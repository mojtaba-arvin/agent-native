#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

python3 - <<'PY'
from pathlib import Path
import re
import sys

workflow_path = Path(".github/workflows/nightly-acceptance.yml")
if not workflow_path.is_file():
    raise SystemExit("T19 acceptance: nightly-acceptance workflow is missing")

workflow = workflow_path.read_text(encoding="utf-8")
required = {
    "daily schedule": 'cron: "17 3 * * *"',
    "all acceptance scripts": 'scripts=(acceptance/*.sh)',
    "first-parent 50-commit window": "git rev-list --first-parent -n 50 research/reboot-core",
    "job-summary pass list": '"## Nightly acceptance" >> "$GITHUB_STEP_SUMMARY"',
    "process-health summary": '"## Process health" >> "$GITHUB_STEP_SUMMARY"',
    "10% process threshold": "ratio > 0.10",
}
missing = [label for label, marker in required.items() if marker not in workflow]
if missing:
    raise SystemExit("T19 acceptance: nightly workflow is missing: " + ", ".join(missing))

# DECISIONS.json is the canonical decision registry on the current base
# (T22); it is explicitly permitted for kind:decision PRs. The ratio
# classifier currently counts project-control/* but silently misses this
# root-level state file, undercounting process/state changes.
case = re.search(r'case "\$path" in(?P<body>.*?)\n\s*esac', workflow, re.S)
if case is None:
    raise SystemExit("T19 acceptance: docs/state path classifier is missing")
if "DECISIONS.json" not in case.group("body"):
    raise SystemExit(
        "T19 acceptance: docs/state ratio omits canonical root DECISIONS.json; "
        "T22 made this the permitted decision registry, so process health is undercounted"
    )

print("T19 acceptance: nightly acceptance and process-health contract is present.")
PY
