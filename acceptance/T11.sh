#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

python3 - <<'PY'
from pathlib import Path
import sys

required = {
    "production service registry": Path("src/agent_native/manifest.py"),
    "production request runtime and route dispatch": Path("src/agent_native/runtime.py"),
    "trusted host handler registry": Path("src/agent_native/handlers.py"),
    "frozen IR v1 schema": Path("schemas/service-ir-v1.schema.json"),
    "catalog IR source": Path("services/catalog/service.an"),
    "inventory IR source": Path("services/inventory/service.an"),
    "catalog manifest": Path("services/catalog/service.json"),
    "inventory manifest": Path("services/inventory/service.json"),
    "catalog policy": Path("services/catalog/policy.json"),
    "inventory policy": Path("services/inventory/policy.json"),
    "production PostgreSQL parity tests": Path("tests/test_production_core_postgres.py"),
}
missing = [label for label, path in required.items() if not path.is_file()]
if missing:
    print("T11 acceptance: missing production core outputs:")
    for label in missing:
        print(f"- {label}")
    sys.exit(1)

manifest = required["production service registry"].read_text(encoding="utf-8")
runtime = required["production request runtime and route dispatch"].read_text(encoding="utf-8")
handlers = required["trusted host handler registry"].read_text(encoding="utf-8")
tests = required["production PostgreSQL parity tests"].read_text(encoding="utf-8")

checks = {
    "IR v1 semantic validation in service registry": "validate_ir" in manifest or "Parser(" in manifest,
    "host-registered handlers, never manifest imports": "class TrustedHandlerRegistry" in handlers,
    "IR-backed runtime dispatch": "class ServiceRuntime" in runtime and "def dispatch(" in runtime,
    "PostgreSQL catalog/inventory integration": "Postgres" in tests and "catalog" in tests.lower() and "inventory" in tests.lower(),
    "deterministic reference trace comparison": "reference_trace" in tests.lower() or "trace" in tests.lower(),
    "negative route and malformed IR coverage": any(x in tests for x in ("unknown_route", "malformed_ir", "invalid_ir", "route_not_found")),
}
failed = [label for label, passed in checks.items() if not passed]
if failed:
    print("T11 acceptance: production-core contract is incomplete:")
    for label in failed:
        print(f"- {label}")
    sys.exit(1)

print("T11 acceptance: production IR loader/router and PostgreSQL catalog/inventory parity test contract is present.")
PY

PYTHONPATH="src:experiments/e009${PYTHONPATH:+:$PYTHONPATH}" python3 -m unittest tests.test_production_core_postgres -v
