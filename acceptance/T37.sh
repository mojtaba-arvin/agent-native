#!/usr/bin/env bash
set -euo pipefail

python - <<'PY'
import json
from pathlib import Path

metrics = Path("experiments/e007/metrics.py").read_text(encoding="utf-8")
schema = json.loads(Path("experiments/e007/trace.schema.json").read_text(encoding="utf-8"))
assert '"service.propose_delta"' in metrics, "runtime validator does not allow service.propose_delta"
rule = next(
    item for item in schema["allOf"]
    if item.get("if", {}).get("required") == ["change_set_id"]
)
assert "service.propose_delta" in rule["then"]["properties"]["tool_name"]["enum"], (
    "trace schema does not allow service.propose_delta"
)
PY

python -m unittest discover -s experiments/e007 -p 'test*.py' -v
python -m json.tool experiments/e007/trace.schema.json >/dev/null
