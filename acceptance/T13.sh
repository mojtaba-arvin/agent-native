#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

python3 - <<'PY'
from pathlib import Path
import sys

migration = Path("src/agent_native/migrations.py")
postgres = Path("src/agent_native/postgres.py")
production_tests = Path("tests/test_production_core_postgres.py")
crash_tests = Path("experiments/e002/test_postgres_reference_adapter.py")
required = (migration, postgres, production_tests, crash_tests)
missing = [str(path) for path in required if not path.is_file()]
if missing:
    print("T13 acceptance: missing IR migration / transactional persistence outputs:")
    for path in missing:
        print(f"- {path}")
    sys.exit(1)

migration_text = migration.read_text(encoding="utf-8")
postgres_text = postgres.read_text(encoding="utf-8")
production_text = production_tests.read_text(encoding="utf-8")
crash_text = crash_tests.read_text(encoding="utf-8")

checks = {
    "migration plan derives schema from validated service IR": "class IRMigrationPlanner" in migration_text and "def from_service(" in migration_text,
    "migrations are applied transactionally and tracked": "def apply_migrations(" in postgres_text and "schema_migrations" in postgres_text,
    "data, audit and outbox share one database transaction": "write_in_transaction" in postgres_text and "audit_log" in postgres_text and "outbox" in postgres_text,
    "production tests verify atomic write and rollback": "test_mutation_commits_data_audit_and_outbox_atomically" in production_text and "test_mutation_failure_rolls_back_data_audit_and_outbox" in production_text,
    "production tests verify migration from catalog and inventory IR": "test_migrations_are_derived_from_catalog_and_inventory_ir" in production_text,
    "SIGKILL recovery is exercised after commit before response": "test_sigkill_after_commit_before_response_reconciles" in crash_text and "signal.SIGKILL" in crash_text,
}
failed = [label for label, passed in checks.items() if not passed]
if failed:
    print("T13 acceptance: durable transaction / IR migration contract is incomplete:")
    for label in failed:
        print(f"- {label}")
    sys.exit(1)

print("T13 acceptance: IR-derived PostgreSQL migrations, atomic data/audit/outbox writes, rollback, and SIGKILL recovery contract is present.")
PY

PYTHONPATH="src:experiments/e009:experiments/e002${PYTHONPATH:+:$PYTHONPATH}" python3 -m unittest tests.test_production_core_postgres -v
PYTHONPATH="src:experiments/e009:experiments/e002${PYTHONPATH:+:$PYTHONPATH}" python3 -m unittest experiments.e002.test_postgres_reference_adapter -v
