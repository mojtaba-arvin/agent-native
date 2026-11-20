#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

python3 - <<'PY'
from pathlib import Path
import sys

required = {
    "Rust library surface": Path("experiments/e002/rust/src/lib.rs"),
    "Rust HTTP server entry point": Path("experiments/e002/rust/src/main.rs"),
    "Rust crate manifest": Path("experiments/e002/rust/Cargo.toml"),
    "committed Rust dependency lockfile": Path("experiments/e002/rust/Cargo.lock"),
    "shared black-box HTTP conformance runner": Path("experiments/e002/conformance.py"),
    "Layer 1 build and runtime wiring": Path(".github/workflows/ci.yml"),
    "T07 Rust evidence record": Path("experiments/e002/rust/T07-evidence.md"),
}
missing = [label for label, path in required.items() if not path.is_file()]
if missing:
    print("T07 acceptance: missing Rust spike outputs:")
    for label in missing:
        print(f"- {label}")
    sys.exit(1)

library = required["Rust library surface"].read_text(encoding="utf-8")
manifest = required["Rust crate manifest"].read_text(encoding="utf-8")
workflow = required["Layer 1 build and runtime wiring"].read_text(encoding="utf-8")
evidence = required["T07 Rust evidence record"].read_text(encoding="utf-8")
runner = required["shared black-box HTTP conformance runner"].read_text(encoding="utf-8")

library_markers = (
    "pub fn parse_work_ms(",
    "pub async fn execute_work(",
    "enum WorkFailure",
    "fn parser_accepts_canonical_decimal_values",
    "fn parser_rejects_noncanonical_query_values",
    "async fn work_completes_before_deadline",
    "async fn work_times_out_at_registered_deadline",
    "fn work_admission_is_bounded_and_releases_capacity",
    "async fn stream_preserves_ordered_chunks",
)
missing_markers = [marker for marker in library_markers if marker not in library]

workflow_markers = (
    "E-002 Rust runtime",
    "cargo test --locked",
    "cargo build --locked --release",
    'python ../conformance.py --command ./target/release/agent-native-e002-rust --cwd .',
)
missing_workflow = [marker for marker in workflow_markers if marker not in workflow]

evidence_markers = (
    "## Verification matrix",
    "cargo test --locked",
    "cargo build --locked --release",
    "experiments/e002/conformance.py",
    "failure",
)
missing_evidence = [marker for marker in evidence_markers if marker not in evidence]

if "edition = \"2021\"" not in manifest:
    missing_markers.append("Rust 2021 crate edition")
if "def verify()" not in runner or '"/work?ms=900"' not in runner:
    missing_evidence.append("shared runner exercises the deadline failure response")

for label, missing_items in (
    ("Rust library correctness/failure tests", missing_markers),
    ("Layer 1 build and runtime validation", missing_workflow),
    ("evidence record and failure contract", missing_evidence),
):
    if missing_items:
        print(f"T07 acceptance: incomplete {label}:")
        for item in missing_items:
            print(f"- {item}")
        sys.exit(1)

print("T07 acceptance: Rust unit tests, locked build, shared HTTP runtime checks, and evidence record are present.")
PY
