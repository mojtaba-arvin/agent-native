#!/usr/bin/env python3
"""Repeated end-to-end load experiment for the E-009 durable HTTP kernel.

The optional containerized mode enforces server CPU/memory limits and reads
resource counters from that server's cgroup v2. GitHub-hosted runner contention
remains uncontrolled, so this is not a cross-runtime capacity certification.
"""
from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
import math
import os
import re
import shutil
import signal
import statistics
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from experiments.e002.benchmark import (
    PROCESS_SAMPLE_INTERVAL_SECONDS,
    ProcessTreeCpuTracker,
    proc_tree_sample,
)
from experiments.e002.product_workload import WORKLOAD_SEED, request_class


def request(base: str, method: str, path: str, token: str | None, *, body=None, key=None):
    headers = {}
    data = None
    if token is not None:
        headers["Authorization"] = f"Bearer {token}"
    if body is not None:
        data = json.dumps(body, separators=(",", ":")).encode()
        headers["Content-Type"] = "application/json"
    if key is not None:
        headers["Idempotency-Key"] = key
    req = urllib.request.Request(base + path, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=10) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as error:
        return error.code, error.read()
    except (OSError, TimeoutError, urllib.error.URLError) as error:
        # Preserve transport failures as observations; never let one request
        # abort the pool and tear down the server while other requests remain.
        return 0, f"{type(error).__name__}:{error}".encode("utf-8", errors="replace")


def find_id(value):
    if isinstance(value, dict):
        if isinstance(value.get("id"), str):
            return value["id"]
        for child in value.values():
            found = find_id(child)
            if found:
                return found
    elif isinstance(value, list):
        for child in value:
            found = find_id(child)
            if found:
                return found
    return None


def cgroup_v2_snapshot(pid):
    root = Path("/sys/fs/cgroup")
    try:
        membership = Path(f"/proc/{pid}/cgroup").read_text(encoding="ascii").splitlines()
        unified = next(line.split(":", 2)[2] for line in membership if line.startswith("0::"))
        directory = root / unified.lstrip("/")
        cpu_max = (directory / "cpu.max").read_text(encoding="ascii").strip()
        memory_max = (directory / "memory.max").read_text(encoding="ascii").strip()
        cpu_stat = {
            key: int(value)
            for key, value in (
                line.split() for line in (directory / "cpu.stat").read_text(encoding="ascii").splitlines()
            )
        }
        io_stat = {}
        for line in (directory / "io.stat").read_text(encoding="ascii").splitlines():
            fields = line.split()
            io_stat[fields[0]] = {
                key: int(value) for key, value in (field.split("=", 1) for field in fields[1:])
            }
        def read_pressure(name):
            parsed = {}
            for line in (directory / name).read_text(encoding="ascii").splitlines():
                fields = line.split()
                parsed[fields[0]] = {
                    key: (float(value) if key.startswith("avg") else int(value))
                    for key, value in (field.split("=", 1) for field in fields[1:])
                }
            return parsed
        quota, period = cpu_max.split()
        return {
            "path": unified,
            "cpu_max": cpu_max,
            "cpu_quota_cores": None if quota == "max" else int(quota) / int(period),
            "memory_max": memory_max,
            "cpu_stat": cpu_stat,
            "cpu_usage_usec": int(cpu_stat["usage_usec"]),
            "io_stat": io_stat,
            "cpu_pressure": read_pressure("cpu.pressure"),
            "io_pressure": read_pressure("io.pressure"),
            "memory_pressure": read_pressure("memory.pressure"),
            "memory_current_bytes": int((directory / "memory.current").read_text(encoding="ascii").strip()),
            "memory_peak_bytes": int((directory / "memory.peak").read_text(encoding="ascii").strip()),
            "pids_current": int((directory / "pids.current").read_text(encoding="ascii").strip()),
        }
    except (OSError, StopIteration, ValueError, IndexError, ZeroDivisionError, KeyError):
        return None


