#!/usr/bin/env python3
"""Prepare T16's preregistration and host manifest without inventing evidence.

The dedicated-host property is an explicit operator attestation. This tool
rejects GitHub-hosted runners and never infers physical exclusivity from cgroups.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import shutil
import shlex
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REQUEST_MIX = {
    "authorized_read": 60,
    "validate_plan": 20,
    "job_admission": 10,
    "expected_denial": 10,
}
THRESHOLDS = {
    "completed_requests_per_second_min": 100,
    "p99_ms": 100,
    "cpu_seconds_per_5000": 25,
    "memory_peak_bytes": 1073741824,
    "oom_events": 0,
    "security_or_integrity_violations": 0,
}


def canonical_json(value: dict[str, Any]) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def validate_attestation(value: Any) -> dict[str, str]:
    if not isinstance(value, dict):
        raise ValueError("host_attestation_must_be_object")
    if value.get("dedicated_physical_host") is not True:
        raise ValueError("dedicated_physical_host_attestation_required")
    for field in ("host_id", "attested_by", "attested_at"):
        if not isinstance(value.get(field), str) or not value[field].strip():
            raise ValueError(f"host_attestation_{field}_required")
    timestamp = datetime.fromisoformat(value["attested_at"].replace("Z", "+00:00"))
    if timestamp.tzinfo is None:
        raise ValueError("host_attestation_timestamp_must_include_timezone")
    return {key: value[key].strip() for key in ("host_id", "attested_by", "attested_at")}


def read_cpu_model() -> str:
    cpuinfo = Path("/proc/cpuinfo")
    if not cpuinfo.is_file():
        raise RuntimeError("cannot_read_cpu_model")
    for line in cpuinfo.read_text(encoding="utf-8", errors="replace").splitlines():
        if line.lower().startswith(("model name", "hardware")):
            return line.split(":", 1)[-1].strip()
    raise RuntimeError("cpu_model_not_found")


def postgres_version(dsn: str) -> str:
    if not shutil.which("psql"):
        raise RuntimeError("psql_required_to_verify_postgresql_dependency")
    result = subprocess.run(
        ["psql", dsn, "-X", "-A", "-t", "-v", "ON_ERROR_STOP=1", "-c", "SHOW server_version"],
        check=False, capture_output=True, text=True, timeout=15,
    )
    if result.returncode:
        raise RuntimeError("postgresql_preflight_failed: " + result.stderr.strip()[-2000:])
    version = result.stdout.strip()
    if not version:
        raise RuntimeError("postgresql_version_unavailable")
    return version


def physical_core_key(cpu: int, topology_root: Path = Path("/sys/devices/system/cpu")) -> tuple[int, int]:
    topology = topology_root / f"cpu{cpu}" / "topology"
    package_id = topology / "physical_package_id"
    core_id = topology / "core_id"
    if not package_id.is_file() or not core_id.is_file():
        raise RuntimeError(f"physical_cpu_topology_unavailable_for_cpu_{cpu}")
    return int(package_id.read_text().strip()), int(core_id.read_text().strip())


def select_distinct_physical_cpus(allowed_cpus: list[int], topology_root: Path = Path("/sys/devices/system/cpu")) -> list[int]:
    selected: list[int] = []
    seen: set[tuple[int, int]] = set()
    for cpu in allowed_cpus:
        key = physical_core_key(cpu, topology_root)
        if key not in seen:
            selected.append(cpu)
            seen.add(key)
        if len(selected) == 3:
            break
    return selected


def collect_host(attestation: dict[str, str], pg_version: str) -> dict[str, Any]:
    if platform.system() != "Linux":
        raise RuntimeError("T16_requires_linux")
    if os.getenv("GITHUB_ACTIONS", "").lower() == "true":
        raise RuntimeError("shared_github_actions_runner_is_not_controlled_host_evidence")
    if not Path("/sys/fs/cgroup/cgroup.controllers").is_file():
        raise RuntimeError("cgroup_v2_required")
    controllers = Path("/sys/fs/cgroup/cgroup.controllers").read_text(encoding="ascii").split()
    missing = sorted({"cpu", "memory", "cpuset"} - set(controllers))
    if missing:
        raise RuntimeError("missing_cgroup_v2_controllers: " + ",".join(missing))
    if not hasattr(os, "sched_getaffinity"):
        raise RuntimeError("sched_getaffinity_required")
    allowed_cpus = sorted(os.sched_getaffinity(0))
    physical_cpus = select_distinct_physical_cpus(allowed_cpus)
    if len(physical_cpus) < 3:
        raise RuntimeError("need_three_distinct_physical_cores_for_candidate_load_generator_and_postgresql")
    if not shutil.which("docker") or not shutil.which("taskset"):
        raise RuntimeError("docker_and_taskset_required")
    docker = subprocess.run(
        ["docker", "version", "--format", "{{.Server.Version}}"],
        check=False, capture_output=True, text=True, timeout=15,
    )
    if docker.returncode:
        raise RuntimeError("docker_daemon_unavailable: " + docker.stderr.strip()[-1000:])
    return {
        "system": "Linux",
        "kernel_release": platform.release(),
        "cpu_model": read_cpu_model(),
        "machine": platform.machine(),
        "host_cpu_affinity": allowed_cpus,
        "selected_physical_cores": {name: list(physical_core_key(cpu)) for name, cpu in zip(("candidate", "load_generator", "postgresql"), physical_cpus)},
        "candidate_vcpus": 1,
        "candidate_cpu": physical_cpus[0],
        "load_generator_cpu": physical_cpus[1],
        "postgres_cpu": physical_cpus[2],
        "candidate_memory_max_bytes": 1073741824,
        "cgroup_version": 2,
        "cgroup_controllers": controllers,
        "docker_server_version": docker.stdout.strip(),
        "postgres_version": pg_version,
        "postgres_separate_from_candidate_cgroup": False,
        "physical_host_isolation": "dedicated",
        "physical_host_attestation": attestation,
        "github_actions_runner": False,
        "evidence_note": (
            "Physical exclusivity is operator-attested, not inferred from cgroups. "
            "PostgreSQL/candidate cgroup separation must be verified after candidate startup."
        ),
    }


def build_preregistration(source_sha: str, command: list[str], now: datetime | None = None) -> dict[str, Any]:
    if not re.fullmatch(r"[0-9a-f]{40}", source_sha):
        raise ValueError("source_sha_must_be_full_40_character_git_sha")
    if not command or any(not item for item in command):
        raise ValueError("benchmark_command_required")
    prereg = {
        "task": "T16",
        "source_sha": source_sha,
        "preregistered_at": (now or datetime.now(timezone.utc)).astimezone(timezone.utc).isoformat(),
        "command": command,
        "repetitions_per_candidate": 10,
        "requests_per_repetition": 5000,
        "concurrency": 32,
        "warmup_requests": 250,
        "target_completed_rps": 100,
        "thresholds": THRESHOLDS,
        "decision_rule": (
            "Each non-cancelled repetition must complete 5000 requests and pass "
            "throughput, p99, CPU, memory, OOM, and security/integrity hard gates; "
            "report candidate-level pass only when all ten repetitions pass."
        ),
    }
    prereg["sha256"] = hashlib.sha256(canonical_json(prereg)).hexdigest()
    return prereg


def build_protocol(source_sha: str, pg_version: str) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "source_sha": source_sha,
        "arrival_model": "open_loop",
        "arrival_schedule": "fixed_rate_100_rps",
        "throughput_measurement": "completed responses divided by the fixed 5000/100-second offer window; completion drain is reported separately",
        "request_mix": REQUEST_MIX,
        "connection_policy": "HTTP/1.1 keep-alive; max 32 concurrent connections",
        "trace_timing_fields": ["scheduled_offset_ms", "offered_at", "started_at", "finished_at"],
        "repetitions_per_candidate": 10,
        "candidate_order": "randomized",
        "requests_per_repetition": 5000,
        "concurrency": 32,
        "warmup_requests": 250,
        "target_completed_rps": 100,
        "cpu_max": "100000 100000",
        "memory_max_bytes": 1073741824,
        "storage_engine": "PostgreSQL",
        "postgres_version": pg_version,
        "candidate_names": ["rust-tokio-hyper", "go-net-http"],
        "raw_trace_format": "one JSON object per offered request, including failed or client-dropped requests, JSONL",
        "denial_accounting": "expected 4xx denials count as completed requests",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--attestation", type=Path, required=True,
                        help="operator-supplied JSON attesting dedicated physical-host tenancy")
    parser.add_argument("--output", type=Path, default=Path("experiments/e002/t16"))
    parser.add_argument("--source-sha", default=os.getenv("GITHUB_SHA", ""))
    parser.add_argument("--command", required=True,
                        help="exact shell command that will execute the preregistered measurement")
    parser.add_argument("--postgres-dsn", default=os.getenv("AGENT_NATIVE_E002_POSTGRES_DSN", ""))
    args = parser.parse_args()
    try:
        attestation = validate_attestation(json.loads(args.attestation.read_text(encoding="utf-8")))
        if not args.postgres_dsn:
            raise ValueError("AGENT_NATIVE_E002_POSTGRES_DSN_required")
        pg_version = postgres_version(args.postgres_dsn)
        host = collect_host(attestation, pg_version)
        prereg = build_preregistration(args.source_sha, shlex.split(args.command))
        protocol = build_protocol(args.source_sha, pg_version)
        args.output.mkdir(parents=True, exist_ok=True)
        for name, value in (("prereg.json", prereg), ("host.json", host), ("protocol.json", protocol)):
            (args.output / name).write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print("T16 preflight prepared preregistration, host manifest, and protocol.")
        print("No benchmark was run; PostgreSQL/candidate cgroup separation remains unverified.")
        return 0
    except (OSError, ValueError, RuntimeError, json.JSONDecodeError, subprocess.TimeoutExpired) as error:
        print(f"T16 preflight failed: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
