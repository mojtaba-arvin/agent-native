"""Small operational CLI for the E-009 durable worker and outbox prototype."""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from repository import SQLiteCatalogRepository
from worker import CatalogWorker, OutboxRelay
from work_store import DurableWorkStore


def _now(value: int | None) -> int:
    return int(time.time()) if value is None else value


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", required=True, type=Path)
    subparsers = parser.add_subparsers(dest="command", required=True)

    worker = subparsers.add_parser("worker-once")
    worker.add_argument("--worker-id", required=True)
    worker.add_argument("--now", type=int)
    worker.add_argument("--lease-seconds", type=int, default=30)

    relay = subparsers.add_parser("relay-once")
    relay.add_argument("--relay-id", required=True)
    relay.add_argument("--consumer-id", default="catalog-observer")
    relay.add_argument("--now", type=int)
    relay.add_argument("--lease-seconds", type=int, default=15)

    expire = subparsers.add_parser("request-stops")
    expire.add_argument("--now", type=int)

    acknowledge = subparsers.add_parser("worker-stopped")
    acknowledge.add_argument("--task-id", required=True)
    acknowledge.add_argument("--worker-id", required=True)
    acknowledge.add_argument("--lease-token", required=True, type=int)
    acknowledge.add_argument("--now", type=int)
    acknowledge.add_argument("--reason", default="supervisor_confirmed_stop")

    show = subparsers.add_parser("job-show")
    show.add_argument("--tenant-id", required=True)
    show.add_argument("--task-id", required=True)

    args = parser.parse_args()
    database = args.database.expanduser().resolve()
    repository = SQLiteCatalogRepository(database)
    work_store = DurableWorkStore(database)
    now = _now(getattr(args, "now", None))

    try:
        if args.command == "worker-once":
            worker = CatalogWorker(
                repository,
                work_store,
                lease_seconds=args.lease_seconds,
            )
            result = worker.run_once(worker_id=args.worker_id, now=now)
        elif args.command == "relay-once":
            relay_runner = OutboxRelay(
                work_store,
                consumer_id=args.consumer_id,
                lease_seconds=args.lease_seconds,
            )
            result = relay_runner.run_once(relay_id=args.relay_id, now=now)
        elif args.command == "request-stops":
            expired = work_store.request_expirations(now=now)
            leases = work_store.request_expired_job_stops(now=now)
            result = {
                **expired,
                "expired_leases_requiring_stop_ack": leases,
                "note": "A stop request does not free worker capacity; acknowledge only after the worker is confirmed stopped.",
            }
        elif args.command == "worker-stopped":
            result = work_store.acknowledge_stopped(
                task_id=args.task_id,
                worker_id=args.worker_id,
                lease_token=args.lease_token,
                now=now,
                reason=args.reason,
            )
        elif args.command == "job-show":
            result = work_store.get_job(
                tenant_id=args.tenant_id,
                task_id=args.task_id,
            )
        else:
            parser.error("unsupported_command")

        print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2))
    finally:
        repository.close()


if __name__ == "__main__":
    main()
