"""Production PostgreSQL-backed HTTP server entrypoint for the container image."""

from __future__ import annotations

import json
import math
import os
import re
import signal
import threading
from pathlib import Path
from typing import Any

from .handlers import RuntimeAdapters, built_in_handler_registry
from .host import ServiceHost
from .operations import create_operational_server
from .postgres import PostgresResourceRepository
from .security import CapabilityTokenAuthority


def _required_environment(name: str) -> str:
    value = os.environ.get(name)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"required_environment_missing:{name}")
    return value


def _signing_key() -> bytes:
    value = _required_environment("AGENT_NATIVE_TOKEN_SIGNING_KEY_HEX")
    if len(value) < 64 or len(value) % 2 or re.fullmatch(r"[0-9a-fA-F]+", value) is None:
        raise ValueError("invalid_token_signing_key_hex")
    key = bytes.fromhex(value)
    if len(key) < 32:
        raise ValueError("token_signing_key_too_short")
    return key


def run_server(args: Any) -> int:
    """Build the trusted service host and run bounded HTTP ingress.

    PostgreSQL and token signing material are environment-only inputs; neither
    is accepted on the command line or written to startup logs.
    """
    if (
        isinstance(args.shutdown_timeout_seconds, bool)
        or not isinstance(args.shutdown_timeout_seconds, (int, float))
        or not math.isfinite(args.shutdown_timeout_seconds)
        or args.shutdown_timeout_seconds < 0
    ):
        raise ValueError("invalid_shutdown_timeout")
    dsn = _required_environment("AGENT_NATIVE_POSTGRES_DSN")
    schema = os.environ.get("AGENT_NATIVE_POSTGRES_SCHEMA", "agent_native")
    authority = CapabilityTokenAuthority(_signing_key())
    services_root = Path(args.services_root).expanduser()

    repository = PostgresResourceRepository(dsn, schema=schema)
    server = None
    previous_handlers = {}
    try:
        host = ServiceHost(
            services_root,
            handlers=built_in_handler_registry(),
            adapters=RuntimeAdapters(repository=repository, jobs=object(), events=object()),
            audit_sink=repository,
            authenticator=authority,
        )
        server = create_operational_server(
            host,
            host=args.host,
            port=args.port,
            max_concurrency=args.max_concurrency,
            max_request_body_bytes=args.max_request_body_bytes,
            request_timeout_seconds=args.request_timeout_seconds,
            allow_non_loopback=args.allow_non_loopback,
        )

        stopping = threading.Event()
        shutdown_thread: threading.Thread | None = None

        def request_shutdown(_signum, _frame) -> None:
            nonlocal shutdown_thread
            if stopping.is_set():
                return
            stopping.set()
            shutdown_thread = threading.Thread(
                target=server.shutdown_gracefully,
                kwargs={"timeout_seconds": args.shutdown_timeout_seconds},
                name="agent-native-shutdown",
                daemon=True,
            )
            shutdown_thread.start()

        for signum in (signal.SIGINT, signal.SIGTERM):
            previous_handlers[signum] = signal.getsignal(signum)
            signal.signal(signum, request_shutdown)

        print(json.dumps({
            "event": "server_started",
            "host": args.host,
            "port": server.server_address[1],
            "services": list(host.service_ids),
            "postgres_schema": schema,
            "max_concurrency": args.max_concurrency,
            "max_request_body_bytes": args.max_request_body_bytes,
        }, sort_keys=True), flush=True)
        server.serve_forever(poll_interval=0.25)
        return 0
    finally:
        if server is not None:
            if shutdown_thread is not None:
                shutdown_thread.join(timeout=args.shutdown_timeout_seconds + 2.0)
            if not server._serve_stopped.is_set():
                server.shutdown_gracefully(timeout_seconds=args.shutdown_timeout_seconds)
            server.server_close()
        for signum, handler in previous_handlers.items():
            signal.signal(signum, handler)
        repository.close()
