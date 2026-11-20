#!/usr/bin/env python3
"""Run E-002 candidates in isolated one-vCPU cgroup-v2 containers.

The request generator is a separately built Go binary pinned to another host
CPU. Python only orchestrates containers and aggregates evidence.
"""
from __future__ import annotations

import argparse
import json
import os
import platform
import random
import shutil
import statistics
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

CANDIDATES = ("go-net-http", "rust-tokio-hyper", "wasi-p2-wasmtime", "beam-elixir-otp")
REPETITIONS = 10
REQUESTS = 5000
CONCURRENCY = 32
WARMUP = 250
SEED = 20261120
MEMORY_LIMIT_BYTES = 2 * 1024 * 1024 * 1024
CPU_MAX = "100000 100000"


def write_json(path: Path, value: dict) -> None:
    """Write standards-compliant JSON with a single trailing newline."""
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def parse_cpu_stat(raw: str) -> dict[str, int]:
    parsed: dict[str, int] = {}
    for line in raw.splitlines():
        fields = line.split()
        if len(fields) != 2:
            raise ValueError(f"invalid cpu.stat line: {line!r}")
        parsed[fields[0]] = int(fields[1])
    if "usage_usec" not in parsed:
        raise ValueError("cpu.stat is missing usage_usec")
    return parsed


def cpu_quota_cores(raw: str) -> float | None:
    fields = raw.strip().split()
    if len(fields) != 2:
        raise ValueError(f"invalid cpu.max: {raw!r}")
    if fields[0] == "max":
        return None
    quota, period = int(fields[0]), int(fields[1])
    if quota <= 0 or period <= 0:
        raise ValueError("cpu.max quota and period must be positive")
    return quota / period


def parse_cpu_list(raw: str) -> list[int]:
    cpus: set[int] = set()
    for item in raw.strip().split(","):
        if not item:
            continue
        if "-" in item:
            start_text, end_text = item.split("-", 1)
            start, end = int(start_text), int(end_text)
            if start < 0 or end < start:
                raise ValueError(f"invalid CPU range: {item!r}")
            cpus.update(range(start, end + 1))
        else:
            value = int(item)
            if value < 0:
                raise ValueError(f"invalid CPU id: {item!r}")
            cpus.add(value)
    return sorted(cpus)


def distribution(values: list[float]) -> dict:
    if not values:
        return {"n": 0, "mean": None, "sample_stddev": None, "median": None, "min": None, "max": None}
    return {
        "n": len(values),
        "mean": statistics.fmean(values),
        "sample_stddev": statistics.stdev(values) if len(values) > 1 else None,
        "median": statistics.median(values),
        "min": min(values),
        "max": max(values),
    }


def run_command(command: list[str], *, check: bool = True, timeout: int = 120) -> subprocess.CompletedProcess:
    completed = subprocess.run(command, capture_output=True, text=True, timeout=timeout, check=False)
    if check and completed.returncode != 0:
        raise RuntimeError(
            f"command_failed exit={completed.returncode}: {' '.join(command)}\n"
            f"stdout:\n{completed.stdout[-4000:]}\nstderr:\n{completed.stderr[-4000:]}"
        )
    return completed


def unified_cgroup_path(raw: str) -> str:
    entries = [line.split(":", 2)[2] for line in raw.splitlines() if line.startswith("0::")]
    if len(entries) != 1 or not entries[0].startswith("/"):
        raise ValueError("container process has no unique cgroup-v2 membership")
    return entries[0]


def container_cgroup_path(container: str) -> Path:
    pid_text = run_command(["docker", "inspect", "--format", "{{.State.Pid}}", container]).stdout.strip()
    pid = int(pid_text)
    if pid <= 0:
        raise RuntimeError(f"candidate container has invalid host PID: {pid_text!r}")
    membership = Path(f"/proc/{pid}/cgroup").read_text(encoding="ascii")
    relative = unified_cgroup_path(membership).lstrip("/")
    directory = Path("/sys/fs/cgroup") / relative
    if not directory.is_dir():
        raise RuntimeError(f"candidate cgroup-v2 directory is not visible on host: {directory}")
    return directory


