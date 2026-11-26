#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

python3 - <<'PY'
from pathlib import Path

path = Path("experiments/e007/manual-pilot-operator-runbook.md")
text = path.read_text(encoding="utf-8")

required = {
    "canonical CI workflow": ".github/workflows/ci.yml",
    "manual dispatch contract": "workflow_dispatch",
    "E-007 model suite input": "model_suite=e007",
    "historical marker non-replay rule": "must not be replayed",
}
for label, marker in required.items():
    if marker not in text:
        raise SystemExit(f"T43 acceptance: missing {label} ({marker})")

for stale in (
    "e007-real-agent-eval.yml",
    "one-shot marker-gated push dispatch",
    "one-shot push proxy",
    "exact commit subject",
):
    if stale in text:
        raise SystemExit(
            f"T43 acceptance: stale dispatch instruction remains ({stale}); "
            "use only the current workflow_dispatch contract"
        )

print("T43 acceptance: E-007 runbook dispatch instructions match the current workflow.")
PY
