#!/usr/bin/env python3
"""Execute the preregistered T16 matrix on an attested dedicated Linux host."""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import random
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path
from typing import Any

CANDIDATES = ("rust-tokio-hyper", "go-net-http")
REPETITIONS = 10
REQUESTS = 5000
CONCURRENCY = 32
WARMUP = 250
TARGET_RPS = 100
CPU_MAX = "100000 100000"
MEMORY_MAX = 1073741824
SEED = 20261120


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def run_command(command: list[str], *, timeout: int = 300, input_text: str | None = None, allow_failure: bool = False) -> str:
    result = subprocess.run(
        command, input=input_text, check=False, capture_output=True, text=True, timeout=timeout,
    )
    if result.returncode and not allow_failure:
        raise RuntimeError(
            f"command failed ({result.returncode}): {command!r}\n"
            f"stdout: {result.stdout[-3000:]}\nstderr: {result.stderr[-3000:]}"
        )
    return result.stdout.strip()


def psql(dsn: str, sql: str) -> str:
    return run_command([
        "psql", dsn, "-X", "-A", "-t", "-v", "ON_ERROR_STOP=1", "-c", sql,
    ], timeout=30)


def cgroup_for_pid(pid: int) -> Path:
    membership = Path(f"/proc/{pid}/cgroup").read_text(encoding="ascii")
    entries = [line.split("::", 1)[1] for line in membership.splitlines() if "::" in line]
    if len(entries) != 1:
        raise RuntimeError(f"PID {pid} does not have one unified cgroup-v2 membership")
    path = Path("/sys/fs/cgroup") / entries[0].lstrip("/")
    if not path.is_dir():
        raise RuntimeError(f"cgroup path is not visible for PID {pid}: {path}")
    return path


def container_pid(name: str) -> int:
    value = run_command(["docker", "inspect", "--format", "{{.State.Pid}}", name])
    pid = int(value)
    if pid <= 0:
        raise RuntimeError(f"container {name} has invalid PID {value!r}")
    return pid


def container_cgroup(name: str) -> Path:
    return cgroup_for_pid(container_pid(name))



def physical_core_key(cpu: int) -> tuple[int, int]:
    topology = Path(f"/sys/devices/system/cpu/cpu{cpu}/topology")
    return (
        int((topology / "physical_package_id").read_text(encoding="ascii").strip()),
        int((topology / "core_id").read_text(encoding="ascii").strip()),
    )


def parse_cpu_list(value: str) -> list[int]:
    result: list[int] = []
    for part in value.strip().split(","):
        if "-" in part:
            low, high = (int(piece) for piece in part.split("-", 1))
            result.extend(range(low, high + 1))
        elif part:
            result.append(int(part))
    return sorted(set(result))


def verify_candidate_cgroup(path: Path, cpu: int) -> dict[str, Any]:
    cpu_max = (path / "cpu.max").read_text(encoding="ascii").strip()
    cpuset = (path / "cpuset.cpus.effective").read_text(encoding="ascii").strip()
    memory_max = int((path / "memory.max").read_text(encoding="ascii").strip())
    if cpu_max != CPU_MAX:
        raise RuntimeError(f"candidate CPU quota mismatch: {cpu_max!r}")
    if parse_cpu_list(cpuset) != [cpu]:
        raise RuntimeError(f"candidate cpuset mismatch: {cpuset!r}, expected [{cpu}]")
    if memory_max != MEMORY_MAX:
        raise RuntimeError(f"candidate memory limit mismatch: {memory_max}")
    return {"cpu_max": cpu_max, "cpuset_cpus_effective": cpuset, "memory_max_bytes": memory_max}


def read_cpu_usage(path: Path) -> dict[str, int]:
    values = {}
    for line in (path / "cpu.stat").read_text(encoding="ascii").splitlines():
        key, value = line.split()
        values[key] = int(value)
    return values


def read_memory_events(path: Path) -> dict[str, int]:
    values = {}
    for line in (path / "memory.events").read_text(encoding="ascii").splitlines():
        key, value = line.split()
        values[key] = int(value)
    return values