def wait_ready(container: str, timeout_seconds: float = 30.0) -> float:
    started = time.monotonic()
    deadline = started + timeout_seconds
    while time.monotonic() < deadline:
        state = run_command(
            ["docker", "inspect", "--format", "{{.State.Running}}", container], check=False
        )
        if state.returncode != 0 or state.stdout.strip() != "true":
            logs = run_command(["docker", "logs", container], check=False)
            raise RuntimeError(f"candidate exited before readiness: {(logs.stdout + logs.stderr)[-4000:]}")
        try:
            with urllib.request.urlopen("http://127.0.0.1:8080/health", timeout=1.0) as response:
                if response.status == 200 and response.read() == b"ok":
                    return time.monotonic() - started
        except (OSError, TimeoutError, urllib.error.URLError):
            time.sleep(0.05)
    logs = run_command(["docker", "logs", container], check=False)
    raise RuntimeError(f"candidate did not become ready in {timeout_seconds}s: {(logs.stdout + logs.stderr)[-4000:]}")


def host_metadata(server_cpu: int, loadgen_cpu: int) -> dict:
    allowed = sorted(os.sched_getaffinity(0))
    cpu_model = "unknown"
    for line in Path("/proc/cpuinfo").read_text(encoding="utf-8", errors="replace").splitlines():
        if line.lower().startswith(("model name", "hardware")):
            cpu_model = line.split(":", 1)[-1].strip()
            break
    os_release = {}
    release_path = Path("/etc/os-release")
    if release_path.exists():
        for line in release_path.read_text(encoding="utf-8").splitlines():
            if "=" in line:
                key, value = line.split("=", 1)
                os_release[key] = value.strip('"')
    controllers = Path("/sys/fs/cgroup/cgroup.controllers").read_text(encoding="ascii").split()
    if not {"cpu", "memory", "cpuset"}.issubset(set(controllers)):
        raise RuntimeError(f"host cgroup v2 lacks required controllers: {controllers}")
    docker_version = run_command(["docker", "version", "--format", "{{.Server.Version}}"])
    return {
        "system": platform.system(),
        "release": platform.release(),
        "machine": platform.machine(),
        "platform": platform.platform(),
        "cpu_model": cpu_model,
        "allowed_host_cpus": allowed,
        "candidate_cpu": server_cpu,
        "load_generator_cpu": loadgen_cpu,
        "docker_server_version": docker_version.stdout.strip(),
        "os_release": os_release,
        "cgroup_version": 2,
        "cgroup_controllers": controllers,
        "github_actions_runner": os.getenv("GITHUB_ACTIONS") == "true",
        "runner_image_os": os.getenv("ImageOS"),
        "runner_image_version": os.getenv("ImageVersion"),
        "physical_host_isolation": "not asserted; cgroup isolation does not establish exclusive physical-host tenancy",
    }


def inspect_container_limits(cgroup: Path, server_cpu: int) -> dict:
    cpu_max = (cgroup / "cpu.max").read_text(encoding="ascii").strip()
    cpus = (cgroup / "cpuset.cpus.effective").read_text(encoding="ascii").strip()
    memory_max = (cgroup / "memory.max").read_text(encoding="ascii").strip()
    quota = cpu_quota_cores(cpu_max)
    cpu_ids = parse_cpu_list(cpus)
    if cpu_max != CPU_MAX or quota != 1.0:
        raise RuntimeError(f"candidate container is not limited to one CPU: cpu.max={cpu_max!r}")
    if cpu_ids != [server_cpu]:
        raise RuntimeError(f"candidate cpuset differs from selected CPU: {cpu_ids!r} != {[server_cpu]!r}")
    if int(memory_max) != MEMORY_LIMIT_BYTES:
        raise RuntimeError(f"candidate memory limit mismatch: {memory_max!r}")
    return {
        "cpu_max": cpu_max,
        "cpu_quota_cores": quota,
        "cpuset_cpus_effective": cpus,
        "memory_max": memory_max,
    }


def read_cgroup_snapshot(cgroup: Path) -> dict:
    cpu = parse_cpu_stat((cgroup / "cpu.stat").read_text(encoding="ascii"))
    return {
        "cpu_stat": cpu,
        "memory_current_bytes": int((cgroup / "memory.current").read_text(encoding="ascii").strip()),
        "memory_peak_bytes": int((cgroup / "memory.peak").read_text(encoding="ascii").strip()),
    }


def run_loadgen(binary: Path, output_prefix: Path, loadgen_cpu: int, *, warmup_only: bool) -> subprocess.CompletedProcess:
    command = [
        "taskset", "-c", str(loadgen_cpu), str(binary),
        "--target", "http://127.0.0.1:8080",
        "--concurrency", str(CONCURRENCY),
        "--warmup", str(WARMUP if warmup_only else 0),
    ]
    if warmup_only:
        command.append("--warmup-only")
    else:
        command.extend(["--requests", str(REQUESTS), "--output-prefix", str(output_prefix)])
    return run_command(command, timeout=300)


