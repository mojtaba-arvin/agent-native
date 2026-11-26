#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

python3 - <<'PY'
import ast
from pathlib import Path

source_path = Path("experiments/e011/semantics.py")
tests_path = Path("experiments/e011/test_semantics.py")
source = ast.parse(source_path.read_text(encoding="utf-8"))
tests = ast.parse(tests_path.read_text(encoding="utf-8"))

lifecycle = next(
    (node for node in source.body if isinstance(node, ast.ClassDef) and node.name == "CallLifecycle"),
    None,
)
if lifecycle is None:
    raise SystemExit("T25 acceptance: CallLifecycle is missing")

frozen = any(
    isinstance(dec, ast.Call)
    and isinstance(dec.func, ast.Name)
    and dec.func.id == "dataclass"
    and any(k.arg == "frozen" and isinstance(k.value, ast.Constant) and k.value.value is True for k in dec.keywords)
    for dec in lifecycle.decorator_list
)
if not frozen:
    raise SystemExit("T25 acceptance: CallLifecycle must be a frozen dataclass")

if not any(isinstance(node, ast.FunctionDef) and node.name == "__post_init__" for node in lifecycle.body):
    raise SystemExit("T25 acceptance: constructor invariants are not validated")

test_names = {
    node.name for node in ast.walk(tests)
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
}
required = {
    "test_constructor_rejects_non_enum_state",
    "test_constructor_rejects_inconsistent_history",
    "test_constructor_rejects_illegal_history_transition",
    "test_lifecycle_state_and_history_cannot_be_mutated_directly",
}
missing = sorted(required - test_names)
if missing:
    raise SystemExit("T25 acceptance: missing regression tests: " + ", ".join(missing))

print("T25 acceptance: immutable lifecycle snapshots and constructor invariants are present.")
PY