def percentile(values, fraction):
    ordered = sorted(values)
    if not ordered:
        return None
    return ordered[min(len(ordered) - 1, math.ceil(fraction * len(ordered)) - 1)]


def summarize_kind(results):
    latencies = [item["latency_ms"] for item in results]
    service_latencies = [item.get("service_latency_ms", item["latency_ms"]) for item in results]
    queue_delays = [item.get("client_queue_delay_ms", 0.0) for item in results]
    statuses = {}
    for item in results:
        statuses[str(item["status"])] = statuses.get(str(item["status"]), 0) + 1
    return {
        "requests": len(results),
        "failed_expectations": sum(not item["ok"] for item in results),
        "status_counts": statuses,
        "latency_ms": {
            "p50": percentile(latencies, 0.50),
            "p95": percentile(latencies, 0.95),
            "p99": percentile(latencies, 0.99),
            "max": max(latencies) if latencies else None,
            "mean": statistics.fmean(latencies) if latencies else None,
        },
        "service_latency_ms": {
            "p50": percentile(service_latencies, 0.50),
            "p95": percentile(service_latencies, 0.95),
            "p99": percentile(service_latencies, 0.99),
        },
        "client_queue_delay_ms": {
            "p50": percentile(queue_delays, 0.50),
            "p95": percentile(queue_delays, 0.95),
            "p99": percentile(queue_delays, 0.99),
            "max": max(queue_delays) if queue_delays else None,
        },
    }


def summarize(results, elapsed):
    latencies = [item["latency_ms"] for item in results]
    statuses = {}
    for item in results:
        statuses[str(item["status"])] = statuses.get(str(item["status"]), 0) + 1
    failures = [item for item in results if not item["ok"]]
    service_latencies = [item.get("service_latency_ms", item["latency_ms"]) for item in results]
    queue_delays = [item.get("client_queue_delay_ms", 0.0) for item in results]
    return {
        "requests": len(results),
        "failed_expectations": len(failures),
        "status_counts": statuses,
        "elapsed_seconds": elapsed,
        "throughput_requests_per_second": len(results) / elapsed if elapsed else 0,
        "latency_ms": {
            "p50": percentile(latencies, 0.50),
            "p95": percentile(latencies, 0.95),
            "p99": percentile(latencies, 0.99),
            "max": max(latencies) if latencies else None,
            "mean": statistics.fmean(latencies) if latencies else None,
        },
        "service_latency_ms": {
            "p50": percentile(service_latencies, 0.50),
            "p95": percentile(service_latencies, 0.95),
            "p99": percentile(service_latencies, 0.99),
        },
        "client_queue_delay_ms": {
            "p50": percentile(queue_delays, 0.50),
            "p95": percentile(queue_delays, 0.95),
            "p99": percentile(queue_delays, 0.99),
            "max": max(queue_delays) if queue_delays else None,
        },
        "response_bytes_total": sum(item["response_bytes"] for item in results),
    }


def sqlite_file_sizes(database_path):
    database = Path(database_path)
    sizes = {}
    for label, path in (
        ("database", database),
        ("wal", Path(str(database) + "-wal")),
        ("shm", Path(str(database) + "-shm")),
    ):
        try:
            sizes[label] = path.stat().st_size
        except FileNotFoundError:
            sizes[label] = 0
    return sizes


DEFAULT_CAPACITY_THRESHOLDS = {
    "minimum_throughput_requests_per_second": 100.0,
    "maximum_aggregate_p99_ms": 100.0,
    "maximum_one_core_cpu_percent": 50.0,
    "maximum_peak_cgroup_memory_bytes": 1_073_741_824,
    "required_server_cpu_quota_cores": 1.0,
    "required_server_memory_limit_bytes": 1_073_741_824,
    "maximum_unexpected_outcomes": 0,
}


def git_blob_sha1(data: bytes) -> str:
    header = f"blob {len(data)}\0".encode("ascii")
    return hashlib.sha1(header + data).hexdigest()