def run_loadgen_container(name: str, arguments: list[str], cpu: int, root: Path,
                          bin_dir: Path, output: Path, read_token: str, deny_token: str, timeout: int = 180) -> dict[str, Any]:
    container = name
    try:
        run_command([
            "docker", "run", "--detach", "--name", container,
            "--cpus=1", f"--cpuset-cpus={cpu}", "--memory=1g", "--network=host",
            "--env", f"T16_READ_TOKEN={read_token}", "--env", f"T16_DENY_TOKEN={deny_token}",
            "-v", f"{root}:/src:ro", "-v", f"{output}:/evidence:rw", "-v", f"{bin_dir}:/out:ro",
            "-w", "/src/experiments/e002/t16/loadgen",
            "golang:1.23.12-bookworm", "/out/t16-loadgen", *arguments,
        ], timeout=60)
        cgroup = container_cgroup(container)
        limits = verify_candidate_cgroup(cgroup, cpu)
        exit_code = run_command(["docker", "wait", container], timeout=timeout)
        logs = run_command(["docker", "logs", container], timeout=15, allow_failure=True)
        if exit_code != "0":
            raise RuntimeError(f"load generator exited {exit_code}: {logs[-3000:]}")
        return {"path": str(cgroup), "limits": limits, "logs": logs[-4000:]}
    finally:
        run_command(["docker", "rm", "--force", container], timeout=60, allow_failure=True)


def wait_ready(container: str, timeout: float = 30.0) -> float:
    started = time.monotonic()
    deadline = started + timeout
    while time.monotonic() < deadline:
        state = run_command(
            ["docker", "inspect", "--format", "{{.State.Running}}", container],
        )
        if state != "true":
            logs = run_command(["docker", "logs", container], timeout=15, allow_failure=True)
            raise RuntimeError(f"candidate exited before readiness: {logs[-3000:]}")
        try:
            with urllib.request.urlopen("http://127.0.0.1:8080/health", timeout=1.0) as response:
                if response.status == 200 and response.read() == b"ok":
                    return time.monotonic() - started
        except (OSError, TimeoutError, urllib.error.URLError):
            time.sleep(0.05)
    logs = run_command(["docker", "logs", container], timeout=15)
    raise RuntimeError(f"candidate did not become ready: {logs[-3000:]}")


def http_request(method: str, path: str, *, token: str | None, request_id: str,
                 tenant: str = "tenant-a", body: dict | None = None,
                 idempotency_key: str | None = None) -> tuple[int, dict]:
    headers = {"X-Request-ID": request_id, "X-Tenant-ID": tenant, "Accept": "application/json"}
    if token is not None:
        headers["Authorization"] = "Bearer " + token
    data = None
    if body is not None:
        data = json.dumps(body, separators=(",", ":")).encode("utf-8")
        headers["Content-Type"] = "application/json"
    if idempotency_key is not None:
        headers["Idempotency-Key"] = idempotency_key
    request = urllib.request.Request("http://127.0.0.1:8080" + path, data=data, headers=headers, method=method)
    try:
        response = urllib.request.urlopen(request, timeout=5)
    except urllib.error.HTTPError as error:
        response = error
    with response:
        payload = json.loads(response.read().decode("utf-8"))
        return response.status, payload


