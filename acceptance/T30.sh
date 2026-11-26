#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
python3 - <<'PY'
import ast
from pathlib import Path

source_path = Path("experiments/e010/demo_apply.py")
tests_path = Path("experiments/e010/test_demo_apply.py")
source = ast.parse(source_path.read_text(encoding="utf-8"))
tests = ast.parse(tests_path.read_text(encoding="utf-8"))
source_text = source_path.read_text(encoding="utf-8")

coordinator = next(node for node in source.body if isinstance(node, ast.ClassDef) and node.name == "SandboxApplyCoordinator")
methods = {node.name: node for node in coordinator.body if isinstance(node, ast.FunctionDef)}
if "_apply_lock" not in source_text or "threading.RLock" not in source_text:
    raise SystemExit("T30 acceptance: process-local apply serialization is missing")
if "self.applied_revision == revision" not in source_text or "self._applied_result" not in source_text:
    raise SystemExit("T30 acceptance: same-revision idempotency cache is missing")
apply_method = methods.get("_apply_locked")
if apply_method is None:
    raise SystemExit("T30 acceptance: serialized apply implementation is missing")
method_source = ast.get_source_segment(source_text, apply_method) or ""
if method_source.find("candidate_runtime.dispatch") < 0 or method_source.find("self.audit_sink({") < method_source.find("candidate_runtime.dispatch"):
    raise SystemExit("T30 acceptance: candidate must be smoke-tested before apply audit")
test_names = {node.name for node in ast.walk(tests) if isinstance(node, ast.FunctionDef)}
required = {
    "test_concurrent_same_revision_publishes_once",
    "test_failed_candidate_smoke_keeps_previous_runtime_and_revision",
    "test_sandbox_apply_rejects_modified_baseline_contract",
    "test_apply_without_validation_and_plan_is_rejected",
}
missing = sorted(required - test_names)
if missing:
    raise SystemExit("T30 acceptance: missing regressions: " + ", ".join(missing))
print("T30 acceptance: serialization, replay cache, pre-publication smoke, and failure/concurrency regressions are present.")
PY
python3 -m unittest discover -s experiments/e010 -v
