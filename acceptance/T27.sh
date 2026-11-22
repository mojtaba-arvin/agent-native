#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

python3 - <<'PY'
import ast
from pathlib import Path

server_path = Path("experiments/e009/http_server.py")
tests_path = Path("experiments/e009/test_http_server.py")
readme_path = Path("experiments/e009/README.md")
server_source = server_path.read_text(encoding="utf-8")
tests_source = tests_path.read_text(encoding="utf-8")
readme_source = readme_path.read_text(encoding="utf-8")
server = ast.parse(server_source, filename=str(server_path))
tests = ast.parse(tests_source, filename=str(tests_path))

server_class = next(
    node for node in server.body
    if isinstance(node, ast.ClassDef) and node.name == "BoundedThreadingHTTPServer"
)
server_class_source = ast.get_source_segment(server_source, server_class) or ""
for marker in ("request_read_timeout", "request.settimeout"):
    if marker not in server_class_source:
        raise SystemExit(f"T27 acceptance: missing bounded socket read-timeout marker: {marker}")

create_server = next(
    node for node in server.body
    if isinstance(node, ast.FunctionDef) and node.name == "create_server"
)
create_source = ast.get_source_segment(server_source, create_server) or ""
if "request_read_timeout" not in create_source:
    raise SystemExit("T27 acceptance: create_server must expose the read-timeout setting")

test_names = {
    node.name for node in ast.walk(tests)
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
}
required = {
    "test_stalled_partial_header_releases_admission_slot",
    "test_stalled_partial_body_releases_admission_slot",
}
missing = sorted(required - test_names)
if missing:
    raise SystemExit("T27 acceptance: missing slow-client regressions: " + ", ".join(missing))

if "request read timeout" not in readme_source.lower():
    raise SystemExit("T27 acceptance: README must document request read timeout semantics")

print("T27 acceptance: finite socket read timeout, slow-header/body regressions, and documentation are present.")
PY

python3 -m unittest experiments.e009.test_http_server
