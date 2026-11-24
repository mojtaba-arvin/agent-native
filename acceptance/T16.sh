#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

python3 - <<'PY'
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import tarfile
import tempfile
import urllib.request
from pathlib import Path, PurePosixPath

def fail(message: str) -> None:
    raise SystemExit("T16 evidence restore: " + message)

event_path = os.getenv("GITHUB_EVENT_PATH")
expected_sha = os.getenv("T16_EXPECTED_SOURCE_SHA", "")
if event_path:
    event = json.loads(Path(event_path).read_text(encoding="utf-8"))
    pull = event.get("pull_request")
    head = pull.get("head") if isinstance(pull, dict) else None
    if isinstance(head, dict):
        expected_sha = head.get("sha", expected_sha)
if not isinstance(expected_sha, str) or not re.fullmatch(r"[0-9a-f]{40}", expected_sha):
    fail("PR head SHA is unavailable; refusing unbound evidence")

repository = os.getenv("GITHUB_REPOSITORY", "mojtaba-arvin/agent-native")
headers = {
    "Accept": "application/vnd.github+json",
    "User-Agent": "agent-native-t16-acceptance",
    "X-GitHub-Api-Version": "2022-11-28",
}
asset_url = None
matches = []
for page in range(1, 11):
    url = f"https://api.github.com/repos/{repository}/releases?per_page=100&page={page}"
    request = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(request, timeout=30) as response:
        releases = json.loads(response.read())
    if not releases:
        break
    for release in releases:
        if release.get("draft") or release.get("prerelease"):
            continue
        if not str(release.get("tag_name", "")).startswith("t16-run-"):
            continue
        if release.get("target_commitish") != expected_sha:
            continue
        if f"Source: {expected_sha}" not in str(release.get("body", "")):
            continue
        for asset in release.get("assets", []):
            if (
                str(asset.get("name", "")).startswith("t16-evidence-")
                and str(asset.get("name", "")).endswith(".tar.gz")
                and asset.get("state") == "uploaded"
                and asset.get("browser_download_url")
            ):
                matches.append((str(release.get("published_at", "")), asset["browser_download_url"]))
    if len(releases) < 100:
        break
if not matches:
    fail(f"no uploaded T16 evidence release is bound to PR head {expected_sha}")
matches.sort(reverse=True)
asset_url = matches[0][1]

target = Path("experiments/e002/t16/evidence/restored").resolve()
if target.exists():
    shutil.rmtree(target)
target.mkdir(parents=True, exist_ok=True)

fd, archive_name = tempfile.mkstemp(prefix="t16-acceptance-", suffix=".tar.gz")
total_downloaded = 0
try:
    request = urllib.request.Request(asset_url, headers={"User-Agent": "agent-native-t16-acceptance"})
    with os.fdopen(fd, "wb") as output, urllib.request.urlopen(request, timeout=900) as response:
        while True:
            chunk = response.read(1024 * 1024)
            if not chunk:
                break
            total_downloaded += len(chunk)
            if total_downloaded > 1_500_000_000:
                fail("release asset exceeds the 1.5 GB download limit")
            output.write(chunk)

    extracted = set()
    total_size = 0
    archive_run_id = None
    root_files = {
        "prereg.json", "host.json", "protocol.json", "ledger.jsonl",
        "results.json", "report.md", "execution.log", "preflight.log",
        "execution-metadata.json", "image-lock.json", "checksums.sha256",
        "evidence-manifest.json",
    }
    with tarfile.open(archive_name, "r:gz") as archive:
        for member in archive.getmembers():
            raw = PurePosixPath(member.name)
            if raw.is_absolute() or not raw.parts or ".." in raw.parts or "\\" in member.name:
                fail("unsafe archive path")
            if len(raw.parts) < 2 or raw.parts[0] != "T16":
                fail("unexpected archive prefix")
            run_id = raw.parts[1]
            if not re.fullmatch(r"[0-9]{8}T[0-9]{6}Z-[0-9a-f]{8}", run_id):
                fail("invalid run identifier")
            if archive_run_id is None:
                archive_run_id = run_id
            elif archive_run_id != run_id:
                fail("archive contains multiple run identifiers")
            if member.isdir():
                dirs = raw.parts[2:]
                if not dirs or dirs == ("runs",) or (
                    len(dirs) == 2 and dirs[0] == "runs"
                    and dirs[1] in {"go-net-http", "rust-tokio-hyper"}
                ):
                    continue
                fail("unexpected archive directory")
            if not member.isfile() or member.issym() or member.islnk() or len(raw.parts) < 3:
                fail("unsupported archive member")
            relative = PurePosixPath(*raw.parts[2:])
            if relative.is_absolute() or ".." in relative.parts:
                fail("unsafe evidence member path")
            allowed_root = len(relative.parts) == 1 and relative.parts[0] in root_files
            allowed_run = (
                len(relative.parts) == 3 and relative.parts[0] == "runs"
                and relative.parts[1] in {"go-net-http", "rust-tokio-hyper"}
                and re.fullmatch(r"rep-[0-9]{2}\.(json|jsonl)", relative.parts[2])
            )
            if not (allowed_root or allowed_run):
                fail("unexpected evidence member: " + relative.as_posix())
            if member.size < 0 or member.size > 1_000_000_000:
                fail("archive member exceeds the 1 GB limit")
            total_size += member.size
            if total_size > 1_500_000_000:
                fail("archive exceeds the 1.5 GB expanded-size limit")
            relative_name = relative.as_posix()
            if relative_name in extracted:
                fail("duplicate archive member")
            destination = (target / Path(*relative.parts)).resolve()
            if not destination.is_relative_to(target):
                fail("archive path escapes evidence destination")
            destination.parent.mkdir(parents=True, exist_ok=True)
            source = archive.extractfile(member)
            if source is None:
                fail("archive member has no file data")
            with source, destination.open("wb") as output:
                shutil.copyfileobj(source, output, length=1024 * 1024)
            extracted.add(relative_name)
