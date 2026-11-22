#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

python3 - <<'PY'
import ast
from pathlib import Path

agent_path = Path("experiments/e009/local_agent.py")
tests_path = Path("experiments/e009/test_local_agent.py")
agent_source = agent_path.read_text(encoding="utf-8")
tests_source = tests_path.read_text(encoding="utf-8")
agent = ast.parse(agent_source, filename=str(agent_path))
tests = ast.parse(tests_source, filename=str(tests_path))

deduplicate = next(
    (node for node in agent.body if isinstance(node, ast.FunctionDef) and node.name == "_deduplicate_tool_outcomes"),
    None,
)
if deduplicate is None:
    raise SystemExit("T26 acceptance: _deduplicate_tool_outcomes is missing")
deduplicate_source = ast.get_source_segment(agent_source, deduplicate) or ""
for marker in ("successful_positions", "successful", "failed:"):
    if marker not in deduplicate_source:
        raise SystemExit(f"T26 acceptance: failed-outcome preservation marker is missing: {marker}")

test_names = {
    node.name for node in ast.walk(tests)
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
}
required_tests = {
    "test_compaction_preserves_each_repeated_failed_request",
    "test_full_runner_gateway_provider_protocol_with_deterministic_provider",
    "test_duplicate_schema_discovery_is_intercepted_with_native_next_action",
    "test_duplicate_inspection_is_intercepted_without_repeating_full_payload",
    "test_compaction_deduplicates_outcomes_and_preserves_latest_guidance",
}
missing = sorted(required_tests - test_names)
if missing:
    raise SystemExit("T26 acceptance: missing regression tests: " + ", ".join(missing))

integration = next(
    node for node in ast.walk(tests)
    if isinstance(node, ast.FunctionDef)
    and node.name == "test_full_runner_gateway_provider_protocol_with_deterministic_provider"
)
integration_source = ast.get_source_segment(tests_source, integration) or ""
for marker in ('"runner_duplicate_guard"', '"SCHEMA_ALREADY_DISCOVERED"', '"tool_definition_names"'):
    if marker not in integration_source:
        raise SystemExit(f"T26 acceptance: integration trace/schema assertion is missing: {marker}")

print("T26 acceptance: failed-outcome preservation and end-to-end duplicate-discovery coverage are present.")
PY

python3 -m unittest experiments.e009.test_local_agent
