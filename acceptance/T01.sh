#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

python3 - <<'PY'
from pathlib import Path
import sys

product = Path("docs/V1_PRODUCT.md")
if not product.is_file():
    print("T01 acceptance: missing docs/V1_PRODUCT.md")
    sys.exit(1)

text = product.read_text(encoding="utf-8")
required = {
    "product contract title": "# Agent Native v0.1 Product Contract",
    "primary user": "AI agents are the primary authors and operators",
    "single PostgreSQL-backed service target": "single PostgreSQL-backed service",
    "one deployable service boundary": "one independently deployable service",
    "HTTP user-visible behavior": "HTTP",
    "authoritative PostgreSQL persistence": "PostgreSQL is the authoritative production persistence target",
    "default-deny security": "default-deny",
    "explicit non-goals": "## Explicit non-goals",
    "acceptance criteria": "## Acceptance criteria",
    "deferred implementation choices": "## Decisions deliberately left open",
    "SLO gate reference": "T02",
    "PostgreSQL conformance reference": "T05",
    "controlled-host SLO evidence reference": "T16",
    "pilot acceptance reference": "T18",
}
missing = [name for name, marker in required.items() if marker not in text]
if missing:
    print("T01 acceptance: missing product-contract requirements:")
    for name in missing:
        print(f"- {name}")
    sys.exit(1)

print("T01 acceptance: the v0.1 product contract defines all required boundaries and acceptance gates.")
PY
