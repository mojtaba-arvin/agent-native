#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

python3 - <<'PY'
import ast
from pathlib import Path

source_path = Path("experiments/e009/local_agent.py")
tests_path = Path("experiments/e009/test_local_agent.py")
source = ast.parse(source_path.read_text(encoding="utf-8"), filename=str(source_path))
tests = ast.parse(tests_path.read_text(encoding="utf-8"), filename=str(tests_path))

function = next(
    (node for node in source.body
     if isinstance(node, ast.FunctionDef) and node.name == "_deduplicate_tool_outcomes"),
    None,
)
if function is None:
    raise SystemExit("T28 acceptance: _deduplicate_tool_outcomes is missing")

has_structured_identity = any(
    isinstance(node, ast.Assign)
    and any(isinstance(target, ast.Name) and target.id == "key" for target in node.targets)
    and isinstance(node.value, ast.Tuple)
    and len(node.value.elts) == 3
    and isinstance(node.value.elts[0], ast.Constant)
    and node.value.elts[0].value == "request"
    and isinstance(node.value.elts[1], ast.Name)
    and node.value.elts[1].id == "tool_name"
    and isinstance(node.value.elts[2], ast.Name)
    and node.value.elts[2].id == "request_id"
    for node in ast.walk(function)
)
if not has_structured_identity:
    raise SystemExit(
        "T28 acceptance: successful request identity must be the structured "
        "('request', tool_name, request_id) tuple"
    )

test_names = {
    node.name for node in ast.walk(tests)
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
}
required = {
    "test_compaction_deduplicates_outcomes_and_preserves_latest_guidance",
    "test_compaction_preserves_each_repeated_failed_request",
    "test_compaction_does_not_merge_different_tools_with_reused_request_id",
    "test_compaction_identity_is_unambiguous_when_components_contain_delimiters",
}
missing = sorted(required - test_names)
if missing:
    raise SystemExit("T28 acceptance: missing regression tests: " + ", ".join(missing))

print("T28 acceptance: structured tool/request identity and collision regressions are present.")
PY

python3 -m unittest experiments.e009.test_local_agent
