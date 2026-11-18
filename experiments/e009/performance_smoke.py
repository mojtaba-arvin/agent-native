#!/usr/bin/env python3
"""Repeatable end-to-end load smoke for the E-009 durable HTTP kernel.

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
import signal
import statistics
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path


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


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--requests", type=int, default=1000)
    parser.add_argument("--concurrency", type=int, default=32)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.requests < 100 or args.concurrency < 1 or args.concurrency > 64:
        parser.error("requests must be >=100 and concurrency must be 1..64")

    token = "e009-performance-smoke-token-" + uuid.uuid4().hex
    env = dict(os.environ, AGENT_NATIVE_DEMO_TOKEN=token)
    with tempfile.TemporaryDirectory(prefix="e009-perf-") as temp:
        db = Path(temp) / "kernel.sqlite3"
        process = subprocess.Popen(
            [sys.executable, "experiments/e009/serve.py", "--database", str(db),
             "--port", "0", "--max-concurrency", str(args.concurrency)],
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
                    method, path, auth, body, key, expected = (
                        "GET", f"/items/{item_id}", token, None, None, 200)
                elif slot < 8:
                    method, path, auth, body, key, expected = (
                        "GET", f"/jobs/{job_id}", token, None, None, 200)
                elif slot == 8:
                    method, path, auth, body, key, expected = (
                        "POST", "/items/rebuild", token, {}, f"load-{index}-{uuid.uuid4().hex}", 202)
                else:
                    method, path, auth, body, key, expected = (
                        "GET", f"/items/{item_id}", None, None, None, 401)
                started = time.perf_counter()
                status, response = request(base, method, path, auth, body=body, key=key)
                elapsed_ms = (time.perf_counter() - started) * 1000
                return {"status": status, "expected": expected, "latency_ms": elapsed_ms,
                        "ok": status == expected, "response_bytes": len(response)}

            started = time.perf_counter()
            with concurrent.futures.ThreadPoolExecutor(max_workers=args.concurrency) as pool:
                results = list(pool.map(one, range(args.requests)))
            elapsed = time.perf_counter() - started
            latencies = [item["latency_ms"] for item in results]
            statuses = {}
            for item in results:
                statuses[str(item["status"])] = statuses.get(str(item["status"]), 0) + 1
            failures = [item for item in results if not item["ok"]]
            summary = {
                "schema_version": 1,
                "classification": "shared_runner_product_path_smoke_not_capacity_claim",
                "workload": {
                    "requests": args.requests, "concurrency": args.concurrency,
                    "mix": {"authorized_item_read": 0.6, "authorized_job_read": 0.2,
                            "durable_job_admission": 0.1, "unauthenticated_read": 0.1},
                    "database": "file-backed SQLite WAL via E-009 serve.py",
                    "server_max_concurrency": args.concurrency,
                },
                "result": {
                    "completed_requests": len(results), "failed_expectations": len(failures),
                    "status_counts": statuses, "elapsed_seconds": elapsed,
                    "throughput_requests_per_second": len(results) / elapsed,
                    "latency_ms": {
                        "p50": percentile(latencies, 0.50), "p95": percentile(latencies, 0.95),
                        "p99": percentile(latencies, 0.99), "max": max(latencies),
                        "mean": statistics.fmean(latencies),
                    },
                    "response_bytes_total": sum(item["response_bytes"] for item in results),
                },
                "limitations": [
                    "shared GitHub-hosted runner; no isolated cgroup CPU or memory claim",
                    "single E-009 process and one SQLite database",
                    "smoke result is not a 10-repetition controlled runtime comparison",
                ],
            }
            rendered = json.dumps(summary, indent=2, sort_keys=True)
            print(rendered)
            if args.output:
                args.output.parent.mkdir(parents=True, exist_ok=True)
                args.output.write_text(rendered + "\n", encoding="utf-8")
            if failures:
                raise SystemExit(f"{len(failures)} requests did not match expected status")
        finally:
            if process.poll() is None:
                process.send_signal(signal.SIGTERM)
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()


if __name__ == "__main__":
    main()
