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

classes = {node.name: node for node in source.body if isinstance(node, ast.ClassDef)}
missing = []

def has_property(class_node, name):
    return any(
        isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name == name
        and any(isinstance(dec, ast.Name) and dec.id == "property" for dec in node.decorator_list)
        for node in class_node.body
    )

for class_name, properties in {
    "CallLifecycle": {"capacity_held"},
    "DeadlineBudget": {"exhausted", "can_dispatch"},
}.items():
    node = classes.get(class_name)
    if node is None:
        missing.append(class_name)
        continue
    for prop in sorted(properties):
        if not has_property(node, prop):
            missing.append(f"{class_name}.{prop}")

test_names = {
    node.name
    for node in ast.walk(tests)
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
}
required_tests = {
    "test_cancel_race_preserves_a_committed_completion",
    "test_unknown_outcome_keeps_capacity_until_reconciled",
    "test_exhausted_deadline_cannot_start_another_hop",
    "test_non_enum_transition_is_rejected_without_corrupting_history",
}
missing.extend(sorted(required_tests - test_names))

if missing:
    raise SystemExit("T24 acceptance: missing lifecycle/deadline contract: " + ", ".join(missing))
print("T24 acceptance: lifecycle capacity, cancellation race, and deadline contract are present.")
PY
