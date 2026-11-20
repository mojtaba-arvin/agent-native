#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

python3 - <<'PY'
from pathlib import Path
import sys

plan = Path("docs/V1_PLAN.md").read_text(encoding="utf-8")
required = {
    "section 10": "## 10. Evidence discipline (applies to every task)",
    "pre-registration": "**10.1 Pre-registration for measurement tasks.**",
    "run ledger": "`evidence/ledger.jsonl`",
    "hash-bound claims": "**10.3 Hash-bound claims.**",
    "no silent threshold changes": "**10.4 No silent threshold changes.**",
    "reference implementation contract": "**10.5 Reference implementation is the oracle, not the product.**",
    "negative results": "**10.6 Negative results are evidence.**",
    "cancelled runs excluded from denominators": "excluded from any denominator",
    "run-id requirement": "must carry the `run_id` from the ledger",
    "schema wins": "the schema wins.",
    "failed runs retained": "Do not delete failed-run records",
}
missing = [name for name, text in required.items() if text not in plan]
if missing:
    print("T20 acceptance: missing evidence-discipline requirements:")
    for name in missing:
        print(f"- {name}")
    sys.exit(1)

print("T20 acceptance: all six evidence-discipline rules are present.")
PY