def aggregate_runs(records: list[dict]) -> dict:
    aggregate = {}
    for candidate in CANDIDATES:
        samples = [item for item in records if item.get("candidate") == candidate and item.get("functional_success")]
        aggregate[candidate] = {
            "successful_repetitions": len(samples),
            "throughput_requests_per_second": distribution([item["loadgen_summary"]["throughput_requests_per_second"] for item in samples]),
            "p50_ms": distribution([item["loadgen_summary"]["latency_ms"]["p50"] for item in samples]),
            "p95_ms": distribution([item["loadgen_summary"]["latency_ms"]["p95"] for item in samples]),
            "p99_ms": distribution([item["loadgen_summary"]["latency_ms"]["p99"] for item in samples]),
            "cpu_seconds": distribution([item["cgroup"]["cpu_seconds_delta"] for item in samples]),
            "cpu_percent_of_one_core": distribution([item["cgroup"]["cpu_percent_of_one_core"] for item in samples]),
            "peak_cgroup_memory_mib": distribution([item["cgroup"]["after"]["memory_peak_bytes"] / (1024 * 1024) for item in samples]),
            "startup_seconds": distribution([item["startup_seconds"] for item in samples]),
        }
    return aggregate


def markdown_report(matrix: dict) -> str:
    lines = [
        "# T09 controlled-cgroup measurement report",
        "",
        f"Source SHA: {matrix['source_sha']}",
        f"Seed: {matrix['seed']}; {matrix['repetitions_per_candidate']} repetitions/candidate; "
        f"{matrix['requests_per_repetition']:,} measured requests/repetition; concurrency {matrix['concurrency']}; warm-up {matrix['warmup']}.",
        "",
        "| Candidate | Throughput req/s (mean ± SD) | p99 ms (mean ± SD) | CPU s / 5k (mean ± SD) | Peak cgroup RSS MiB (median) | Successful runs |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for candidate, values in matrix["aggregate"].items():
        throughput = values["throughput_requests_per_second"]
        p99 = values["p99_ms"]
        cpu = values["cpu_seconds"]
        rss = values["peak_cgroup_memory_mib"]
        lines.append(
            f"| {candidate} | {throughput['mean']:.2f} ± {throughput['sample_stddev'] or 0:.2f} | "
            f"{p99['mean']:.3f} ± {p99['sample_stddev'] or 0:.3f} | "
            f"{cpu['mean']:.4f} ± {cpu['sample_stddev'] or 0:.4f} | "
            f"{rss['median']:.2f} | {values['successful_repetitions']}/10 |"
        )
    lines.extend([
        "",
        "## Evidence boundary",
        "",
        "Each candidate was placed in its own one-vCPU/two-GiB cgroup-v2 container. The Go load generator ran outside that cgroup and was pinned to a separate host CPU. Candidate CPU usage and throttling came from the candidate cgroup counters.",
        "",
        "The runner is an ephemeral GitHub-hosted VM. This does not establish exclusive physical-host tenancy or eliminate hypervisor/neighbor noise; it is not a dedicated bare-metal result or production-capacity certification.",
        "",
        "The workload is the existing in-memory GET /work?ms=0 probe. It does not exercise authentication, authorization, durable audit, PostgreSQL, outbox/idempotency, or the product control-plane request mix. No runtime is selected.",
        "",
        "Raw request-level JSONL, host metadata, per-run summaries, and cgroup counters are included in the workflow artifact.",
    ])
    return "\n".join(lines) + "\n"


def execute_matrix(args: argparse.Namespace) -> dict:
    if not Path("/sys/fs/cgroup/cgroup.controllers").is_file():
        raise RuntimeError("host does not expose cgroup v2")
    if not shutil.which("docker") or not shutil.which("taskset"):
        raise RuntimeError("docker and taskset are required")
    if not args.loadgen.is_file() or not os.access(args.loadgen, os.X_OK):
        raise RuntimeError(f"Go load generator is missing or not executable: {args.loadgen}")
    bundle = args.bundle.resolve()
    if not bundle.is_dir():
        raise RuntimeError(f"candidate bundle directory is missing: {bundle}")
    required = ("e002-go", "e002-rust", "wasmtime", "agent_native_e002_wasi_p2.wasm", "beam-release", "toolchains.txt")
    missing = [name for name in required if not (bundle / name).exists()]
    if missing:
        raise RuntimeError(f"candidate bundle is incomplete: {missing}")
    allowed = sorted(os.sched_getaffinity(0))
    if len(allowed) < 2:
        raise RuntimeError(f"need two host CPUs to isolate candidate and generator, got {allowed}")
    server_cpu, loadgen_cpu = allowed[0], allowed[1]
    host = host_metadata(server_cpu, loadgen_cpu)
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    (output / "host.json").write_text(json.dumps(host, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    toolchains = (bundle / "toolchains.txt").read_text(encoding="utf-8")
    (output / "toolchains.txt").write_text(toolchains, encoding="utf-8")
    protocol = {
        "load_generator": "Go net/http binary; not Python",
        "toolchains": toolchains,
        "requests_per_repetition": REQUESTS,
        "concurrency": CONCURRENCY,
        "warmup_requests": WARMUP,
        "repetitions_per_candidate": REPETITIONS,
        "candidate_order": "randomized independently for each repetition",
        "seed": SEED,
        "server_container_cpu_max": CPU_MAX,
        "server_container_cpuset_cpu": server_cpu,
        "load_generator_cpu": loadgen_cpu,
        "server_container_memory_max_bytes": MEMORY_LIMIT_BYTES,
        "connection_policy": "HTTP/1.1 keep-alive disabled; one connection per request",
        "endpoint": "GET /work?ms=0",
        "expected_response": "HTTP 200, exact body completed:0",
        "cpu_accounting": "candidate cgroup-v2 cpu.stat usage_usec delta; generator runs outside the cgroup",
    }
    (output / "protocol.json").write_text(json.dumps(protocol, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    run_command([
        "docker", "build", "--tag", args.image,
        "--file", str(args.dockerfile.resolve()),
        str(args.dockerfile.resolve().parent),
    ], timeout=900)
    protocol["container_image_inspect"] = run_command([
        "docker", "image", "inspect", args.image, "--format", "{{.Id}} {{json .RepoDigests}}"
    ]).stdout.strip()
    write_json(output / "protocol.json", protocol)
    rng = random.Random(SEED)
    records: list[dict] = []
    for repetition in range(1, REPETITIONS + 1):
        order = list(CANDIDATES)
        rng.shuffle(order)
        for position, candidate in enumerate(order, start=1):
            prefix = output / "runs" / candidate / f"rep-{repetition:02d}"
            prefix.parent.mkdir(parents=True, exist_ok=True)
            name = f"e002-t09-{uuid.uuid4().hex[:12]}"
            container_command = [
                "docker", "run", "--detach", "--name", name,
                "--cpus=1", f"--cpuset-cpus={server_cpu}", "--memory=2g",
                "--network=host", "--mount", f"type=bind,src={bundle},dst=/opt/candidates,readonly",
                args.image, candidate,
            ]
            run_command(container_command, timeout=300)
            record = {
                "candidate": candidate,
                "repetition": repetition,
                "order_position": position,
                "seed": SEED,
                "server_cpu": server_cpu,
                "load_generator_cpu": loadgen_cpu,
                "container": name,
            }
            try:
                startup_seconds = wait_ready(name)
                cgroup_path = container_cgroup_path(name)
                limits = inspect_container_limits(cgroup_path, server_cpu)
                run_loadgen(args.loadgen.resolve(), prefix, loadgen_cpu, warmup_only=True)
                before = read_cgroup_snapshot(cgroup_path)
                measured = run_loadgen(args.loadgen.resolve(), prefix, loadgen_cpu, warmup_only=False)
                after = read_cgroup_snapshot(cgroup_path)
                summary_path = prefix.with_suffix(".json")
                summary = json.loads(summary_path.read_text(encoding="utf-8"))
                cpu_before = before["cpu_stat"]
                cpu_after = after["cpu_stat"]
                usage_usec = cpu_after["usage_usec"] - cpu_before["usage_usec"]
                elapsed = float(summary["elapsed_seconds"])
                cgroup = {
                    "path": str(cgroup_path),
                    "limits": limits,
                    "before": before,
                    "after": after,
                    "usage_usec_delta": usage_usec,
                    "cpu_seconds_delta": usage_usec / 1_000_000,
                    "cpu_percent_of_one_core": (usage_usec / 1_000_000 / elapsed * 100) if elapsed > 0 else None,
                    "nr_throttled_delta": cpu_after.get("nr_throttled", 0) - cpu_before.get("nr_throttled", 0),
                    "throttled_usec_delta": cpu_after.get("throttled_usec", 0) - cpu_before.get("throttled_usec", 0),
                }
                record.update({
                    "startup_seconds": startup_seconds,
                    "warmup_requests_completed_before_measurement": WARMUP,
                    "elapsed_seconds": elapsed,
                    "loadgen_exit_code": measured.returncode,
                    "loadgen_summary": summary,
                    "cgroup": cgroup,
                    "raw_jsonl": str(prefix.with_suffix(".jsonl").relative_to(output)),
                    "summary_json": str(summary_path.relative_to(output)),
                    "functional_success": bool(summary["functional_success"]),
                })
                summary.update({
                    "startup_seconds": startup_seconds,
                    "candidate_cgroup": cgroup,
                    "candidate_cpu": server_cpu,
                    "load_generator_cpu": loadgen_cpu,
                    "repetition": repetition,
                    "order_position": position,
                    "source_sha": args.source_sha,
                })
                summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
                if not summary["functional_success"]:
                    raise RuntimeError(f"{candidate} repetition {repetition} had failed functional responses")
            except Exception as error:
                record["error"] = str(error)
                logs = run_command(["docker", "logs", name], check=False)
                record["docker_logs"] = (logs.stdout + logs.stderr)[-8000:]
                records.append(record)
                write_partial(output, args.source_sha, host, protocol, records)
                raise
            finally:
                run_command(["docker", "rm", "--force", name], check=False)
            records.append(record)
            print(f"T09 matrix {repetition}/{REPETITIONS} {candidate}: {record['loadgen_summary']['throughput_requests_per_second']:.2f} req/s", flush=True)
            write_partial(output, args.source_sha, host, protocol, records)

    matrix = {
        "schema_version": 1,
        "source_sha": args.source_sha,
        "measurement": "E-002 in-memory HTTP workload on a one-vCPU candidate cgroup",
        "seed": SEED,
        "repetitions_per_candidate": REPETITIONS,
        "requests_per_repetition": REQUESTS,
        "concurrency": CONCURRENCY,
        "warmup": WARMUP,
        "randomized_order": True,
        "host": host,
        "protocol": protocol,
        "aggregate": aggregate_runs(records),
        "runs": records,
        "all_functional_runs_passed": all(item.get("functional_success") for item in records) and len(records) == len(CANDIDATES) * REPETITIONS,
        "decision_grade": False,
        "runtime_selection": None,
        "limitations": [
            "The ephemeral GitHub-hosted VM does not establish exclusive physical-host tenancy.",
            "The measured workload is the trivial in-memory GET /work?ms=0 probe, not the product control-plane workload.",
            "The non-Python Go load generator is pinned outside the candidate cgroup; host-level noise can still affect it.",
            "No production runtime selection or SLO claim is made.",
        ],
    }
    (output / "matrix.json").write_text(json.dumps(matrix, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    report = markdown_report(matrix)
    (output / "report.md").write_text(report, encoding="utf-8")
    summary_path = os.getenv("GITHUB_STEP_SUMMARY")
    if summary_path:
        with Path(summary_path).open("a", encoding="utf-8") as handle:
            handle.write(report + "\n")
    if not matrix["all_functional_runs_passed"]:
        raise RuntimeError("one or more candidate repetitions did not pass functional response validation")
    return matrix


def write_partial(output: Path, source_sha: str, host: dict, protocol: dict, records: list[dict]) -> None:
    partial = {
        "source_sha": source_sha,
        "host": host,
        "protocol": protocol,
        "completed_runs": len(records),
        "runs": records,
    }
    (output / "matrix.partial.json").write_text(json.dumps(partial, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--loadgen", type=Path, required=True)
    parser.add_argument("--dockerfile", type=Path, default=Path("experiments/e002/controlled-host/Dockerfile"))
    parser.add_argument("--image", default="agent-native-e002-controlled-host:t09")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--source-sha", default=os.getenv("GITHUB_SHA", "unknown"))
    args = parser.parse_args()
    try:
        matrix = execute_matrix(args)
    except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired) as error:
        print(f"T09 controlled-host matrix failed: {error}", file=sys.stderr)
        return 2
    print(json.dumps({
        candidate: {
            "throughput_mean_rps": values["throughput_requests_per_second"]["mean"],
            "p99_mean_ms": values["p99_ms"]["mean"],
            "cpu_mean_seconds_per_5000": values["cpu_seconds"]["mean"],
            "runs": values["successful_repetitions"],
        }
        for candidate, values in matrix["aggregate"].items()
    }, indent=2, sort_keys=True))
    print("T09 controlled-cgroup measurement: PASS (40/40 functional runs)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
