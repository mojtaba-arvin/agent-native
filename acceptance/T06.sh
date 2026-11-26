#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

python3 - <<'PY'
from pathlib import Path
import re
import sys

required = {
    "PostgreSQL E-009 storage test adapter": Path("experiments/e009/test_postgres_storage.py"),
    "PostgreSQL-backed T04 HTTP suite": Path("experiments/e009/test_postgres_http_conformance.py"),
    "Layer 1 PostgreSQL test hook": Path("experiments/e002/test_postgres_reference_adapter.py"),
    "original T04 HTTP suite": Path("experiments/e009/test_http_conformance.py"),
}
missing = [label for label, path in required.items() if not path.is_file()]
if missing:
    print("T06 acceptance: missing PostgreSQL HTTP conformance outputs:")
    for label in missing:
        print(f"- {label}")
    sys.exit(1)

adapter = required["PostgreSQL E-009 storage test adapter"].read_text(encoding="utf-8")
postgres_suite = required["PostgreSQL-backed T04 HTTP suite"].read_text(encoding="utf-8")
layer1_hook = required["Layer 1 PostgreSQL test hook"].read_text(encoding="utf-8")
sqlite_suite = required["original T04 HTTP suite"].read_text(encoding="utf-8")

markers = {
    "PostgreSQL catalog repository": "class PostgresCatalogRepository",
    "PostgreSQL durable audit sink": "class PostgresAuditSink",
    "transaction-scoped idempotency": "pg_advisory_xact_lock",
    "isolated schemas": "CREATE SCHEMA IF NOT EXISTS",
}
missing_adapter = [label for label, marker in markers.items() if marker not in adapter]
if "class PostgresHTTPConformanceTests(HTTPConformanceTests)" not in postgres_suite:
    missing_adapter.append("PostgreSQL suite reuses the T04 black-box HTTP test cases")
if "test_t06_http_conformance_on_postgres" not in layer1_hook:
    missing_adapter.append("Layer 1 executes the PostgreSQL-backed T04 suite")
if len(re.findall(r"^    def test_", sqlite_suite, re.M)) < 14:
    missing_adapter.append("the complete 14-case T04 HTTP conformance suite")

if missing_adapter:
    print("T06 acceptance: incomplete PostgreSQL conformance wiring:")
    for item in missing_adapter:
        print(f"- {item}")
    sys.exit(1)

print("T06 acceptance: PostgreSQL adapter and full T04 HTTP suite wiring are present.")
PY

if [[ -n "${AGENT_NATIVE_E002_POSTGRES_DSN:-}" ]]; then
  PYTHONPATH="src:experiments/e009${PYTHONPATH:+:$PYTHONPATH}" \
    python3 -m unittest discover \
      -s experiments/e009 \
      -p "test_postgres_http_conformance.py" \
      -v
else
  echo "T06 acceptance: PostgreSQL runtime execution is delegated to the Layer 1 PostgreSQL 16.4 job."
fi
