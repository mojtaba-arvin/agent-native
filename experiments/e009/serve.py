"""Run the E-009 Catalog vertical slice on a loopback HTTP socket.

This entry point is development/demo infrastructure. It requires a token from
the environment, binds only to loopback, and is not a production deployment
or production authentication configuration.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
import threading
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
E009_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(E009_ROOT))
sys.path.insert(0, str(ROOT / "experiments" / "e004"))

from catalog import build_catalog_handlers  # noqa: E402
from audit import SQLiteAuditSink  # noqa: E402
from http_server import create_server  # noqa: E402
from identity import MemoryIdentityProvider  # noqa: E402
from kernel import ServiceRuntime, load_service_ir  # noqa: E402
from repository import SQLiteCatalogRepository  # noqa: E402
from work_store import DurableWorkStore  # noqa: E402
from worker import CatalogWorker, OutboxRelay  # noqa: E402
from security_model import Grant, RequestContext  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, default=Path("./agent-native-e009.sqlite3"))
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--host", choices=("127.0.0.1", "0.0.0.0"), default="127.0.0.1")
    parser.add_argument("--max-concurrency", type=int, default=64)
    parser.add_argument("--worker-poll-seconds", type=float, default=0.25)
    parser.add_argument("--relay-poll-seconds", type=float, default=0.25)
    parser.add_argument("--worker-lease-seconds", type=int, default=30)
    parser.add_argument("--relay-lease-seconds", type=int, default=15)
    parser.add_argument("--max-outstanding-jobs", type=int, default=1000)
    parser.add_argument("--max-running-jobs", type=int, default=16)
    parser.add_argument("--audit-batch-size", type=int, default=32)
    parser.add_argument("--audit-batch-delay-ms", type=float, default=2.0)
    parser.add_argument("--job-batch-size", type=int, default=32)
    parser.add_argument("--job-batch-delay-ms", type=float, default=0.5)
    args = parser.parse_args()
    if args.host != "127.0.0.1" and os.environ.get("AGENT_NATIVE_ALLOW_NON_LOOPBACK") != "1":
        parser.error("non-loopback binding requires AGENT_NATIVE_ALLOW_NON_LOOPBACK=1")
    if not 1 <= args.job_batch_size <= 1024:
        parser.error("--job-batch-size must be between 1 and 1024")
    if (
        not math.isfinite(args.job_batch_delay_ms)
        or not 0 <= args.job_batch_delay_ms <= 50
    ):
        parser.error("job batch delay must be between 0 and 50 ms")
    for name, value in (
        ("worker-poll-seconds", args.worker_poll_seconds),
        ("relay-poll-seconds", args.relay_poll_seconds),
    ):
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(value)
            or value <= 0
        ):
            parser.error(f"--{name} must be a finite positive number")

    if not 1 <= args.audit_batch_size <= 1024:
        parser.error("--audit-batch-size must be between 1 and 1024")
    if (
        not math.isfinite(args.audit_batch_delay_ms)
        or args.audit_batch_delay_ms < 0
        or args.audit_batch_delay_ms > 50
    ):
        parser.error("--audit-batch-delay-ms must be between 0 and 50")

    token = os.environ.get("AGENT_NATIVE_DEMO_TOKEN", "")
    if len(token) < 24:
        parser.error("AGENT_NATIVE_DEMO_TOKEN must contain at least 24 characters")

    grants = (
        Grant("local-operator", "demo-tenant", "items.read", "/items"),
        Grant("local-operator", "demo-tenant", "items.create", "/items"),
        Grant("local-operator", "demo-tenant", "jobs.submit", "/items"),
        Grant("local-operator", "demo-tenant", "jobs.read", "/jobs"),
        Grant("local-operator", "demo-tenant", "jobs.cancel", "/jobs"),
    )
    trusted_context = RequestContext(
        principal_id="local-operator",
        tenant_id="demo-tenant",
        now=0,
        grants=grants,
    )
    identity = MemoryIdentityProvider({token: trusted_context})
    source = (E009_ROOT / "catalog.an").read_text(encoding="utf-8")
    ir = load_service_ir(source)
    repository = SQLiteCatalogRepository(args.database)
    audit_sink = SQLiteAuditSink(
        repository.database,
        max_batch_size=args.audit_batch_size,
        max_batch_delay_seconds=args.audit_batch_delay_ms / 1000,
    )
    try:
        work_store = DurableWorkStore(
            repository.database,
            max_outstanding=args.max_outstanding_jobs,
            max_concurrency=args.max_running_jobs,
            audit_sink=audit_sink,
            max_submit_batch_size=args.job_batch_size,
            max_submit_batch_delay_seconds=args.job_batch_delay_ms / 1000,
        )
    except ValueError as error:
        parser.error(str(error))
    runtime = ServiceRuntime(
        ir,
        handlers=build_catalog_handlers(repository, work_store),
        repository=repository,
        trusted_effects={"repository.read", "repository.write", "queue.submit", "queue.read", "queue.cancel"},
        audit_sink=audit_sink,
    )
    server = create_server(
        runtime,
        identity,
        host=args.host,
        port=args.port,
        max_concurrency=args.max_concurrency,
        allow_non_loopback=(args.host != "127.0.0.1"),
    )

    worker_id = f"catalog-worker-{uuid.uuid4().hex[:12]}"
    relay_id = f"outbox-relay-{uuid.uuid4().hex[:12]}"
    worker = CatalogWorker(
        repository,
        work_store,
        lease_seconds=args.worker_lease_seconds,
    )
    relay = OutboxRelay(
        work_store,
        consumer_id="catalog-local-observer",
        lease_seconds=args.relay_lease_seconds,
    )
    stop = threading.Event()

    def worker_loop() -> None:
        while not stop.is_set():
            try:
                worker.run_once(worker_id=worker_id, now=int(time.time()))
            except Exception as error:
                print(
                    f"[worker] iteration failed: {type(error).__name__}",
                    file=sys.stderr,
                    flush=True,
                )
            stop.wait(args.worker_poll_seconds)

    def relay_loop() -> None:
        while not stop.is_set():
            try:
                relay.run_once(relay_id=relay_id, now=int(time.time()))
            except Exception as error:
                print(
                    f"[outbox] iteration failed: {type(error).__name__}",
                    file=sys.stderr,
                    flush=True,
                )
            stop.wait(args.relay_poll_seconds)

    worker_thread = threading.Thread(
        target=worker_loop,
        name="agent-native-catalog-worker",
        daemon=False,
    )
    relay_thread = threading.Thread(
        target=relay_loop,
        name="agent-native-outbox-relay",
        daemon=False,
    )
    print(
        f"Agent Native E-009 reference kernel listening on "
        f"http://127.0.0.1:{server.server_port} (local demo only) "
        f"with worker={worker_id} relay={relay_id}",
        flush=True,
    )
    worker_thread.start()
    relay_thread.start()
    try:
        server.serve_forever(poll_interval=0.25)
    except KeyboardInterrupt:
        pass
    finally:
        stop.set()
        worker_thread.join()
        relay_thread.join()
        server.server_close()
        print(
            "E009_AUDIT_METRICS=" + json.dumps(audit_sink.metrics(), sort_keys=True),
            flush=True,
        )
        print(
            "E009_WORK_METRICS=" + json.dumps(work_store.metrics(), sort_keys=True),
            flush=True,
        )
        repository.close()


if __name__ == "__main__":
    main()
