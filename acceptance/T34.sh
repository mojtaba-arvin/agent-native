#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
python3 - <<'PY'
import ast
from pathlib import Path

store_path = Path("experiments/e009/work_store.py")
server_path = Path("experiments/e009/http_server.py")
work_tests_path = Path("experiments/e009/test_work_store.py")
http_tests_path = Path("experiments/e009/test_http_server.py")
store = store_path.read_text(encoding="utf-8")
server = server_path.read_text(encoding="utf-8")
work_tests = ast.parse(work_tests_path.read_text(encoding="utf-8"))
http_tests = ast.parse(http_tests_path.read_text(encoding="utf-8"))
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
if "def _validated_trace_id(" not in server:
    raise SystemExit("T34 acceptance: validated inbound trace identifier handling is missing")
work_names = {node.name for node in ast.walk(work_tests) if isinstance(node, ast.FunctionDef)}
http_names = {node.name for node in ast.walk(http_tests) if isinstance(node, ast.FunctionDef)}
if "test_recovery_metrics_are_durable_and_count_retries_and_duplicate_delivery" not in work_names:
    raise SystemExit("T34 acceptance: recovery metrics persistence regression is missing")
if "test_validated_trace_header_is_echoed_and_audited" not in http_names:
    raise SystemExit("T34 acceptance: validated trace echo/audit regression is missing")
if "test_malformed_trace_header_is_rejected_without_echo" not in http_names:
    raise SystemExit("T34 acceptance: malformed trace header regression is missing")
print("T34 acceptance: read-only durable recovery metrics and validated request/audit trace correlation are present.")
PY
python3 -m unittest discover -s experiments/e009 -p "test_work_store.py" -v
python3 -m unittest discover -s experiments/e009 -p "test_http_server.py" -v
