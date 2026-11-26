#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

python3 - <<'PY'
import ast
from pathlib import Path

identity_path = Path("experiments/e009/identity.py")
serve_path = Path("experiments/e009/serve.py")
test_path = Path("experiments/e009/test_identity.py")

identity = identity_path.read_text(encoding="utf-8")
serve = serve_path.read_text(encoding="utf-8")
tests = ast.parse(test_path.read_text(encoding="utf-8"))

for marker in (
    "TrustedContextFactory = Callable[[], RequestContext]",
    "context = matched() if callable(matched) else matched",
    "trusted_context_factory_must_return_request_context",
):
    if marker not in identity:
        raise SystemExit(f"T36 acceptance: identity provider is missing: {marker}")

if "identity = MemoryIdentityProvider({token: authenticate_demo_operator})" not in serve:
    raise SystemExit("T36 acceptance: demo host does not defer context construction to authentication")
if "trusted_context = RequestContext(" in serve:
    raise SystemExit("T36 acceptance: ambient RequestContext is still constructed during host startup")

required_tests = {
    "test_context_factory_runs_only_after_matching_bearer_authentication",
    "test_context_factory_creates_a_fresh_request_context_per_authentication",
    "test_prebuilt_context_remains_supported_for_existing_fixtures",
    "test_factory_result_must_be_a_request_context",
    "test_invalid_identity_mapping_value_is_rejected_at_construction",
}
actual_tests = {
    node.name for node in ast.walk(tests)
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
}
missing = sorted(required_tests - actual_tests)
if missing:
    raise SystemExit("T36 acceptance: missing identity lifecycle tests: " + ", ".join(missing))

print("T36 acceptance: post-authentication RequestContext construction and regression coverage are present.")
PY

python3 -m unittest experiments.e009.test_identity -v
python3 -m unittest discover -s experiments/e009 -v
