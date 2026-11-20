#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

python3 - <<'PY'
from pathlib import Path
import sys

required = {
    "Go HTTP runtime implementation": Path("experiments/e002/go/main.go"),
    "Go behavior test suite": Path("experiments/e002/go/main_test.go"),
    "Go module manifest": Path("experiments/e002/go/go.mod"),
    "shared black-box HTTP conformance runner": Path("experiments/e002/conformance.py"),
    "Layer 1 Go build and runtime wiring": Path(".github/workflows/ci.yml"),
    "T08 Go evidence record": Path("experiments/e002/go/T08-evidence.md"),
}
missing = [label for label, path in required.items() if not path.is_file()]
if missing:
    print("T08 acceptance: missing Go spike outputs:")
    for label in missing:
        print(f"- {label}")
    sys.exit(1)

implementation = required["Go HTTP runtime implementation"].read_text(encoding="utf-8")
tests = required["Go behavior test suite"].read_text(encoding="utf-8")
manifest = required["Go module manifest"].read_text(encoding="utf-8")
workflow = required["Layer 1 Go build and runtime wiring"].read_text(encoding="utf-8")
evidence = required["T08 Go evidence record"].read_text(encoding="utf-8")
runner = required["shared black-box HTTP conformance runner"].read_text(encoding="utf-8")

implementation_markers = (
    "func parseWorkMS(",
    "func newHandler(",
    "func (app *application) serveWork(",
    "maxConcurrent = 64",
    "workDeadline  = 750 * time.Millisecond",
    "maxWorkMS",
)
missing_implementation = [marker for marker in implementation_markers if marker not in implementation]

test_markers = (
    "func TestParseWorkMS(",
    "func TestWorkCompletesBeforeDeadline(",
    "func TestWorkTimesOutAtRegisteredDeadline(",
    "func TestWorkAdmissionIsBoundedAndReleasesCapacity(",
    "func TestWorkTimeoutReleasesAdmissionCapacity(",
    "func TestWorkFailureResponsesMatchHTTPContract(",
    "func TestStreamPreservesOrderedChunks(",
)
missing_tests = [marker for marker in test_markers if marker not in tests]

workflow_markers = (
    "E-002 Go runtime",
    "go test ./...",
    'go build -o "$RUNNER_TEMP/e002-go" .',
    'python ../conformance.py --command "$RUNNER_TEMP/e002-go" --cwd .',
)
missing_workflow = [marker for marker in workflow_markers if marker not in workflow]

evidence_markers = (
    "# T08",
    "## Verification matrix",
    "go test ./...",
    'go build -o "$RUNNER_TEMP/e002-go" .',
    "experiments/e002/conformance.py",
    "750 ms",
    "failure",
)
missing_evidence = [marker for marker in evidence_markers if marker not in evidence]

if "go 1.23" not in manifest:
    missing_implementation.append("Go 1.23 module declaration")
if "def verify()" not in runner or '"/work?ms=900"' not in runner or '"/stream"' not in runner:
    missing_evidence.append("shared runner covers deadline and ordered streaming failure/success behavior")

for label, items in (
    ("Go workload implementation", missing_implementation),
    ("Go behavior and failure tests", missing_tests),
    ("Layer 1 build and runtime validation", missing_workflow),
    ("evidence record and shared contract", missing_evidence),
):
    if items:
        print(f"T08 acceptance: incomplete {label}:")
        for item in items:
            print(f"- {item}")
        sys.exit(1)

print("T08 acceptance: Go workload tests, Layer 1 locked-toolchain build, shared HTTP checks, and evidence record are present.")
PY
