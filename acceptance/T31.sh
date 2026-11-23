#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
python3 - <<'PY'
import ast
from pathlib import Path

source_path = Path("experiments/e011/multiprocess.py")
tests_path = Path("experiments/e011/test_multiprocess.py")
source = ast.parse(source_path.read_text(encoding="utf-8"))
tests = ast.parse(tests_path.read_text(encoding="utf-8"))
source_text = source_path.read_text(encoding="utf-8")
required_source = (
    "multiprocessing.get_context(\"spawn\")",
    "BEGIN IMMEDIATE",
    "X-Test-Crash-After-Commit",
    "Idempotency-Key",
    "PRIMARY KEY (tenant_id, operation, idempotency_key)",
)
for marker in required_source:
    if marker not in source_text:
        raise SystemExit(f"T31 acceptance: missing implementation marker: {marker}")
test_names = {node.name for node in ast.walk(tests) if isinstance(node, ast.FunctionDef)}
required_tests = {
    "test_concurrent_duplicate_requests_from_independent_clients_apply_once",
    "test_same_key_with_different_payload_is_conflict",
    "test_crash_after_commit_is_reconciled_after_process_restart",
    "test_precommit_failure_rolls_back_effect_and_same_key_can_retry",
    "test_tenant_assertion_and_capability_are_not_caller_authority",
}
missing = sorted(required_tests - test_names)
if missing:
    raise SystemExit("T31 acceptance: missing failure-model tests: " + ", ".join(missing))
print("T31 acceptance: independent receiver process, durable idempotency, crash/restart, and authorization tests are present.")
PY
python3 -m unittest discover -s experiments/e011 -v