def load_preregistration_config(path: Path) -> tuple[dict, str]:
    raw_bytes = path.read_bytes()
    config = json.loads(raw_bytes)
    if not isinstance(config, dict):
        raise ValueError("preregistration config must be a JSON object")
    if set(config) != {"schema_version", "cohort_id", "no_apply", "purpose", "parameters", "thresholds"}:
        raise ValueError("preregistration config has missing or unknown top-level fields")
    if type(config["schema_version"]) is not int or config["schema_version"] != 1:
        raise ValueError("preregistration schema_version must be 1")
    if not isinstance(config["cohort_id"], str) or not config["cohort_id"].strip():
        raise ValueError("preregistration cohort_id is required")
    if config["no_apply"] is not True:
        raise ValueError("performance cohort must be no-apply")
    if not isinstance(config["purpose"], str) or not config["purpose"].strip():
        raise ValueError("preregistration purpose is required")

    parameters = config["parameters"]
    parameter_keys = {
        "requests_per_repetition", "repetitions", "client_concurrency", "target_rps",
        "containerized", "enforce_capacity_gate", "audit_batch_delay_ms",
        "job_batch_size", "job_batch_delay_ms",
    }
    if not isinstance(parameters, dict) or set(parameters) != parameter_keys:
        raise ValueError("preregistration parameters have missing or unknown fields")
    for key in ("requests_per_repetition", "repetitions", "client_concurrency", "job_batch_size"):
        if type(parameters[key]) is not int:
            raise ValueError(f"{key} must be an integer")
    if parameters["requests_per_repetition"] < 100:
        raise ValueError("requests_per_repetition must be at least 100")
    if not 1 <= parameters["repetitions"] <= 10:
        raise ValueError("repetitions must be between 1 and 10")
    if not 1 <= parameters["client_concurrency"] <= 64:
        raise ValueError("client_concurrency must be between 1 and 64")
    if not 1 <= parameters["job_batch_size"] <= 1024:
        raise ValueError("job_batch_size must be between 1 and 1024")
    for key in ("target_rps", "audit_batch_delay_ms", "job_batch_delay_ms"):
        value = parameters[key]
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            raise ValueError(f"{key} must be a finite number")
    if parameters["target_rps"] < 0:
        raise ValueError("target_rps must be non-negative")
    if not 0 <= parameters["audit_batch_delay_ms"] <= 50:
        raise ValueError("audit_batch_delay_ms must be between 0 and 50")
    if not 0 <= parameters["job_batch_delay_ms"] <= 50:
        raise ValueError("job_batch_delay_ms must be between 0 and 50")
    if parameters["containerized"] is not True or parameters["enforce_capacity_gate"] is not True:
        raise ValueError("capacity confirmation requires containerized execution and an enforced gate")

    thresholds = config["thresholds"]
    if not isinstance(thresholds, dict) or set(thresholds) != set(DEFAULT_CAPACITY_THRESHOLDS):
        raise ValueError("preregistration thresholds have missing or unknown fields")
    for key in (
        "minimum_throughput_requests_per_second", "maximum_aggregate_p99_ms",
        "maximum_one_core_cpu_percent", "required_server_cpu_quota_cores",
    ):
        value = thresholds[key]
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
            raise ValueError(f"{key} must be a finite positive number")
    for key in ("maximum_peak_cgroup_memory_bytes", "required_server_memory_limit_bytes"):
        if type(thresholds[key]) is not int or thresholds[key] <= 0:
            raise ValueError(f"{key} must be a positive integer")
    if type(thresholds["maximum_unexpected_outcomes"]) is not int or thresholds["maximum_unexpected_outcomes"] < 0:
        raise ValueError("maximum_unexpected_outcomes must be a non-negative integer")
    return config, git_blob_sha1(raw_bytes)