def verify_product_conformance(dsn: str, read_token: str, deny_token: str) -> None:
    psql(dsn, "SELECT t16_reset()")
    status, read = http_request("GET", "/v1/records/fixture-0001", token=read_token, request_id="conf-read")
    if status != 200 or read.get("data", {}).get("id") != "fixture-0001":
        raise RuntimeError("authorized tenant-scoped read conformance failed")
    status, plan = http_request(
        "POST", "/v1/operations/validate", token=read_token, request_id="conf-plan",
        body={"contract_version": "v1", "operation": "catalog.read", "resource_id": "fixture-0001"},
    )
    if status != 200 or plan.get("decision") != "allow":
        raise RuntimeError("plan-validation conformance failed")

    invalid_status, invalid = http_request(
        "POST", "/v1/operations/validate", token=read_token, request_id="conf-invalid",
        body={"contract_version": "v1", "operation": "catalog.read", "resource_id": "fixture-0001", "unexpected": True},
    )
    if invalid_status != 400 or invalid.get("error", {}).get("code") != "INVALID_CONTRACT":
        raise RuntimeError("unknown contract fields were not rejected consistently")

    body = {"contract_version": "v1", "operation": "jobs.create", "payload": {"fixture": "conformance"}}
    status, first = http_request(
        "POST", "/v1/jobs", token=read_token, request_id="conf-job-1",
        body=body, idempotency_key="conf-idempotency",
    )
    status2, replay = http_request(
        "POST", "/v1/jobs", token=read_token, request_id="conf-job-2",
        body=body, idempotency_key="conf-idempotency",
    )
    if status != 202 or status2 != 202 or first.get("job_id") != replay.get("job_id"):
        raise RuntimeError("job admission/idempotent replay conformance failed")
    changed = {"contract_version": "v1", "operation": "jobs.create", "payload": {"fixture": "different"}}
    conflict_status, conflict = http_request(
        "POST", "/v1/jobs", token=read_token, request_id="conf-job-3",
        body=changed, idempotency_key="conf-idempotency",
    )
    if conflict_status != 409 or conflict.get("error", {}).get("code") != "IDEMPOTENCY_CONFLICT":
        raise RuntimeError("idempotency payload-conflict conformance failed")
    denied_status, denied = http_request(
        "POST", "/v1/jobs", token=deny_token, request_id="conf-denied",
        body=body, idempotency_key="conf-denied-key",
    )
    if denied_status != 403 or denied.get("error", {}).get("code") != "CAPABILITY_DENIED":
        raise RuntimeError("default-deny capability conformance failed")
    tenant_status, tenant_denied = http_request(
        "GET", "/v1/records/fixture-0001", token=read_token,
        request_id="conf-cross-tenant", tenant="tenant-b",
    )
    if tenant_status != 403 or tenant_denied.get("error", {}).get("code") != "TENANT_SCOPE_MISMATCH":
        raise RuntimeError("cross-tenant isolation conformance failed")
    unauth_status, _ = http_request(
        "GET", "/v1/records/fixture-0001", token=None, request_id="conf-unauth",
    )
    if unauth_status != 401:
        raise RuntimeError("missing-credential default-deny conformance failed")
    counts = psql(dsn, """
        SELECT (SELECT count(*) FROM t16_jobs) || '|' ||
               (SELECT count(*) FROM t16_outbox) || '|' ||
               (SELECT count(*) FROM t16_idempotency_records) || '|' ||
               (SELECT count(*) FROM t16_audit) || '|' ||
               (SELECT count(*) FROM t16_integrity_violations)
    """)
    if counts != "1|1|1|8|0":
        raise RuntimeError(f"durable conformance state mismatch: {counts!r}")
    psql(dsn, "SELECT t16_reset()")


def integrity_violations(dsn: str) -> int:
    value = psql(dsn, """
        SELECT
          (SELECT count(*) FROM t16_integrity_violations) +
          (SELECT count(*) FROM t16_audit
           WHERE (principal_id = 'benchmark-limited' AND operation_id = 'jobs.create' AND decision = 'allow')
              OR (reason_code = 'TENANT_SCOPE_MISMATCH' AND decision <> 'deny'))
    """)
    return int(value)


