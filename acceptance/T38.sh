#!/usr/bin/env bash
set -euo pipefail

python - <<'PY'
import ast
from pathlib import Path

source = Path("experiments/e009/local_agent.py").read_text(encoding="utf-8")
tree = ast.parse(source)
delimiters = [
    node.value
    for node in ast.walk(tree)
    if isinstance(node, ast.Constant)
    and isinstance(node.value, str)
    and node.value.startswith("Session surface JSON:")
]
assert "Session surface JSON:\n" in delimiters, (
    "the initial session-surface prompt must contain an actual newline"
)
assert "Session surface JSON:\\n" not in delimiters, (
    "the initial session-surface prompt still contains a literal backslash-n"
)
PY

python -m unittest discover -s experiments/e009 -p 'test_local_agent.py' -v