finally:
    Path(archive_name).unlink(missing_ok=True)

manifest_path = target / "evidence-manifest.json"
if not manifest_path.is_file() or archive_run_id is None:
    fail("missing evidence manifest or run identifier")
manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
if (
    manifest.get("schema_version") != 1
    or manifest.get("task") != "T16"
    or manifest.get("run_id") != archive_run_id
    or manifest.get("source_sha") != expected_sha
):
    fail("manifest is not bound to this exact PR head")
files = manifest.get("files")
required = {
    "prereg.json", "host.json", "protocol.json", "ledger.jsonl",
    "results.json", "report.md", "execution.log", "preflight.log",
    "execution-metadata.json", "image-lock.json", "checksums.sha256",
}
if not isinstance(files, dict) or not required.issubset(files):
    fail("manifest is incomplete")
if extracted - {"evidence-manifest.json"} != set(files):
    fail("archive file set differs from its manifest")
for relative_name, expected_digest in files.items():
    if not re.fullmatch(r"[0-9a-f]{64}", str(expected_digest)):
        fail("invalid file digest in manifest")
    path = (target / Path(*PurePosixPath(relative_name).parts)).resolve()
    if not path.is_relative_to(target) or not path.is_file():
        fail("missing or unsafe manifest file")
    if hashlib.sha256(path.read_bytes()).hexdigest() != expected_digest:
        fail("SHA-256 mismatch: " + relative_name)

prereg = json.loads((target / "prereg.json").read_text(encoding="utf-8"))
results = json.loads((target / "results.json").read_text(encoding="utf-8"))
protocol = json.loads((target / "protocol.json").read_text(encoding="utf-8"))
image_lock = json.loads((target / "image-lock.json").read_text(encoding="utf-8"))
metadata = json.loads((target / "execution-metadata.json").read_text(encoding="utf-8"))
canonical = {key: value for key, value in prereg.items() if key != "sha256"}
canonical_bytes = json.dumps(canonical, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
prereg_hash = hashlib.sha256(canonical_bytes).hexdigest()
if prereg.get("source_sha") != expected_sha or prereg.get("sha256") != prereg_hash:
    fail("preregistration is not bound to the PR head")
if manifest.get("prereg_hash") != prereg_hash or results.get("prereg_hash") != prereg_hash:
    fail("results or manifest do not bind the preregistration")
if results.get("source_sha") != expected_sha or protocol.get("source_sha") != expected_sha:
    fail("results or protocol source SHA mismatch")
image_ref = results.get("image_ref")
if not isinstance(image_ref, str) or not re.fullmatch(
    r"ghcr\.io/mojtaba-arvin/agent-native-t16@sha256:[0-9a-f]{64}", image_ref
):
    fail("results do not identify a digest-pinned image")
if (
    manifest.get("image_ref") != image_ref
    or image_lock.get("source_sha") != expected_sha
    or image_lock.get("image_ref") != image_ref
    or metadata.get("source_sha") != expected_sha
    or metadata.get("image_ref") != image_ref
):
    fail("image/source provenance does not match the PR head")
if not image_lock.get("build_run_id") or not image_lock.get("build_run_url"):
    fail("image build provenance is missing")
print(f"Restored and verified T16 evidence run {archive_run_id} for exact PR head {expected_sha}.")
PY

python3 - <<'PY'
from __future__ import annotations

import json
import re
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
