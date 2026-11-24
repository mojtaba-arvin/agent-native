#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

python3 experiments/e002/t16/restore_evidence.py --target experiments/e002/t16/evidence/restored

python3 - <<'PY'
from __future__ import annotations

import json
import sys
from pathlib import Path

root = Path("experiments/e002/t16/evidence/restored")
required = {
    "pre-registration": root / "prereg.json",
    "controlled-host manifest": root / "host.json",
    "workload protocol": root / "protocol.json",
    "run ledger": root / "ledger.jsonl",
    "machine-readable result": root / "results.json",
    "human-readable report": root / "report.md",
    "image lock": root / "image-lock.json",
    "execution metadata": root / "execution-metadata.json",
    "source-bound evidence manifest": root / "evidence-manifest.json",
}
missing = [label for label, path in required.items() if not path.is_file()]
if missing:
    print("T16 acceptance: no decision-grade controlled-host SLO evidence:")
    for label in missing:
        print(f"- missing {label}: {required[label]}")
    sys.exit(1)

def load_json(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise SystemExit(f"T16 acceptance: invalid JSON in {path}: {error}")
    if not isinstance(value, dict):
        raise SystemExit(f"T16 acceptance: {path} must contain a JSON object")
    return value

prereg = load_json(required["pre-registration"])
host = load_json(required["controlled-host manifest"])
protocol = load_json(required["workload protocol"])
results = load_json(required["machine-readable result"])
report = required["human-readable report"].read_text(encoding="utf-8")
image_lock = load_json(required["image lock"])
execution_metadata = load_json(required["execution metadata"])
manifest = load_json(required["source-bound evidence manifest"])

# The preregistration must be committed before the run and bind every result
# to one immutable source revision and a reproducible decision rule.
prereg_checks = {
    "task identity": prereg.get("task") == "T16",
    "source revision": isinstance(prereg.get("source_sha"), str) and len(prereg["source_sha"]) == 40,
    "pre-run timestamp": isinstance(prereg.get("preregistered_at"), str) and bool(prereg["preregistered_at"]),
    "command": isinstance(prereg.get("command"), list) and bool(prereg["command"]),
    "ten repetitions": prereg.get("repetitions_per_candidate") == 10,
    "five thousand measured requests": prereg.get("requests_per_repetition") == 5000,
    "concurrency 32": prereg.get("concurrency") == 32,
    "250 warm-up requests": prereg.get("warmup_requests") == 250,
    "100 requests/second": prereg.get("target_completed_rps") == 100,
    "registered thresholds": isinstance(prereg.get("thresholds"), dict),
    "explicit decision rule": isinstance(prereg.get("decision_rule"), str) and bool(prereg["decision_rule"]),
}
failed = [name for name, ok in prereg_checks.items() if not ok]
if failed:
    sys.exit("T16 acceptance: incomplete pre-registration: " + ", ".join(failed))

source_sha = prereg["source_sha"]
image_ref = results.get("image_ref")
if not isinstance(image_ref, str) or not re.fullmatch(
    r"ghcr\\.io/mojtaba-arvin/agent-native-t16@sha256:[0-9a-f]{64}", image_ref
):
    sys.exit("T16 acceptance: results do not identify a digest-pinned T16 image")
if image_lock.get("source_sha") != source_sha or image_lock.get("image_ref") != image_ref:
    sys.exit("T16 acceptance: immutable image lock is not bound to the preregistered source and result")
if not image_lock.get("build_run_url") or not image_lock.get("build_run_id"):
    sys.exit("T16 acceptance: image lock omits the successful image build provenance reference")
if execution_metadata.get("source_sha") != source_sha or execution_metadata.get("image_ref") != image_ref:
    sys.exit("T16 acceptance: execution metadata is not bound to the exact source and image")
if manifest.get("source_sha") != source_sha or manifest.get("image_ref") != image_ref:
    sys.exit("T16 acceptance: evidence manifest is not bound to the exact source and image")
if manifest.get("prereg_hash") != prereg.get("sha256"):
    sys.exit("T16 acceptance: evidence manifest is not bound to the preregistration hash")

thresholds = prereg["thresholds"]
expected_thresholds = {
    "p99_ms": 100,
    "cpu_seconds_per_5000": 25,
    "memory_peak_bytes": 1073741824,
    "oom_events": 0,
    "security_or_integrity_violations": 0,
}
for name, expected in expected_thresholds.items():
    if thresholds.get(name) != expected:
        sys.exit(f"T16 acceptance: preregistered threshold {name} must be {expected}")
if thresholds.get("completed_requests_per_second_min") != 100:
    sys.exit("T16 acceptance: preregistered completed-throughput floor must be 100 req/s")

# A cgroup limit is necessary but not sufficient: T02 explicitly excludes
# shared GitHub-hosted runner data from controlled-host capacity claims.
host_checks = {
    "Linux host": host.get("system") == "Linux",
    "documented kernel": isinstance(host.get("kernel_release"), str) and bool(host["kernel_release"]),
    "documented CPU model": isinstance(host.get("cpu_model"), str) and bool(host["cpu_model"]),
    "documented architecture": isinstance(host.get("machine"), str) and bool(host["machine"]),
    "one-vCPU candidate allocation": host.get("candidate_vcpus") == 1,
    "one-GiB candidate memory limit": host.get("candidate_memory_max_bytes") == 1073741824,
    "cgroup v2 accounting": host.get("cgroup_version") == 2,
    "dedicated host attestation": host.get("physical_host_isolation") == "dedicated",
    "not a shared GitHub runner": host.get("github_actions_runner") is False,
    "separate PostgreSQL dependency": host.get("postgres_separate_from_candidate_cgroup") is True,
}
failed = [name for name, ok in host_checks.items() if not ok]
if failed:
    sys.exit("T16 acceptance: host is not decision-grade: " + ", ".join(failed))

protocol_checks = {
    "open-loop arrivals": protocol.get("arrival_model") == "open_loop",
    "exact product request mix": protocol.get("request_mix") == {
        "authorized_read": 60,
        "validate_plan": 20,
        "job_admission": 10,
        "expected_denial": 10,
    },
    "10 randomized repetitions": protocol.get("repetitions_per_candidate") == 10 and protocol.get("candidate_order") == "randomized",
    "5,000 requests per repetition": protocol.get("requests_per_repetition") == 5000,
    "concurrency 32": protocol.get("concurrency") == 32,
    "250 warm-up requests": protocol.get("warmup_requests") == 250,
    "100 completed requests/second": protocol.get("target_completed_rps") == 100,
    "one-vCPU cgroup": protocol.get("cpu_max") == "100000 100000",
    "one-GiB memory ceiling": protocol.get("memory_max_bytes") == 1073741824,
    "durable PostgreSQL storage": protocol.get("storage_engine") == "PostgreSQL" and bool(protocol.get("postgres_version")),
    "pinned source revision": protocol.get("source_sha") == prereg["source_sha"],
}
failed = [name for name, ok in protocol_checks.items() if not ok]
if failed:
    sys.exit("T16 acceptance: workload protocol mismatch: " + ", ".join(failed))

try:
    ledger = [
        json.loads(line)
        for line in required["run ledger"].read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
except (OSError, UnicodeError, json.JSONDecodeError) as error:
    sys.exit(f"T16 acceptance: invalid run ledger: {error}")
if not ledger:
    sys.exit("T16 acceptance: run ledger is empty")

# Cancelled runs remain in the ledger but are excluded from the ten-run
# denominator. Every non-cancelled run, including failures, must be retained.
active = [item for item in ledger if item.get("status") != "cancelled"]
candidates = ("rust-tokio-hyper", "go-net-http")
for candidate in candidates:
    runs = [item for item in active if item.get("candidate") == candidate]
    if len(runs) != 10:
        sys.exit(f"T16 acceptance: {candidate} has {len(runs)} non-cancelled runs; expected 10")
    for run in runs:
        for key in ("run_id", "sha", "prereg_hash", "command", "started_at", "finished_at", "raw_trace"):
            if not run.get(key):
                sys.exit(f"T16 acceptance: {candidate} run is missing {key}")
        if run.get("sha") != prereg["source_sha"]:
            sys.exit(f"T16 acceptance: {candidate} run SHA differs from preregistration")
        raw = root / run["raw_trace"]
        if not raw.is_file() or raw.stat().st_size == 0:
            sys.exit(f"T16 acceptance: missing raw request trace for {run['run_id']}: {raw}")
        metrics = run.get("metrics")
        if not isinstance(metrics, dict):
            sys.exit(f"T16 acceptance: {candidate} run {run['run_id']} has no metrics")
        if metrics.get("completed_requests") != 5000:
            sys.exit(f"T16 acceptance: {candidate} run {run['run_id']} did not complete 5,000 requests")
        if metrics.get("completed_requests_per_second") is None or metrics.get("p99_ms") is None:
            sys.exit(f"T16 acceptance: {candidate} run {run['run_id']} lacks throughput or p99")
        if metrics.get("cpu_seconds") is None or metrics.get("memory_peak_bytes") is None:
            sys.exit(f"T16 acceptance: {candidate} run {run['run_id']} lacks cgroup CPU or memory evidence")
        for counter in ("oom_events", "security_or_integrity_violations"):
            if metrics.get(counter) is None:
                sys.exit(f"T16 acceptance: {candidate} run {run['run_id']} lacks {counter}")
        if run.get("functional_conformance") is not True:
            sys.exit(f"T16 acceptance: {candidate} run {run['run_id']} failed functional conformance")

if results.get("source_sha") != prereg["source_sha"]:
    sys.exit("T16 acceptance: results are not bound to the preregistered source SHA")
if results.get("prereg_hash") != prereg.get("sha256"):
    sys.exit("T16 acceptance: results are not bound to the preregistration hash")

# Recompute every hard gate from raw run-level summaries. A failed candidate
# is a valid measured outcome; absent evidence is never silently scored as 0.
for candidate in candidates:
    runs = [item for item in active if item.get("candidate") == candidate]
    for run in runs:
        metrics = run["metrics"]
        checks = {
            "throughput": metrics["completed_requests_per_second"] >= 100,
            "p99": metrics["p99_ms"] <= 100,
            "CPU": metrics["cpu_seconds"] <= 25,
            "memory": metrics["memory_peak_bytes"] <= 1073741824,
            "OOM": metrics["oom_events"] == 0,
            "security/integrity": metrics["security_or_integrity_violations"] == 0,
        }
        expected = all(checks.values())
        if run.get("slo_pass") is not expected:
            sys.exit(f"T16 acceptance: {candidate} run {run['run_id']} has an incorrect SLO pass/fail label")

for run in active:
    if run.get("run_id") not in report:
        sys.exit(f"T16 acceptance: report omits run_id {run.get('run_id')!r}")
if "not measured" in report.lower() and any(item.get("slo_pass") for item in active):
    sys.exit("T16 acceptance: report contradicts measured passing runs")

print("T16 acceptance: preregistration, dedicated-host attestation, product request mix, PostgreSQL protocol, raw traces, 10-run cohorts, and T02 hard-gate decisions are present.")
PY
