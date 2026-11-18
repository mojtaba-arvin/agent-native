#!/usr/bin/env python3
"""Repeated end-to-end load smoke for the E-009 durable HTTP kernel.

This is a product-path diagnostic, not a controlled capacity benchmark:
GitHub-hosted runners are shared and cgroup isolation is not asserted.
"""
from __future__ import annotations

import argparse
import concurrent.futures
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


def percentile(values, fraction):
    ordered = sorted(values)
    if not ordered:
        return None
    return ordered[min(len(ordered) - 1, math.ceil(fraction * len(ordered)) - 1)]


def summarize_kind(results):
    latencies = [item["latency_ms"] for item in results]
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
    }


def summarize(results, elapsed):
    latencies = [item["latency_ms"] for item in results]
    statuses = {}
    for item in results:
        statuses[str(item["status"])] = statuses.get(str(item["status"]), 0) + 1
    failures = [item for item in results if not item["ok"]]
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
        "response_bytes_total": sum(item["response_bytes"] for item in results),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--requests", type=int, default=1000, help="measured requests per repetition")
    parser.add_argument("--repetitions", type=int, default=5)
    parser.add_argument("--concurrency", type=int, default=32)
    parser.add_argument("--audit-batch-delay-ms", type=float, default=2.0)
    parser.add_argument("--job-batch-delay-ms", type=float, default=0.5)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.requests < 100 or not 1 <= args.repetitions <= 10:
        parser.error("requests must be >=100 and repetitions must be 1..10")
    if not 1 <= args.concurrency <= 64:
        parser.error("concurrency must be 1..64")
    if not math.isfinite(args.audit_batch_delay_ms) or not 0 <= args.audit_batch_delay_ms <= 50:
        parser.error("audit batch delay must be between 0 and 50 ms")
    if not math.isfinite(args.job_batch_delay_ms) or not 0 <= args.job_batch_delay_ms <= 50:
        parser.error("job batch delay must be between 0 and 50 ms")

    token = "e009-performance-smoke-token-" + uuid.uuid4().hex
    env = dict(os.environ, AGENT_NATIVE_DEMO_TOKEN=token)
    with tempfile.TemporaryDirectory(prefix="e009-perf-") as temp:
        db = Path(temp) / "kernel.sqlite3"
        server_concurrency = max(64, args.concurrency * 2)
        server_command = [
            sys.executable, "experiments/e009/serve.py", "--database", str(db),
            "--port", "0", "--max-concurrency", str(server_concurrency),
            "--audit-batch-delay-ms", str(args.audit_batch_delay_ms),
            "--job-batch-delay-ms", str(args.job_batch_delay_ms),
        ]
        server_cpu_affinity = None
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
            deadline = time.monotonic() + 20
            base = None
            while time.monotonic() < deadline:
                line = process.stdout.readline()
                if not line and process.poll() is not None:
                    raise RuntimeError("E-009 server exited before startup")
                match = re.search(r"http://127\.0\.0\.1:(\d+)", line)
                if match:
                    base = f"http://127.0.0.1:{match.group(1)}"
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

            status, payload = request(base, "POST", "/items/rebuild", token,
                                      body={}, key="seed-job-" + uuid.uuid4().hex)
            if status not in (200, 202):
                raise RuntimeError(f"seed job failed: HTTP {status} {payload[:200]!r}")
            job_id = find_id(json.loads(payload))
            if not job_id:
                raise RuntimeError("seed job response omitted job id")

            def one(index):
                slot = index % 10
                if slot < 6:
                    kind = "authorized_item_read"
                    method, target, auth, body, key, expected = (
                        "GET", f"/items/{item_id}", token, None, None, 200)
                elif slot < 8:
                    kind = "authorized_job_read"
                    method, target, auth, body, key, expected = (
                        "GET", f"/jobs/{job_id}", token, None, None, 200)
                elif slot == 8:
                    kind = "durable_job_admission"
                    method, target, auth, body, key, expected = (
                        "POST", "/items/rebuild", token, {}, f"load-{index}-{uuid.uuid4().hex}", 202)
                else:
                    kind = "unauthenticated_read"
                    method, target, auth, body, key, expected = (
                        "GET", f"/items/{item_id}", None, None, None, 401)
                started = time.perf_counter()
                status, response = request(base, method, target, auth, body=body, key=key)
                elapsed_ms = (time.perf_counter() - started) * 1000
                return {
                    "kind": kind, "status": status, "expected": expected,
                    "latency_ms": elapsed_ms, "ok": status == expected,
                    "response_bytes": len(response),
                }

            with concurrent.futures.ThreadPoolExecutor(max_workers=args.concurrency) as pool:
                warmup = list(pool.map(one, range(-100, 0)))
                cpu_tracker = ProcessTreeCpuTracker()
                cpu_tracker.observe(proc_tree_sample(process.pid))
                start_cpu_seconds = cpu_tracker.total_cpu_seconds
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
                    results = list(pool.map(one, range(offset, offset + args.requests)))
                    elapsed = time.perf_counter() - started
                    repetitions.append({"repetition": repetition + 1, **summarize(results, elapsed)})
                    all_results.extend(results)

            stop_cpu_monitor.set()
            cpu_monitor.join()
            cpu_tracker.observe(proc_tree_sample(process.pid))
            server_cpu_seconds = max(0.0, cpu_tracker.total_cpu_seconds - start_cpu_seconds)
            server_peak_rss_bytes = cpu_tracker.peak_tree_rss_bytes or None
            server_observed_process_count = cpu_tracker.observed_process_count
            total_elapsed = sum(item["elapsed_seconds"] for item in repetitions)
            aggregate = summarize(all_results, total_elapsed)
            by_kind = {
                kind: summarize_kind([item for item in all_results if item["kind"] == kind])
                for kind in sorted({item["kind"] for item in all_results})
            }

            # Stop gracefully so serve.py can report the counters collected by
            # the same FULL-synchronous audit sink used for the measured calls.
            process.send_signal(signal.SIGINT)
            process.wait(timeout=15)
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
                    "mix": {"authorized_item_read": 0.6, "authorized_job_read": 0.2,
                            "durable_job_admission": 0.1, "unauthenticated_read": 0.1},
                    "database": "file-backed SQLite WAL via E-009 serve.py",
                    "server_max_concurrency": server_concurrency,
                    "audit_batch_delay_ms": args.audit_batch_delay_ms,
                    "job_batch_delay_ms": args.job_batch_delay_ms,
                    "audit_batch_delay_ms": args.audit_batch_delay_ms,
                },
                "aggregate": aggregate,
                "resource_metrics": {
                    "accounting": "5ms /proc process-tree cumulative-max; diagnostic, not cgroup v2",
                    "server_cpu_seconds": server_cpu_seconds,
                    "server_peak_rss_bytes": server_peak_rss_bytes,
                    "server_observed_process_count": server_observed_process_count,
                    "server_cpu_affinity": server_cpu_affinity,
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
                    "shared GitHub-hosted runner; no isolated cgroup CPU or memory claim",
                    "single E-009 process and one SQLite database",
                    "not a 10-repetition controlled cross-runtime capacity comparison",
                ],
            }
            rendered = json.dumps(summary, indent=2, sort_keys=True)
            print(rendered)
            if args.output:
                args.output.parent.mkdir(parents=True, exist_ok=True)
                args.output.write_text(rendered + "\n", encoding="utf-8")
            if failures:
                raise SystemExit(f"{len(failures)} of {len(all_results)} measured requests did not match expected status")
        finally:
            if "stop_cpu_monitor" in locals():
                stop_cpu_monitor.set()
            if "cpu_monitor" in locals():
                cpu_monitor.join()
            if process.poll() is None:
                process.send_signal(signal.SIGINT)
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()


if __name__ == "__main__":
    main()