def aggregate(records: list[dict], candidate: str) -> dict[str, Any]:
    selected = [item for item in records if item["candidate"] == candidate]
    values = [item["metrics"] for item in selected if isinstance(item.get("metrics"), dict)]
    if not values:
        return {
            "runs": 0, "attempts": len(selected), "throughput_mean_rps": None,
            "p99_mean_ms": None, "cpu_mean_seconds": None,
            "memory_peak_max_bytes": None, "slo_passed_runs": 0,
        }
    def mean(key: str) -> float:
        return sum(float(item[key]) for item in values) / len(values)
    return {
        "runs": len(values),
        "attempts": len(selected),
        "throughput_mean_rps": mean("completed_requests_per_second"),
        "p99_mean_ms": mean("p99_ms"),
        "cpu_mean_seconds": mean("cpu_seconds"),
        "memory_peak_max_bytes": max(item["memory_peak_bytes"] for item in values),
        "slo_passed_runs": sum(1 for item in selected if item.get("slo_pass") is True),
    }


def markdown_report(source_sha: str, prereg_hash: str, records: list[dict], host: dict) -> str:
    lines = [
        "# T16 controlled-host product workload results",
        "",
        f"Source SHA: {source_sha}",
        f"Preregistration SHA-256: {prereg_hash}",
        f"Host: {host['cpu_model']} / {host['machine']} / kernel {host['kernel_release']}",
        f"PostgreSQL: {host['postgres_version']}; dedicated-host attestation: {host['physical_host_isolation']}",
        "",
        "| Candidate | Run | Completed req/s | p99 ms | CPU seconds | Peak memory bytes | OOM | Integrity violations | SLO |",
        "|---|---|---:|---:|---:|---:|---:|---:|---|",
    ]
    for item in records:
        m = item.get("metrics")
        if not isinstance(m, dict):
            lines.append(
                f"| {item['candidate']} | {item['run_id']} | — | — | — | — | — | — | FAIL (attempt error) |"
            )
            continue
        lines.append(
            f"| {item['candidate']} | {item['run_id']} | {m['completed_requests_per_second']:.2f} | "
            f"{m['p99_ms']:.3f} | {m['cpu_seconds']:.4f} | {m['memory_peak_bytes']} | "
            f"{m['oom_events']} | {m['security_or_integrity_violations']} | "
            f"{'PASS' if item.get('slo_pass') else 'FAIL'} |"
        )
    lines.extend(["", "## Cohort summary", ""])
    for candidate in CANDIDATES:
        cohort = aggregate(records, candidate)
        lines.append(
            f"- {candidate}: {cohort['runs']}/10 measured runs across {cohort['attempts']} attempts; "
            f"mean throughput {cohort['throughput_mean_rps'] if cohort['throughput_mean_rps'] is not None else 'n/a'} req/s; "
            f"mean p99 {cohort['p99_mean_ms'] if cohort['p99_mean_ms'] is not None else 'n/a'} ms; "
            f"mean CPU {cohort['cpu_mean_seconds'] if cohort['cpu_mean_seconds'] is not None else 'n/a'} s; "
            f"{cohort['slo_passed_runs']}/10 SLO passes."
        )
    lines.extend([
        "",
        "## Evidence boundary",
        "",
        "Every row is a separate container run with a one-vCPU/one-GiB cgroup-v2 candidate allocation. "
        "The load generator and PostgreSQL dependency use separate CPU allocations and cgroups. "
        "The 60/20/10/10 product workload includes authorized reads, plan validation, durable job admission, "
        "and expected capability denials. Expected 403 denials count as completed responses. "
        "Completed throughput is divided by the fixed 50-second offer window; post-window completion drain is reported separately.",
        "",
        "Physical-host exclusivity is an explicit operator attestation. Shared GitHub-hosted runner data is not used.",
        "",
    ])
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("experiments/e002/t16"))
    parser.add_argument("--source-sha", default=os.getenv("GITHUB_SHA", ""))
    parser.add_argument("--image", default="agent-native-t16-candidates:local")
    parser.add_argument("--postgres-dsn", default=os.getenv("AGENT_NATIVE_E002_POSTGRES_DSN", ""))
    args = parser.parse_args()
    output = args.output.resolve()
    root = Path.cwd().resolve()
    try:
        if not re.fullmatch(r"[0-9a-f]{40}", args.source_sha):
            raise ValueError("--source-sha must be a full 40-character Git SHA")
        actual_sha = run_command(["git", "rev-parse", "HEAD"])
        if actual_sha != args.source_sha:
            raise RuntimeError(f"checked-out source SHA {actual_sha} differs from preregistered {args.source_sha}")
        run_command(["git", "diff", "--quiet"])
        run_command(["git", "diff", "--cached", "--quiet"])
        untracked = run_command(["git", "ls-files", "--others", "--exclude-standard"]).splitlines()
        allowed_evidence = {
            str((output / "prereg.json").relative_to(root)),
            str((output / "host.json").relative_to(root)),
            str((output / "protocol.json").relative_to(root)),
        }
        unexpected_untracked = sorted(set(untracked) - allowed_evidence)
        if unexpected_untracked:
            raise RuntimeError("source checkout contains unexpected untracked files: " + ", ".join(unexpected_untracked))
        if not args.postgres_dsn:
            raise ValueError("AGENT_NATIVE_E002_POSTGRES_DSN is required")
        prereg_path, host_path, protocol_path = output / "prereg.json", output / "host.json", output / "protocol.json"
        for path in (prereg_path, host_path, protocol_path):
            if not path.is_file():
                raise RuntimeError(f"missing preregistered input: {path}")
        prereg = json.loads(prereg_path.read_text(encoding="utf-8"))
        host = json.loads(host_path.read_text(encoding="utf-8"))
        protocol = json.loads(protocol_path.read_text(encoding="utf-8"))
        if prereg.get("source_sha") != args.source_sha or protocol.get("source_sha") != args.source_sha:
            raise RuntimeError("source SHA differs from preregistered source revision")
        if host.get("physical_host_isolation") != "dedicated" or host.get("github_actions_runner") is not False:
            raise RuntimeError("dedicated non-GitHub host attestation is required")
        cpus = [host.get("candidate_cpu"), host.get("load_generator_cpu"), host.get("postgres_cpu")]
        if any(not isinstance(cpu, int) for cpu in cpus) or len(set(cpus)) != 3:
            raise RuntimeError("three distinct preregistered CPU allocations are required")
        core_keys = [physical_core_key(cpu) for cpu in cpus]
        recorded_cores = host.get("selected_physical_cores", {})
        expected_cores = [
            tuple(recorded_cores.get(name, []))
            for name in ("candidate", "load_generator", "postgresql")
        ]
        if len(set(core_keys)) != 3 or core_keys != expected_cores:
            raise RuntimeError("physical CPU topology differs from the preregistered three-core allocation")
        if not shutil.which("docker") or not shutil.which("taskset") or not shutil.which("psql"):
            raise RuntimeError("docker, taskset, and psql are required")
        if not Path("/sys/fs/cgroup/cgroup.controllers").is_file():
            raise RuntimeError("cgroup v2 is required")
        controllers = Path("/sys/fs/cgroup/cgroup.controllers").read_text(encoding="ascii").split()
        if not {"cpu", "memory", "cpuset"}.issubset(controllers):
            raise RuntimeError("host cgroup v2 lacks cpu, memory, or cpuset controllers")

        # Verify the external PostgreSQL service is live and record its process cgroup.
        pg_pid = int(psql(args.postgres_dsn, "SELECT pg_backend_pid()"))
        postgres_cgroup = cgroup_for_pid(pg_pid)
        postgres_cpu_max = (postgres_cgroup / "cpu.max").read_text(encoding="ascii").strip()
        postgres_cpuset = (postgres_cgroup / "cpuset.cpus.effective").read_text(encoding="ascii").strip()
        if postgres_cpu_max != CPU_MAX or parse_cpu_list(postgres_cpuset) != [host["postgres_cpu"]]:
            raise RuntimeError(
                f"PostgreSQL must have its own one-CPU cgroup on CPU {host['postgres_cpu']}: "
                f"cpu.max={postgres_cpu_max!r}, cpuset={postgres_cpuset!r}"
            )
        pg_version = psql(args.postgres_dsn, "SHOW server_version")
        if pg_version != str(host.get("postgres_version")):
            raise RuntimeError("PostgreSQL version differs from preregistered host manifest")

        schema = (output / "schema.sql")
        if not schema.is_file():
            schema = root / "experiments/e002/t16/schema.sql"
        run_command(["psql", args.postgres_dsn, "-X", "-q", "-v", "ON_ERROR_STOP=1", "-f", str(schema)])
        # Build both candidates from the exact checked-out source revision.
        run_command([
            "docker", "build", "--file", "experiments/e002/t16/Dockerfile",
            "--tag", args.image, ".",
        ], timeout=1800)
        bin_dir = output / "bin"
        bin_dir.mkdir(parents=True, exist_ok=True)
        run_command([
            "docker", "run", "--rm", "-v", f"{root}:/src:ro", "-v", f"{bin_dir}:/out",
            "-w", "/src/experiments/e002/t16/loadgen", "golang:1.23.12-bookworm",
            "go", "build", "-trimpath", "-o", "/out/t16-loadgen", ".",
        ], timeout=600)
        loadgen = bin_dir / "t16-loadgen"
        if not loadgen.is_file() or not os.access(loadgen, os.X_OK):
            raise RuntimeError("T16 load generator build did not produce an executable")

        read_token, deny_token = uuid.uuid4().hex + uuid.uuid4().hex, uuid.uuid4().hex + uuid.uuid4().hex
        prereg_hash = prereg.get("sha256")
        if not isinstance(prereg_hash, str) or len(prereg_hash) != 64:
            raise RuntimeError("preregistration SHA-256 is missing")
        canonical_prereg = {key: value for key, value in prereg.items() if key != "sha256"}
        import hashlib
        canonical_bytes = json.dumps(canonical_prereg, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
        if hashlib.sha256(canonical_bytes).hexdigest() != prereg_hash:
            raise RuntimeError("preregistration content does not match its SHA-256")
        if prereg.get("task") != "T16" or prereg.get("repetitions_per_candidate") != REPETITIONS or prereg.get("requests_per_repetition") != REQUESTS or prereg.get("concurrency") != CONCURRENCY or prereg.get("warmup_requests") != WARMUP or prereg.get("target_completed_rps") != TARGET_RPS:
            raise RuntimeError("preregistration workload parameters differ from the executable matrix")
        if protocol.get("request_mix") != {"authorized_read": 60, "validate_plan": 20, "job_admission": 10, "expected_denial": 10} or protocol.get("storage_engine") != "PostgreSQL" or protocol.get("arrival_model") != "open_loop" or protocol.get("arrival_schedule") != "fixed_rate_100_rps" or protocol.get("throughput_measurement") != "completed responses divided by the fixed 5000/100-second offer window; completion drain is reported separately":
            raise RuntimeError("protocol differs from the T16 product workload contract")
        ledger_path = output / "ledger.jsonl"
        ledger_path.write_text("", encoding="utf-8")
        runs: list[dict] = []
        rng = random.Random(SEED)
        for repetition in range(1, REPETITIONS + 1):
            order = list(CANDIDATES)
            rng.shuffle(order)
            for candidate in order:
                run_id = f"t16-{candidate}-rep-{repetition:02d}"
                container = f"t16-{candidate}-{repetition:02d}-{uuid.uuid4().hex[:8]}"
                run_started = utc_now()
                prefix = output / "runs" / candidate / f"rep-{repetition:02d}"
                prefix.parent.mkdir(parents=True, exist_ok=True)
                command = list(prereg["command"])
                record = None
                try:
                    run_command([
                        "docker", "run", "--detach", "--name", container,
                        "--cpus=1", f"--cpuset-cpus={host['candidate_cpu']}",
                        "--memory=1g", "--network=host",
                        "--env", f"T16_READ_TOKEN={read_token}",
                        "--env", f"T16_DENY_TOKEN={deny_token}",
                        "--env", "T16_TENANT_ID=tenant-a",
                        "--env", f"T16_PSQL_DSN={args.postgres_dsn}",
                        args.image, candidate,
                    ], timeout=60)
                    startup_seconds = wait_ready(container)
                    candidate_cgroup = container_cgroup(container)
                    cgroup_limits = verify_candidate_cgroup(candidate_cgroup, host["candidate_cpu"])
                    if candidate_cgroup == postgres_cgroup:
                        raise RuntimeError("PostgreSQL backend shares the candidate cgroup")
                    if not host.get("postgres_separate_from_candidate_cgroup"):
                        host["postgres_separate_from_candidate_cgroup"] = True
                        host["postgres_cgroup_path"] = str(postgres_cgroup)
                        host["postgres_cgroup_limits"] = {"cpu_max": postgres_cpu_max, "cpuset_cpus_effective": postgres_cpuset}
                        host["candidate_cgroup_path"] = str(candidate_cgroup)
                        host_path = host_path
                        host_path.write_text(json.dumps(host, indent=2, sort_keys=True) + "\n", encoding="utf-8")

                    if repetition == 1:
                        verify_product_conformance(args.postgres_dsn, read_token, deny_token)
                    psql(args.postgres_dsn, "SELECT t16_reset()")
                    events_before = read_memory_events(candidate_cgroup)
                    warmup_arguments = [
                        "--target", "http://127.0.0.1:8080", "--requests", str(REQUESTS),
                        "--concurrency", str(CONCURRENCY), "--warmup", str(WARMUP),
                        "--target-rps", str(TARGET_RPS), "--run-id", run_id + "-warmup",
                        "--output-prefix", "/evidence/" + str((prefix.parent / (prefix.name + "-warmup")).relative_to(output)),
                        "--warmup-only",
                    ]
                    loadgen_warmup = run_loadgen_container(
                        f"t16-loadgen-warmup-{uuid.uuid4().hex[:8]}",
                        warmup_arguments, host["load_generator_cpu"], root, bin_dir, output, read_token, deny_token,
                    )
                    psql(args.postgres_dsn, "SELECT t16_reset()")
                    cpu_before = read_cpu_usage(candidate_cgroup)
                    measured_arguments = [
                        "--target", "http://127.0.0.1:8080", "--requests", str(REQUESTS),
                        "--concurrency", str(CONCURRENCY), "--warmup", "0",
                        "--target-rps", str(TARGET_RPS), "--run-id", run_id,
                        "--output-prefix", "/evidence/" + str(prefix.relative_to(output)),
                    ]
                    loadgen_measured = run_loadgen_container(
                        f"t16-loadgen-measured-{uuid.uuid4().hex[:8]}",
                        measured_arguments, host["load_generator_cpu"], root, bin_dir, output, read_token, deny_token,
                    )
                    if any(path == str(candidate_cgroup) or path == str(postgres_cgroup) for path in (loadgen_warmup["path"], loadgen_measured["path"])):
                        raise RuntimeError("load generator shares the candidate or PostgreSQL cgroup")
                    cpu_after = read_cpu_usage(candidate_cgroup)
                    events_after = read_memory_events(candidate_cgroup)
                    summary = json.loads(prefix.with_suffix(".json").read_text(encoding="utf-8"))
                    memory_peak = int((candidate_cgroup / "memory.peak").read_text(encoding="ascii").strip())
                    oom_delta = sum(
                        events_after.get(key, 0) - events_before.get(key, 0)
                        for key in ("oom", "oom_kill")
                    )
                    violations = integrity_violations(args.postgres_dsn)
                    metrics = {
                        "completed_requests": int(summary["completed_requests"]),
                        "measurement_window_seconds": float(summary["measurement_window_seconds"]),
                        "elapsed_seconds": float(summary["elapsed_seconds"]),
                        "drain_seconds": float(summary["drain_seconds"]),
                        "completed_requests_per_second": float(summary["completed_requests_per_second"]),
                        "p99_ms": float(summary["latency_ms"]["p99"]),
                        "cpu_seconds": (cpu_after["usage_usec"] - cpu_before["usage_usec"]) / 1_000_000,
                        "memory_peak_bytes": memory_peak,
                        "oom_events": oom_delta,
                        "security_or_integrity_violations": violations,
                    }
                    checks = {
                        "throughput": metrics["completed_requests_per_second"] >= 100,
                        "p99": metrics["p99_ms"] <= 100,
                        "CPU": metrics["cpu_seconds"] <= 25,
                        "memory": metrics["memory_peak_bytes"] <= MEMORY_MAX,
                        "OOM": metrics["oom_events"] == 0,
                        "security/integrity": metrics["security_or_integrity_violations"] == 0,
                    }
                    record = {
                        "candidate": candidate,
                        "run_id": run_id,
                        "sha": args.source_sha,
                        "prereg_hash": prereg_hash,
                        "command": command,
                        "started_at": run_started,
                        "finished_at": utc_now(),
                        "raw_trace": str(prefix.with_suffix(".jsonl").relative_to(output)),
                        "status": "completed",
                        "functional_conformance": bool(summary["functional_success"]),
                        "metrics": metrics,
                        "slo_pass": all(checks.values()),
                        "startup_seconds": startup_seconds,
                        "load_generator_cgroups": {
                            "warmup": loadgen_warmup,
                            "measured": loadgen_measured,
                        },
                        "cgroup": {
                            "path": str(candidate_cgroup),
                            "limits": cgroup_limits,
                            "cpu_before": cpu_before,
                            "cpu_after": cpu_after,
                            "memory_events_before": events_before,
                            "memory_events_after": events_after,
                        },
                    }
                    if record["functional_conformance"] is not True:
                        raise RuntimeError(f"{candidate} {run_id} failed functional request conformance")
                    runs.append(record)
                    with ledger_path.open("a", encoding="utf-8") as handle:
                        handle.write(json.dumps(record, sort_keys=True) + "\n")
                        handle.flush()
                    print(
                        f"T16 {candidate} {repetition}/10: "
                        f"{metrics['completed_requests_per_second']:.2f} req/s, "
                        f"p99 {metrics['p99_ms']:.2f} ms, SLO {'PASS' if record['slo_pass'] else 'FAIL'}",
                        flush=True,
                    )
                except Exception as error:
                    if record is None:
                        record = {
                            "candidate": candidate,
                            "run_id": run_id,
                            "sha": args.source_sha,
                            "prereg_hash": prereg_hash,
                            "command": command,
                            "started_at": run_started,
                            "finished_at": utc_now(),
                            "raw_trace": str(prefix.with_suffix(".jsonl").relative_to(output)),
                            "status": "failed",
                            "functional_conformance": False,
                            "slo_pass": False,
                        }
                    else:
                        record["status"] = "failed"
                        record["functional_conformance"] = False
                        record["slo_pass"] = False
                        record["finished_at"] = utc_now()
                    record["error"] = f"{type(error).__name__}: {error}"
                    runs.append(record)
                    with ledger_path.open("a", encoding="utf-8") as handle:
                        handle.write(json.dumps(record, sort_keys=True) + "\\n")
                        handle.flush()
                    print(f"T16 {candidate} {repetition}/10 FAILED: {record['error']}", file=sys.stderr, flush=True)
                finally:
                    run_command(["docker", "rm", "--force", container], timeout=60, allow_failure=True)

        results = {
            "schema_version": 1,
            "source_sha": args.source_sha,
            "prereg_hash": prereg_hash,
            "candidate_order_seed": SEED,
            "repetitions_per_candidate": REPETITIONS,
            "runs": runs,
            "cohorts": {candidate: aggregate(runs, candidate) for candidate in CANDIDATES},
            "runtime_selection": None,
            "decision": "No runtime selected; T16 records measured SLO evidence only.",
        }
        (output / "results.json").write_text(json.dumps(results, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        (output / "report.md").write_text(markdown_report(args.source_sha, prereg_hash, runs, host), encoding="utf-8")
        print("T16 matrix complete: 10 repetitions per candidate; results and raw traces written.")
        return 0
    except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired, json.JSONDecodeError) as error:
        print(f"T16 controlled-host run failed: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
