#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

python3 - <<'PY'
import ast
from pathlib import Path

source = ast.parse(Path("experiments/e009/local_agent.py").read_text(encoding="utf-8"))
tests = ast.parse(Path("experiments/e009/test_local_agent.py").read_text(encoding="utf-8"))

function = next(
    node for node in source.body
    if isinstance(node, ast.FunctionDef) and node.name == "_deduplicate_tool_outcomes"
)
source_text = ast.unparse(function)
if 'request:{tool_name}:{request_id}' not in source_text:
    raise SystemExit("T26 acceptance: compaction identity must include both tool name and request ID")

test_names = {
    node.name for node in ast.walk(tests)
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
}
required = {
    "test_compaction_deduplicates_outcomes_and_preserves_latest_guidance",
    "test_compaction_does_not_merge_different_tools_with_reused_request_id",
}
missing = sorted(required - test_names)
if missing:
    raise SystemExit("T26 acceptance: missing regression tests: " + ", ".join(missing))

print("T26 acceptance: tool-scoped compaction identity and cross-tool collision regression are present.")
PY
