#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

python3 - <<'PY'
from pathlib import Path
import sys

required_files = {
    "normative storage contract": Path("experiments/e002/storage-conformance-contract.md"),
    "SQLite reference adapter": Path("experiments/e002/sqlite_reference_adapter.py"),
    "PostgreSQL reference adapter": Path("experiments/e002/postgres_reference_adapter.py"),
    "shared deterministic trace runner": Path("experiments/e002/trace_runner.py"),
    "SQLite reference tests": Path("experiments/e002/test_sqlite_reference_adapter.py"),
    "PostgreSQL conformance tests": Path("experiments/e002/test_postgres_reference_adapter.py"),
    "cross-engine parity tests": Path("experiments/e002/test_cross_engine_trace_parity.py"),
    "CI PostgreSQL service": Path(".github/workflows/ci.yml"),
}
missing_files = [name for name, path in required_files.items() if not path.is_file()]
if missing_files:
    print("T05 acceptance: missing storage-conformance outputs:")
    for name in missing_files:
        print(f"- {name}")
    sys.exit(1)

postgres_tests = Path("experiments/e002/test_postgres_reference_adapter.py").read_text(encoding="utf-8")
parity_tests = Path("experiments/e002/test_cross_engine_trace_parity.py").read_text(encoding="utf-8")
postgres_adapter = Path("experiments/e002/postgres_reference_adapter.py").read_text(encoding="utf-8")
sqlite_adapter = Path("experiments/e002/sqlite_reference_adapter.py").read_text(encoding="utf-8")
contract = Path("experiments/e002/storage-conformance-contract.md").read_text(encoding="utf-8")
ci = Path(".github/workflows/ci.yml").read_text(encoding="utf-8")

postgres_markers = (
    "def test_atomic_admission_and_engine_durability_metadata",
    "def test_failure_after_each_precommit_write_rolls_back_all_records",
    "def test_commit_then_process_crash_before_response_reconciles",
    "def test_same_key_replay_conflict_and_tenant_operation_scope",
    "def test_32_concurrent_same_hash_submissions_have_one_winner",
    "def test_32_concurrent_different_hashes_have_one_winner",
    "def test_audit_storage_outage_fails_closed",
    "def test_audit_is_append_only",
    "def test_outbox_lease_expiry_fences_stale_acknowledgement",
    "def test_append_audit_sequence_survives_reopen",
)
missing_postgres = [marker for marker in postgres_markers if marker not in postgres_tests]

parity_markers = (
    "def test_process_crash_after_commit_reconciles_identically_on_both_engines",
    "def test_precommit_faults_have_identical_atomic_rollback_on_both_engines",
    "def test_identical_generated_traces_have_identical_sqlite_and_postgres_outcomes",
    "def test_canonical_request_hashes_match_across_engines",
    "range(20261118, 20261143)",
    "len(seeds) * 60",
)
missing_parity = [marker for marker in parity_markers if marker not in parity_tests]

implementation_markers = (
    'CANONICALIZATION_VERSION = "json-sort-keys-compact-utf8-v1"',
    "def append_audit(",
    "def admit_job(",
    "def lookup_idempotency(",
    "def claim_outbox(",
    "def ack_outbox(",
    "def recover(",
    '"fsync"',
    '"synchronous_commit"',
)
missing_adapter = [
    marker for marker in implementation_markers
    if marker not in postgres_adapter
]
if 'CANONICALIZATION_VERSION = "json-sort-keys-compact-utf8-v1"' not in sqlite_adapter:
    missing_adapter.append("SQLite versioned canonicalization identifier")

ci_markers = (
    "postgres:16.4",
    "AGENT_NATIVE_E002_POSTGRES_DSN",
    'psycopg[binary]==3.2.9',
    'test_postgres_reference_adapter.py',
    'test_cross_engine_trace_parity.py',
)
missing_ci = [marker for marker in ci_markers if marker not in ci]

contract_markers = (
    "local durable commit",
    "atomic",
    "idempotency",
    "audit",
    "recovery",
    "25 deterministic seeds",
    "1,500 total",
    "not a product database choice",
)
missing_contract = [marker for marker in contract_markers if marker not in contract]

problems = []
for label, missing in (
    ("PostgreSQL conformance cases", missing_postgres),
    ("cross-engine parity cases", missing_parity),
    ("adapter API and durability metadata", missing_adapter),
    ("CI PostgreSQL execution wiring", missing_ci),
    ("contract and evidence record", missing_contract),
):
    if missing:
        problems.append((label, missing))

if problems:
    print("T05 acceptance: storage conformance is incomplete:")
    for label, missing in problems:
        print(f"- {label}:")
        for marker in missing:
            print(f"  - {marker}")
    sys.exit(1)

print("T05 acceptance: PostgreSQL atomicity/idempotency/audit/recovery,")
print("shared SQLite/PostgreSQL trace parity, and CI execution wiring are present.")
PY

PYTHONPATH=experiments/e002 python3 - <<'PY'
import os
import unittest

patterns = ["test_sqlite_reference_adapter.py"]
if os.environ.get("AGENT_NATIVE_E002_POSTGRES_DSN"):
    try:
        import psycopg  # noqa: F401
    except ImportError as error:
        raise SystemExit("T05 acceptance: a PostgreSQL DSN is set but psycopg is unavailable.") from error
    patterns.extend((
        "test_postgres_reference_adapter.py",
        "test_cross_engine_trace_parity.py",
    ))
else:
    print(
        "T05 acceptance: PostgreSQL execution is delegated to the CI Layer 1 "
        "job's disposable PostgreSQL 16.4 service."
    )

loader = unittest.TestLoader()
runner = unittest.TextTestRunner(verbosity=2)
for pattern in patterns:
    suite = loader.discover("experiments/e002", pattern=pattern, top_level_dir="experiments/e002")
    count = suite.countTestCases()
    if count < 1:
        raise SystemExit(f"T05 acceptance: discovery found zero tests for {pattern}.")
    result = runner.run(suite)
    if not result.wasSuccessful():
        raise SystemExit(f"T05 acceptance: {pattern} failed.")
    if result.skipped:
        raise SystemExit(
            f"T05 acceptance: {pattern} skipped {len(result.skipped)} tests; "
            "required conformance cases must execute, not silently skip."
        )
    print(f"T05 acceptance: {pattern}: {result.testsRun} tests passed.")

print("T05 acceptance: reference storage conformance checks passed.")
PY
