#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

python3 - <<'PY'
from pathlib import Path
import sys

required = {
    "controlled cgroup matrix orchestrator": Path("experiments/e002/controlled_host_matrix.py"),
    "independent Go load generator": Path("experiments/e002/loadgen/main.go"),
    "Go load-generator tests": Path("experiments/e002/loadgen/main_test.go"),
    "controlled-host container definition": Path("experiments/e002/controlled-host/Dockerfile"),
    "candidate container entry point": Path("experiments/e002/controlled-host/entrypoint.sh"),
    "controlled-host protocol tests": Path("experiments/e002/test_controlled_host_matrix.py"),
    "T09 evidence record": Path("experiments/e002/T09-evidence.md"),
    "CI measurement wiring": Path(".github/workflows/ci.yml"),
}
missing = [label for label, path in required.items() if not path.is_file()]
if missing:
    print("T09 acceptance: missing controlled-host measurement outputs:")
    for label in missing:
        print(f"- {label}")
    sys.exit(1)

matrix = required["controlled cgroup matrix orchestrator"].read_text(encoding="utf-8")
loadgen = required["independent Go load generator"].read_text(encoding="utf-8")
loadtests = required["Go load-generator tests"].read_text(encoding="utf-8")
dockerfile = required["controlled-host container definition"].read_text(encoding="utf-8")
entrypoint = required["candidate container entry point"].read_text(encoding="utf-8")
tests = required["controlled-host protocol tests"].read_text(encoding="utf-8")
evidence = required["T09 evidence record"].read_text(encoding="utf-8")
workflow = required["CI measurement wiring"].read_text(encoding="utf-8")

matrix_markers = (
    "cpu.max",
    "cpuset.cpus.effective",
    "cpu.stat",
    "memory.max",
    "memory.peak",
    "--cpus=1",
    "--memory=2g",
    "random.Random",
    "repetitions",
    "5000",
    "concurrency",
    "warmup",
    "docker",
    "taskset",
    "loadgen",
)
missing_matrix = [marker for marker in matrix_markers if marker not in matrix]

loadgen_markers = (
    "net/http",
    "encoding/json",
    "jsonl",
    "completed:0",
    "latency_ms",
    "throughput_requests_per_second",
    "functional_success",
    "DisableKeepAlives",
)
missing_loadgen = [marker for marker in loadgen_markers if marker not in loadgen]

test_markers = (
    "TestParseCPUStat",
    "TestOneVcpuQuota",
    "TestAllowedCPUList",
    "TestDistribution",\n    "TestWriteJSON",
)
missing_tests = [marker for marker in test_markers if marker not in tests]

workflow_markers = (
    "E-002 controlled one-vCPU ten-repetition matrix",
    "go build -o",
    "controlled_host_matrix.py",
    "upload-artifact@v4",
    "retention-days: 90",
)
missing_workflow = [marker for marker in workflow_markers if marker not in workflow]

evidence_markers = (
    "# T09",
    "## Registered protocol",
    "10 repetitions",
    "5,000",
    "32",
    "250",
    "Go load generator",
    "cpu.max",
    "usage_usec",
    "## Evidence boundary",
    "not dedicated bare-metal",
    "no runtime is selected",
)
missing_evidence = [marker for marker in evidence_markers if marker not in evidence]

if "ENTRYPOINT" not in dockerfile or "exec" not in entrypoint:
    missing_matrix.append("container has an explicit candidate entry point")
if "func Test" not in loadtests:
    missing_loadgen.append("Go load generator has executable unit tests")
if "T09" not in workflow or "outputs:" not in workflow:
    missing_workflow.append("workflow exposes the T09 impact output")

for label, items in (
    ("controlled one-vCPU cgroup isolation and randomized protocol", missing_matrix),
    ("non-Python load generation and response validation", missing_loadgen),
    ("protocol parsing and configuration tests", missing_tests),
    ("automatic PR measurement and raw-artifact retention", missing_workflow),
    ("registered protocol and explicit evidence limitations", missing_evidence),
):
    if items:
        print(f"T09 acceptance: incomplete {label}:")
        for item in items:
            print(f"- {item}")
        sys.exit(1)

print("T09 acceptance: Go load generation, isolated cgroup accounting, ten randomized runs per candidate, CI execution, and evidence boundaries are present.")
PY
