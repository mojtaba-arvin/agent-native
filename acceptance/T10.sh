#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

python3 - <<'PY'
import json
from pathlib import Path
import sys

root = Path(".")
decision_path = root / "DECISIONS.json"
record_path = root / "docs/T10_RUNTIME_DECISION.md"
rule_path = root / "docs/T02_SLO_AND_RUNTIME.md"
evidence_path = root / "experiments/e002/T09-evidence.md"

for label, path in (
    ("canonical decision registry", decision_path),
    ("T10 decision report", record_path),
    ("unchanged T02 rule", rule_path),
    ("T09 evidence record", evidence_path),
):
    if not path.is_file():
        print(f"T10 acceptance: missing {label}: {path}")
        sys.exit(1)

registry = json.loads(decision_path.read_text(encoding="utf-8"))
decisions = registry.get("decisions")
if not isinstance(decisions, list):
    print("T10 acceptance: DECISIONS.json has no decisions array.")
    sys.exit(1)

by_id = {item.get("id"): item for item in decisions if isinstance(item, dict)}
rule = by_id.get("D-0015")
record = by_id.get("D-0016")
if not rule:
    print("T10 acceptance: missing preregistered T02 decision D-0015.")
    sys.exit(1)
if not record:
    print("T10 acceptance: missing T10 runtime decision D-0016.")
    sys.exit(1)

if rule.get("runtime_candidates") != ["Rust/Tokio + Hyper", "Go/net/http"]:
    print("T10 acceptance: D-0015 formal Rust/Go candidate boundary was changed.")
    sys.exit(1)
if record.get("topic") != "runtime_selection" or record.get("status") != "decided":
    print("T10 acceptance: D-0016 must be a decided runtime_selection record.")
    sys.exit(1)

selection = record.get("selection")
if not isinstance(selection, dict) or selection.get("outcome") != "no_selection" or selection.get("runtime") is not None:
    print("T10 acceptance: D-0016 must explicitly record no runtime selected.")
    sys.exit(1)

if record.get("task") != "T10 (#114)":
    print("T10 acceptance: D-0016 must identify Task T10 (#114).")
    sys.exit(1)

source = record.get("source_evidence", {})
if (
    source.get("source_sha") != "acfd8d0f775d46b4f0dea39ade423e445efc8fd5"
    or source.get("workflow_run") != 44741277036
    or source.get("artifact_id") != 14630464028
    or source.get("decision_grade") is not False
):
    print("T10 acceptance: D-0016 source evidence is not pinned to the retained T09 artifact.")
    sys.exit(1)

candidates = record.get("observed_tradeoffs", {})
expected = {
    "Go/net-http": (10514.85, 367.04, 4.575, 0.330, 0.2935, 0.0095, 7.24),
    "Rust/Tokio + Hyper": (10371.60, 376.13, 4.609, 0.197, 0.2628, 0.0054, 4.15),
    "WASI P2 / Wasmtime": (6428.70, 115.64, 7.672, 0.260, 0.7744, 0.0122, 21.50),
    "Elixir/BEAM": (9795.92, 429.49, 5.014, 0.237, 0.4874, 0.0165, 46.83),
}
for name, values in expected.items():
    item = candidates.get(name)
    if not isinstance(item, dict):
        print(f"T10 acceptance: missing observed trade-offs for {name}.")
        sys.exit(1)
    actual = (
        item.get("throughput_mean_requests_per_second"),
        item.get("throughput_sample_sd_requests_per_second"),
        item.get("p99_mean_ms"),
        item.get("p99_sample_sd_ms"),
        item.get("cpu_mean_seconds_per_5000"),
        item.get("cpu_sample_sd_seconds_per_5000"),
        item.get("peak_cgroup_memory_median_mib"),
    )
    if actual != values or item.get("functional_repetitions_passed") != 10:
        print(f"T10 acceptance: incomplete or mismatched measured trade-offs for {name}.")
        sys.exit(1)

rejected = record.get("rejected_alternatives")
if not isinstance(rejected, list) or len(rejected) < 3:
    print("T10 acceptance: record at least three rejected selection shortcuts.")
    sys.exit(1)
if any(item.get("classification") != "rejected" for item in rejected if isinstance(item, dict)):
    print("T10 acceptance: rejected alternatives must be explicitly classified.")
    sys.exit(1)

text = record_path.read_text(encoding="utf-8")
required_markers = (
    "# T10 — T09 runtime decision",
    "Task: T10 (#114)",
    "Decision: **NO SELECTION**",
    "authenticated Agent/tool-execution control-plane workload",
    "100 completed requests/second",
    "one vCPU and one GiB",
    "open-loop",
    "durable audit",
    "PostgreSQL",
    "outbox",
    "idempotency",
    "fault-injection",
    "closed-loop",
    "2 GiB",
    "GET /work?ms=0",
    "shared GitHub-hosted",
    "No weighted score is calculated",
    "not measured",
    "not rejected as architectures",
    "10/10",
    "44741277036",
    "14630464028",
)
missing = [marker for marker in required_markers if marker not in text]
if missing:
    print("T10 acceptance: T10 report missing required decision/evidence content:")
    for marker in missing:
        print(f"- {marker}")
    sys.exit(1)

rule_text = rule_path.read_text(encoding="utf-8")
rule_markers = (
    "Rust/Tokio + Hyper",
    "Go/net/http",
    "100 completed requests/second",
    "1 GiB",
    "open-loop arrival",
    "10 randomized repetitions per candidate",
    "95% bootstrap confidence interval",
    "no runtime selected",
)
missing_rule = [marker for marker in rule_markers if marker not in rule_text]
if missing_rule:
    print("T10 acceptance: preregistered T02 rule is incomplete or changed:")
    for marker in missing_rule:
        print(f"- {marker}")
    sys.exit(1)

evidence_text = evidence_path.read_text(encoding="utf-8")
if "not a product SLO or decision-grade runtime selection" not in evidence_text:
    print("T10 acceptance: T09 evidence boundary is missing.")
    sys.exit(1)

print("T10 acceptance: canonical D-0016 no-selection decision, unchanged D-0015 rule, measured trade-offs, rejected alternatives, and T09 artifact provenance are recorded.")
PY