def evaluate_capacity_gate(aggregate, resource_metrics, thresholds=None):
    """Evaluate the preregistered single-node E-009 target using server cgroup metrics."""
    thresholds = dict(DEFAULT_CAPACITY_THRESHOLDS if thresholds is None else thresholds)
    cgroup = resource_metrics.get("cgroup_v2_limits") or {}
    checks = {
        "throughput_meets_preregistered_minimum": (
            aggregate.get("throughput_requests_per_second", 0) >= thresholds["minimum_throughput_requests_per_second"]
        ),
        "aggregate_p99_within_preregistered_maximum": (
            (aggregate.get("latency_ms") or {}).get("p99", float("inf")) <= thresholds["maximum_aggregate_p99_ms"]
        ),
        "server_cpu_within_preregistered_maximum": (
            resource_metrics.get("server_cpu_percent_of_one_core_during_load", float("inf")) <= thresholds["maximum_one_core_cpu_percent"]
        ),
        "peak_cgroup_memory_within_preregistered_maximum": (
            resource_metrics.get("server_peak_cgroup_memory_bytes") is not None
            and resource_metrics["server_peak_cgroup_memory_bytes"] <= thresholds["maximum_peak_cgroup_memory_bytes"]
        ),
        "server_cgroup_matches_preregistered_cpu_quota": (
            resource_metrics.get("server_containerized") is True
            and resource_metrics.get("server_cpu_quota_cores") == thresholds["required_server_cpu_quota_cores"]
            and cgroup.get("cpu_max") == "100000 100000"
        ),
        "server_cgroup_matches_preregistered_memory_limit": (
            cgroup.get("memory_max") == str(thresholds["required_server_memory_limit_bytes"])
        ),
        "unexpected_outcomes_within_preregistered_maximum": aggregate.get("failed_expectations") <= thresholds["maximum_unexpected_outcomes"],
    }
    return {
        "enabled": True,
        "passed": all(checks.values()),
        "thresholds": thresholds,
        "checks": checks,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, help="load all cohort parameters and thresholds from a frozen JSON manifest")
    parser.add_argument("--requests", type=int, default=1000, help="measured requests per repetition")
    parser.add_argument("--repetitions", type=int, default=5)
    parser.add_argument("--concurrency", type=int, default=32)
    parser.add_argument("--target-rps", type=float, default=100.0,
                        help="open-loop offered rate per repetition; 0 selects saturation mode")
    parser.add_argument("--containerized", action="store_true",
                        help="run the server in a one-CPU/1-GiB cgroup-limited container")
    parser.add_argument("--enforce-capacity-gate", action="store_true",
                        help="fail unless the measured run meets the 100 req/s single-node gate")
    parser.add_argument("--audit-batch-delay-ms", type=float, default=2.0)
    parser.add_argument("--job-batch-size", type=int, default=32)
    parser.add_argument("--job-batch-delay-ms", type=float, default=0.5)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    preregistration = None
    preregistration_sha1 = None
    if args.config is not None:
        try:
            preregistration, preregistration_sha1 = load_preregistration_config(args.config)
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
            parser.error(f"invalid preregistration config: {exc}")
        parameters = preregistration["parameters"]
        args.requests = parameters["requests_per_repetition"]
        args.repetitions = parameters["repetitions"]
        args.concurrency = parameters["client_concurrency"]
        args.target_rps = parameters["target_rps"]
        args.containerized = parameters["containerized"]
        args.enforce_capacity_gate = parameters["enforce_capacity_gate"]
        args.audit_batch_delay_ms = parameters["audit_batch_delay_ms"]
        args.job_batch_size = parameters["job_batch_size"]
        args.job_batch_delay_ms = parameters["job_batch_delay_ms"]
    if args.requests < 100 or not 1 <= args.repetitions <= 10:
        parser.error("requests must be >=100 and repetitions must be 1..10")
    if not 1 <= args.concurrency <= 64:
        parser.error("concurrency must be 1..64")
    if not math.isfinite(args.target_rps) or args.target_rps < 0:
        parser.error("target-rps must be finite and non-negative")
    if not math.isfinite(args.audit_batch_delay_ms) or not 0 <= args.audit_batch_delay_ms <= 50:
        parser.error("audit batch delay must be between 0 and 50 ms")
    if not 1 <= args.job_batch_size <= 1024:
        parser.error("job batch size must be between 1 and 1024")
    if not math.isfinite(args.job_batch_delay_ms) or not 0 <= args.job_batch_delay_ms <= 50:
        parser.error("job batch delay must be between 0 and 50 ms")

    token = "e009-performance-smoke-token-" + uuid.uuid4().hex
    denial_token = token + "-read-only"
    env = dict(
        os.environ,
        AGENT_NATIVE_DEMO_TOKEN=token,
        AGENT_NATIVE_PRODUCT_WORKLOAD="1",
    )
    with tempfile.TemporaryDirectory(prefix="e009-perf-") as temp:
        db = Path(temp) / "kernel.sqlite3"
        server_concurrency = max(64, args.concurrency * 2)
        container_name = "e009-perf-" + uuid.uuid4().hex[:12] if args.containerized else None
        server_cpu_affinity = None
        if args.containerized:
            server_command = [
                "docker", "run", "--rm", "--name", container_name,
                "--cpus=1", "--memory=1g", "--stop-signal=SIGINT",
                "--publish", "127.0.0.1:18080:8080",
                "--volume", f"{REPOSITORY_ROOT}:/workspace:ro",
                "--volume", f"{temp}:/data",
                "--workdir", "/workspace",
                "--env", f"AGENT_NATIVE_DEMO_TOKEN={token}",
                "--env", "AGENT_NATIVE_ALLOW_NON_LOOPBACK=1",
                "python:3.11-slim",
                "python", "experiments/e009/serve.py",
                "--database", "/data/kernel.sqlite3",
                "--host", "0.0.0.0", "--port", "8080",
                "--max-concurrency", str(server_concurrency),
                "--audit-batch-delay-ms", str(args.audit_batch_delay_ms),
                "--job-batch-size", str(args.job_batch_size),
                "--job-batch-delay-ms", str(args.job_batch_delay_ms),
            ]
        else:
            server_command = [
                sys.executable, "experiments/e009/serve.py", "--database", str(db),
                "--port", "0", "--max-concurrency", str(server_concurrency),
                "--audit-batch-delay-ms", str(args.audit_batch_delay_ms),
                "--job-batch-size", str(args.job_batch_size),
                "--job-batch-delay-ms", str(args.job_batch_delay_ms),
            ]
            if hasattr(os, "sched_getaffinity") and shutil.which("taskset"):
                available_cpus = sorted(os.sched_getaffinity(0))
                if available_cpus:
                    server_cpu_affinity = available_cpus[0]
                    server_command = ["taskset", "-c", str(server_cpu_affinity), *server_command]
        process = subprocess.Popen(
            server_command,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, env=env,
            bufsize=1,
        )
        try:
            deadline = time.monotonic() + (90 if args.containerized else 20)
            base = None
            startup_output = []
            while time.monotonic() < deadline:
                line = process.stdout.readline()
                if line:
                    startup_output.append(line)
                if not line and process.poll() is not None:
                    detail = "".join(startup_output)[-4000:]
                    raise RuntimeError(
                        f"E-009 server exited before startup (exit={process.returncode}): {detail}"
                    )
                match = re.search(r"http://127\.0\.0\.1:(\d+)", line)
                if match:
                    base = "http://127.0.0.1:18080" if args.containerized else f"http://127.0.0.1:{match.group(1)}"
                    break
            if base is None:
                raise RuntimeError("E-009 server startup deadline exceeded")

            status, payload = request(base, "POST", "/items", token,
                                      body={"name": "perf-seed-" + uuid.uuid4().hex},
                                      key="seed-item-" + uuid.uuid4().hex)
            if status != 201:
                raise RuntimeError(f"seed item failed: HTTP {status} {payload[:200]!r}")
            item_id = find_id(json.loads(payload))
            if not item_id:
                raise RuntimeError("seed item response omitted item id")

            base_contract = (REPOSITORY_ROOT / "experiments/e009/catalog.an").read_bytes()
            base_revision = hashlib.sha256(base_contract).hexdigest()

            def one(index, scheduled_at=None):
                kind = request_class(index, seed=WORKLOAD_SEED)
                if kind == "authorized_read":
                    method, target, auth, body, key, expected = (
                        "GET", f"/items/{item_id}", token, None, None, 200)
                elif kind == "validate_plan":
                    method, target, auth, body, key, expected = (
                        "POST", "/control/validate-plan", token,
                        {"operation_name": "get_item", "base_revision": base_revision},
                        None, 200)
                elif kind == "job_admission":
                    method, target, auth, body, key, expected = (
                        "POST", "/items/rebuild", token, {}, f"load-{index}", 202)
                else:
                    method, target, auth, body, key, expected = (
                        "POST", "/control/validate-plan", denial_token,
                        {"operation_name": "get_item", "base_revision": base_revision},
                        None, 403)
                started = time.perf_counter()
                status, response = request(base, method, target, auth, body=body, key=key)
                finished = time.perf_counter()
                service_latency_ms = (finished - started) * 1000
                queue_delay_ms = (
                    max(0.0, started - scheduled_at) * 1000
                    if scheduled_at is not None else 0.0
                )
                return {
                    "kind": kind, "status": status, "expected": expected,
                    "latency_ms": (
                        (finished - scheduled_at) * 1000
                        if scheduled_at is not None else service_latency_ms
                    ),
                    "service_latency_ms": service_latency_ms,
                    "client_queue_delay_ms": queue_delay_ms,
                    "ok": status == expected,
                    "response_bytes": len(response),
                }

            with concurrent.futures.ThreadPoolExecutor(max_workers=args.concurrency) as pool:
                warmup = list(pool.map(one, range(-100, 0)))
                if args.containerized:
                    inspect = subprocess.check_output(
                        ["docker", "inspect", "--format", "{{.State.Pid}}", container_name],
                        text=True,
                    ).strip()
                    container_pid = int(inspect)
                    cgroup_start = cgroup_v2_snapshot(container_pid)
                    if cgroup_start is None or cgroup_start["cpu_quota_cores"] is None:
                        raise RuntimeError("container cgroup v2 CPU quota is unavailable")
                    cpu_tracker = None
                    stop_cpu_monitor = None
                    cpu_monitor = None
                else:
                    container_pid = process.pid
                    cgroup_start = None
                    cpu_tracker = ProcessTreeCpuTracker()
                    cpu_tracker.observe(proc_tree_sample(process.pid))
                    start_cpu_seconds = cpu_tracker.total_cpu_seconds
                    cpu_tracker.peak_tree_rss_bytes = 0
                    stop_cpu_monitor = threading.Event()

                    def monitor_server_cpu():
                        while not stop_cpu_monitor.is_set():
                            cpu_tracker.observe(proc_tree_sample(process.pid))
                            stop_cpu_monitor.wait(PROCESS_SAMPLE_INTERVAL_SECONDS)

                    cpu_monitor = threading.Thread(target=monitor_server_cpu, daemon=True)
                    cpu_monitor.start()
                repetitions = []
                all_results = []
                for repetition in range(args.repetitions):
                    offset = repetition * args.requests
                    started = time.perf_counter()
                    if args.target_rps == 0:
                        results = list(pool.map(one, range(offset, offset + args.requests)))
                    else:
                        futures = []
                        for index in range(offset, offset + args.requests):
                            scheduled_at = started + (index - offset) / args.target_rps
                            delay = scheduled_at - time.perf_counter()
                            if delay > 0:
                                time.sleep(delay)
                            futures.append(pool.submit(one, index, scheduled_at))
                        results = [future.result() for future in futures]
                    elapsed = time.perf_counter() - started
                    repetitions.append({"repetition": repetition + 1, **summarize(results, elapsed)})
                    all_results.extend(results)

            if args.containerized:
                cgroup_end = cgroup_v2_snapshot(container_pid)
                if cgroup_end is None:
                    raise RuntimeError("container cgroup v2 metrics disappeared before shutdown")
                server_cpu_seconds = max(
                    0.0, (cgroup_end["cpu_usage_usec"] - cgroup_start["cpu_usage_usec"]) / 1_000_000
                )
                server_peak_rss_bytes = None
                server_peak_cgroup_memory_bytes = cgroup_end["memory_peak_bytes"]
                server_observed_process_count = None
                server_cgroup_pids_current = cgroup_end["pids_current"]
                server_cgroup_memory_current_bytes = cgroup_end["memory_current_bytes"]
                cgroup_limits = cgroup_end
            else:
                stop_cpu_monitor.set()
                cpu_monitor.join()
                cpu_tracker.observe(proc_tree_sample(process.pid))
                server_cpu_seconds = max(0.0, cpu_tracker.total_cpu_seconds - start_cpu_seconds)
                server_peak_rss_bytes = cpu_tracker.peak_tree_rss_bytes or None
                server_peak_cgroup_memory_bytes = None
                server_observed_process_count = cpu_tracker.observed_process_count
                server_cgroup_pids_current = None
                server_cgroup_memory_current_bytes = None
                cgroup_limits = None
            total_elapsed = sum(item["elapsed_seconds"] for item in repetitions)
            aggregate = summarize(all_results, total_elapsed)
            by_kind = {
                kind: summarize_kind([item for item in all_results if item["kind"] == kind])
                for kind in sorted({item["kind"] for item in all_results})
            }
            sqlite_file_sizes_during_load = sqlite_file_sizes(db)

            # Stop gracefully so serve.py can report the counters collected by
            # the same FULL-synchronous audit sink used for the measured calls.
            if args.containerized:
                subprocess.run(
                    ["docker", "stop", "--time", "10", container_name],
                    check=False, capture_output=True, text=True,
                )
            else:
                process.send_signal(signal.SIGINT)
            process.wait(timeout=15)
            sqlite_file_sizes_after_shutdown = sqlite_file_sizes(db)
            remaining_output = process.stdout.read() if process.stdout else ""
            audit_match = re.search(r"E009_AUDIT_METRICS=(\{[^\n]+\})", remaining_output)
            if audit_match is None:
                raise RuntimeError("server did not emit final audit commit counters")
            audit_metrics = json.loads(audit_match.group(1))
            work_match = re.search(r"E009_WORK_METRICS=(\{[^\n]+\})", remaining_output)
            if work_match is None:
                raise RuntimeError("server did not emit final durable submission counters")
            work_metrics = json.loads(work_match.group(1))
            failures = [item for item in all_results if not item["ok"]]
            summary = {
                "schema_version": 2,
                "classification": "shared_runner_repeated_product_path_smoke_not_capacity_claim",
                "workload": {
                    "requests_per_repetition": args.requests,
                    "repetitions": args.repetitions,
                    "warmup_requests": len(warmup),
                    "measured_requests": len(all_results),
                    "client_concurrency": args.concurrency,
                    "arrival_mode": "saturated_closed_loop" if args.target_rps == 0 else "open_loop",
                    "target_rps": args.target_rps or None,
                    "mix": {"authorized_item_read": 0.6, "authorized_job_read": 0.2,
                            "durable_job_admission": 0.1, "unauthenticated_read": 0.1},
                    "database": "file-backed SQLite WAL via E-009 serve.py",
                    "server_max_concurrency": server_concurrency,
                    "audit_batch_delay_ms": args.audit_batch_delay_ms,
                    "job_batch_size": args.job_batch_size,
                    "job_batch_delay_ms": args.job_batch_delay_ms,
                },
                "aggregate": aggregate,
                "resource_metrics": {
                    "accounting": ("container cgroup v2 cpu.stat + memory.peak" if args.containerized else "5ms /proc process-tree cumulative-max; diagnostic, not cgroup v2"),
                    "server_cpu_seconds": server_cpu_seconds,
                    "server_peak_rss_bytes": server_peak_rss_bytes,
                    "server_peak_cgroup_memory_bytes": server_peak_cgroup_memory_bytes,
                    "server_observed_process_count": server_observed_process_count,
                    "server_cgroup_pids_current": server_cgroup_pids_current,
                    "server_cgroup_memory_current_bytes": server_cgroup_memory_current_bytes,
                    "server_cpu_affinity": server_cpu_affinity,
                    "server_cpu_quota_cores": cgroup_limits["cpu_quota_cores"] if cgroup_limits else None,
                    "cgroup_v2_limits": cgroup_limits,
                    "cgroup_v2_start_snapshot": cgroup_start if args.containerized else None,
                    "server_containerized": args.containerized,
                    "sqlite_file_sizes_during_load_bytes": sqlite_file_sizes_during_load,
                    "sqlite_file_sizes_after_shutdown_bytes": sqlite_file_sizes_after_shutdown,
                    "server_cpu_percent_of_one_core_during_load": (
                        server_cpu_seconds / total_elapsed * 100 if total_elapsed else None
                    ),
                    "estimated_cpu_percent_at_100_rps": (
                        server_cpu_seconds / len(all_results) * 10000 if all_results else None
                    ),
                },
                "by_operation_kind": by_kind,
                "audit_metrics": audit_metrics,
                "work_metrics": work_metrics,
                "repetitions": repetitions,
                "slowest_requests": sorted(
                    all_results, key=lambda item: item["latency_ms"], reverse=True
                )[:20],
                "limitations": [
                    "shared GitHub host; server resource limits and accounting are cgroup v2 controlled when containerized" if args.containerized else "shared GitHub host; server process-tree accounting is diagnostic only",
                    "single E-009 process and one SQLite database",
                    "not a 10-repetition controlled cross-runtime capacity comparison",
                ],
            }
            if preregistration is not None:
                summary["preregistration"] = {
                    "cohort_id": preregistration["cohort_id"],
                    "config_path": args.config.as_posix(),
                    "git_blob_sha1": preregistration_sha1,
                    "thresholds": preregistration["thresholds"],
                }
            if args.enforce_capacity_gate:
                summary["capacity_gate"] = evaluate_capacity_gate(
                    summary["aggregate"],
                    summary["resource_metrics"],
                    preregistration["thresholds"] if preregistration is not None else None,
                )
            rendered = json.dumps(summary, indent=2, sort_keys=True)
            print(rendered)
            if args.output:
                args.output.parent.mkdir(parents=True, exist_ok=True)
                args.output.write_text(rendered + "\n", encoding="utf-8")
            if failures:
                raise SystemExit(f"{len(failures)} of {len(all_results)} measured requests did not match expected status")
            if args.enforce_capacity_gate and not summary["capacity_gate"]["passed"]:
                failed_checks = [
                    name for name, passed in summary["capacity_gate"]["checks"].items() if not passed
                ]
                raise SystemExit("E-009 capacity gate failed: " + ", ".join(failed_checks))
        finally:
            if "stop_cpu_monitor" in locals() and stop_cpu_monitor is not None:
                stop_cpu_monitor.set()
            if "cpu_monitor" in locals() and cpu_monitor is not None:
                cpu_monitor.join()
            if process.poll() is None:
                if args.containerized and container_name:
                    subprocess.run(
                        ["docker", "stop", "--time", "5", container_name],
                        check=False, capture_output=True, text=True,
                    )
                else:
                    process.send_signal(signal.SIGINT)
                try:
                    process.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()


if __name__ == "__main__":
    main()
