#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

python3 - <<'PY'
from pathlib import Path
import sys

paths = {
    "T02 preregistered rule": Path("docs/T02_SLO_AND_RUNTIME.md"),
    "T09 evidence": Path("experiments/e002/T09-evidence.md"),
    "runtime decision matrix": Path("experiments/e002/decision-matrix.md"),
    "T10 decision record": Path("experiments/e002/results/2026-11-20-t09-runtime-decision.md"),
}
missing_files = [name for name, path in paths.items() if not path.is_file()]
if missing_files:
    print("T10 acceptance: missing required decision inputs:")
    for name in missing_files:
        print(f"- {name}")
    sys.exit(1)

rule = paths["T02 preregistered rule"].read_text(encoding="utf-8")
evidence = paths["T09 evidence"].read_text(encoding="utf-8")
matrix = paths["runtime decision matrix"].read_text(encoding="utf-8")
record = paths["T10 decision record"].read_text(encoding="utf-8")

rule_markers = (
    "authenticated Agent/tool-execution control-plane workload",
    "100 completed requests/second",
    "1 GiB",
    "open-loop arrival",
    "10 randomized repetitions per candidate",
    "zero authorization",
    "Rust/Tokio + Hyper",
    "Go/net/http",
    "Do not calculate a final score",
    "no runtime selected",
)
missing_rule = [marker for marker in rule_markers if marker not in rule]

evidence_markers = (
    "GET /work?ms=0",
    "closed-loop concurrency 32",
    "2 GiB memory",
    "ephemeral GitHub-hosted VM",
    "not dedicated bare-metal",
    "not a product SLO or decision-grade runtime selection",
)
missing_evidence = [marker for marker in evidence_markers if marker not in evidence]

matrix_link = "2026-11-20-t09-runtime-decision.md"
record_markers = (
    "# T10 — T09 runtime decision",
    "Decision: **NO SELECTION**",
    "Task: T10 (#114)",
    "acfd8d0f775d46b4f0dea39ade423e445efc8fd5",
    "44741277036",
    "14630464028",
    "decision_grade: false",
    "GET /work?ms=0",
    "closed-loop",
    "2 GiB",
    "shared GitHub-hosted",
    "100 completed requests/second",
    "open-loop",
    "authenticated",
    "durable audit",
    "PostgreSQL",
    "outbox",
    "idempotency",
    "fault-injection",
    "No weighted score is calculated",
    "not measured",
    "Go/net-http",
    "Rust/Tokio + Hyper",
    "WASI P2 / Wasmtime",
    "Elixir/BEAM",
    "10/10",
    "not rejected as architectures",
)
missing_record = [marker for marker in record_markers if marker not in record]
if matrix_link not in matrix:
    missing_record.append("decision matrix links to the dated T09 decision record")

measurement_rows = (
    "| Go/net-http | 10,514.85 ± 367.04 | 4.575 ± 0.330 | 0.2935 ± 0.0095 | 7.24 | 10/10 |",
    "| Rust/Tokio + Hyper | 10,371.60 ± 376.13 | 4.609 ± 0.197 | 0.2628 ± 0.0054 | 4.15 | 10/10 |",
    "| WASI P2 / Wasmtime | 6,428.70 ± 115.64 | 7.672 ± 0.260 | 0.7744 ± 0.0122 | 21.50 | 10/10 |",
    "| Elixir/BEAM | 9,795.92 ± 429.49 | 5.014 ± 0.237 | 0.4874 ± 0.0165 | 46.83 | 10/10 |",
)
missing_rows = [row for row in measurement_rows if row not in record]

if missing_rule or missing_evidence or missing_record or missing_rows:
    for label, items in (
        ("T02 rule preservation", missing_rule),
        ("T09 diagnostic boundary", missing_evidence),
        ("T10 decision and traceability", missing_record),
        ("exact ten-run measurements", missing_rows),
    ):
        if items:
            print(f"T10 acceptance: incomplete {label}:")
            for item in items:
                print(f"- {item}")
    sys.exit(1)

if "Decision: **NO SELECTION**" not in record or "No weighted score is calculated" not in record:
    print("T10 acceptance: incomplete evidence must not produce a runtime winner or weighted score.")
    sys.exit(1)

print("T10 acceptance: T02 eligibility gates, T09 measurements and limitations, explicit no-selection outcome, alternatives, and artifact traceability are recorded.")
PY
