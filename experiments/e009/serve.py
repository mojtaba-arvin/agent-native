"""Run the E-009 Catalog vertical slice on a loopback HTTP socket.

This entry point is development/demo infrastructure. It requires a token from
the environment, binds only to loopback, and is not a production deployment
or production authentication configuration.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
E009_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(E009_ROOT))
sys.path.insert(0, str(ROOT / "experiments" / "e004"))

from catalog import build_catalog_handlers  # noqa: E402
from http_server import create_server  # noqa: E402
from identity import MemoryIdentityProvider  # noqa: E402
from kernel import ServiceRuntime, load_service_ir  # noqa: E402
from repository import SQLiteCatalogRepository  # noqa: E402
from security_model import Grant, RequestContext  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, default=Path("./agent-native-e009.sqlite3"))
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--max-concurrency", type=int, default=64)
    args = parser.parse_args()

    token = os.environ.get("AGENT_NATIVE_DEMO_TOKEN", "")
    if len(token) < 24:
        parser.error("AGENT_NATIVE_DEMO_TOKEN must contain at least 24 characters")

    grants = (
        Grant("local-operator", "demo-tenant", "items.read", "/items"),
        Grant("local-operator", "demo-tenant", "items.create", "/items"),
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
    runtime = ServiceRuntime(
        ir,
        handlers=build_catalog_handlers(repository),
        repository=repository,
        trusted_effects={"repository.read", "repository.write"},
    )
    server = create_server(
        runtime,
        identity,
        host="127.0.0.1",
        port=args.port,
        max_concurrency=args.max_concurrency,
    )

    print(
        f"Agent Native E-009 reference kernel listening on "
        f"http://127.0.0.1:{server.server_port} (local demo only)",
        flush=True,
    )
    try:
        server.serve_forever(poll_interval=0.25)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        repository.close()


if __name__ == "__main__":
    main()
