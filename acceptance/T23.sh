#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

python3 - <<'PY'
import ast
from pathlib import Path

agent_path = Path("experiments/e009/local_agent.py")
tests_path = Path("experiments/e009/test_local_agent.py")
agent = ast.parse(agent_path.read_text(encoding="utf-8"), filename=str(agent_path))
tests = ast.parse(tests_path.read_text(encoding="utf-8"), filename=str(tests_path))

functions = {
    node.name: node
    for node in agent.body
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
}
required_functions = {
    "_compact_tool_outcome",
    "_deduplicate_tool_outcomes",
    "_duplicate_completed_tool_response",
}
missing_functions = sorted(required_functions - functions.keys())
if missing_functions:
    raise SystemExit("T23 acceptance: missing implementation functions: " + ", ".join(missing_functions))

runner = next(
    (node for node in agent.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == "run"),
    None,
)
if runner is None or "_duplicate_completed_tool_response" not in {
    node.id for node in ast.walk(runner) if isinstance(node, ast.Name)
}:
    raise SystemExit("T23 acceptance: duplicate guard is not wired into the agent execution loop")

test_class = next(
    (node for node in tests.body if isinstance(node, ast.ClassDef) and node.name == "LocalAgentRunnerTests"),
    None,
)
if test_class is None:
    raise SystemExit("T23 acceptance: LocalAgentRunnerTests class is missing")

test_names = {
    node.name for node in test_class.body
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
}
required_tests = {
    "test_duplicate_schema_discovery_is_intercepted_with_native_next_action",
    "test_duplicate_inspection_is_intercepted_without_repeating_full_payload",
    "test_compaction_deduplicates_outcomes_and_preserves_latest_guidance",
}
missing_tests = sorted(required_tests - test_names)
if missing_tests:
    raise SystemExit("T23 acceptance: missing regression tests: " + ", ".join(missing_tests))

source = tests_path.read_text(encoding="utf-8")
for marker in ('"runner_duplicate_guard"', '"INSPECTION_ALREADY_COMPLETED"', '"SCHEMA_ALREADY_DISCOVERED"'):
    if marker not in source:
        raise SystemExit(f"T23 acceptance: missing trace/diagnostic assertion {marker}")

print("T23 acceptance: duplicate discovery guard, outcome compaction, and regression assertions are present.")
PY
