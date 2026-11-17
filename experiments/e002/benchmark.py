#!/usr/bin/env python3
"""Repeatable black-box load runner for E-002 native candidates (stdlib only)."""
from __future__ import annotations

import argparse
import concurrent.futures
import json
import os
import signal
import subprocess
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path


BASE = "http://127.0.0.1:8080"


def request(path: str) -> tuple[int, bytes]:
    try:
        with urllib.request.urlopen(BASE + path, timeout=5) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as error:
        return error.code, error.read()


def valid_measurement_response(item: dict) -> bool:
    return (
        item.get("status") == 200
        and item.get("body") == "completed:0"
        and "error" in item
        and item["error"] is None
    )


def proc_sample(pid: int) -> tuple[float, int] | None:
    """Aggregate CPU time and RSS for the process and its descendants."""
    pending = [pid]
    seen: set[int] = set()
    cpu_seconds = 0.0
    rss_bytes = 0
    found = False
    while pending:
        current = pending.pop()
        if current in seen:
            continue
        seen.add(current)
        try:
            stat = Path(f"/proc/{current}/stat").read_text().split()
            cpu_ticks = int(stat[13]) + int(stat[14])
            rss_kib = 0
            for line in Path(f"/proc/{current}/status").read_text().splitlines():
                if line.startswith("VmRSS:"):
                    rss_kib = int(line.split()[1])
                    break
            cpu_seconds += cpu_ticks / os.sysconf("SC_CLK_TCK")
            rss_bytes += rss_kib * 1024
            found = True
            children = Path(f"/proc/{current}/task/{current}/children").read_text().split()
            pending.extend(int(child) for child in children)
        except (OSError, ValueError, IndexError):
            continue
    return (cpu_seconds, rss_bytes) if found else None


def percentile(values: list[float], percentile_value: float) -> float:
    ordered = sorted(values)
    if not ordered:
        return 0.0
    index = max(0, min(len(ordered) - 1, int((percentile_value / 100) * len(ordered) + 0.999999) - 1))
    return ordered[index]


def wait_ready(process: subprocess.Popen, timeout: float = 20) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f"candidate exited early with status {process.returncode}")
        try:
            status, body = request("/health")
            if status == 200 and body == b"ok":
                return
        except (OSError, TimeoutError):
            pass
        time.sleep(0.1)
    raise RuntimeError(f"candidate did not become healthy within {timeout}s")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--command", required=True)
    parser.add_argument("--cwd", required=True)
    parser.add_argument("--requests", type=int, default=5000)
    parser.add_argument("--concurrency", type=int, default=64)
    parser.add_argument("--warmup", type=int, default=250)
    parser.add_argument("--label", required=True)
    parser.add_argument("--output", required=True, help="output prefix, without extension")
    args = parser.parse_args()
    if min(args.requests, args.concurrency) < 1 or args.warmup < 0:
        parser.error("requests/concurrency must be positive and warmup non-negative")

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    process = subprocess.Popen(args.command.split(), cwd=Path(args.cwd), start_new_session=True)
    samples: list[tuple[float, int]] = []
    stop_monitor = threading.Event()

    def monitor() -> None:
        while not stop_monitor.is_set():
            sample = proc_sample(process.pid)
            if sample is not None:
                samples.append(sample)
            stop_monitor.wait(0.02)

    try:
        startup_started = time.perf_counter()
        wait_ready(process)
        startup_seconds = time.perf_counter() - startup_started
        with concurrent.futures.ThreadPoolExecutor(max_workers=args.concurrency) as pool:
            warmup_results = list(pool.map(lambda _: request("/work?ms=0"), range(args.warmup)))
            if any(status != 200 or body != b"completed:0" for status, body in warmup_results):
                raise RuntimeError("candidate failed one or more warm-up requests")

            raw: list[dict] = []
            start_cpu = proc_sample(process.pid)
            monitor_thread = threading.Thread(target=monitor, daemon=True)
            monitor_thread.start()
            start = time.perf_counter()

            def one(index: int) -> dict:
                began = time.perf_counter()
                try:
                    status, body = request("/work?ms=0")
                    return {
                        "index": index,
                        "status": status,
                        "latency_ms": (time.perf_counter() - began) * 1000,
                        "body": body.decode("utf-8", errors="replace"),
                        "error": None,
                    }
                except Exception as error:  # retained as raw failure data
                    return {
                        "index": index,
                        "status": None,
                        "latency_ms": (time.perf_counter() - began) * 1000,
                        "body": "",
                        "error": repr(error),
                    }

            raw = list(pool.map(one, range(args.requests)))
            elapsed = time.perf_counter() - start
            stop_monitor.set()
            monitor_thread.join(timeout=2)
            end_cpu = proc_sample(process.pid)

        latencies = [item["latency_ms"] for item in raw]
        status_counts: dict[str, int] = {}
        for item in raw:
            key = str(item["status"]) if item["status"] is not None else "error"
            status_counts[key] = status_counts.get(key, 0) + 1

        cpu_seconds = None
        if start_cpu and end_cpu:
            cpu_seconds = max(0.0, end_cpu[0] - start_cpu[0])
        peak_rss = max((sample[1] for sample in samples), default=None)
        failed_responses = sum(not valid_measurement_response(item) for item in raw)
        process_alive_after_load = process.poll() is None
        functional_success = failed_responses == 0 and process_alive_after_load
        summary = {
            "label": args.label,
            "command": args.command,
            "requests": args.requests,
            "concurrency": args.concurrency,
            "warmup": args.warmup,
            "elapsed_seconds": elapsed,
            "startup_seconds": startup_seconds,
            "throughput_requests_per_second": args.requests / elapsed,
            "latency_ms": {
                "p50": percentile(latencies, 50),
                "p95": percentile(latencies, 95),
                "p99": percentile(latencies, 99),
                "max": max(latencies, default=0),
            },
            "status_counts": status_counts,
            "cpu_seconds": cpu_seconds,
            "peak_rss_bytes": peak_rss,
            "process_alive_after_load": process_alive_after_load,
            "failed_response_count": failed_responses,
            "functional_success": functional_success,
            "measurement_note": "single run; not a statistically sufficient performance conclusion",
        }
        with output.with_suffix(".jsonl").open("w", encoding="utf-8") as handle:
            for item in raw:
                handle.write(json.dumps(item, sort_keys=True) + "\n")
        output.with_suffix(".json").write_text(
            json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        print(json.dumps(summary, indent=2, sort_keys=True))
        if not functional_success:
            return 2
    finally:
        stop_monitor.set()
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.wait()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
