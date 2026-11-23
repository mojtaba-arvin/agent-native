#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
python3 - <<'PY'
import ast
from pathlib import Path

store_path = Path("experiments/e009/work_store.py")
server_path = Path("experiments/e009/http_server.py")
tests_path = Path("experiments/e009/test_work_store.py")
store = store_path.read_text(encoding="utf-8")
server = server_path.read_text(encoding="utf-8")
tests = ast.parse(tests_path.read_text(encoding="utf-8"))
for marker in (
    "def recovery_metrics(",
    "PRAGMA query_only = ON",
    "durable_inbox_delivery_metrics",
    "duplicate_deliveries = duplicate_deliveries + 1",
):
    if marker not in store:
        raise SystemExit(f"T34 acceptance: missing durable recovery metric marker: {marker}")
if 'self.send_header("X-Trace-ID", request_id)' not in server:
    raise SystemExit("T34 acceptance: response trace correlation header is missing")
test_names = {node.name for node in ast.walk(tests) if isinstance(node, ast.FunctionDef)}
if "test_recovery_metrics_are_durable_and_count_retries_and_duplicate_delivery" not in test_names:
    raise SystemExit("T34 acceptance: recovery metrics persistence regression is missing")
print("T34 acceptance: read-only durable recovery metrics and request/audit trace correlation are present.")
PY
python3 -m unittest discover -s experiments/e009 -p "test_work_store.py" -v
python3 -m unittest discover -s experiments/e009 -p "test_http_server.py" -v
