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
PROCESS_SAMPLE_INTERVAL_SECONDS = 0.005


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


def parse_proc_stat(raw: str, clock_ticks: int) -> tuple[float, int]:
    """Return (CPU seconds, process start-time ticks) without splitting comm."""
    close = raw.rfind(")")
    if close < 0:
        raise ValueError("malformed_proc_stat_comm")
    fields = raw[close + 1 :].split()
    # fields[0] is proc stat field 3 (state); utime/stime are 14/15,
    # and starttime is 22. Index relative to field 3 is therefore 11/12/19.
    if len(fields) <= 19:
        raise ValueError("truncated_proc_stat")
    user_ticks = int(fields[11])
    system_ticks = int(fields[12])
    start_time_ticks = int(fields[19])
    return (user_ticks + system_ticks) / clock_ticks, start_time_ticks


def proc_tree_sample(
    pid: int,
    *,
    proc_root: str | Path = "/proc",
    clock_ticks: int | None = None,
) -> dict[tuple[int, int], tuple[float, int]]:
    """Snapshot visible process-tree members keyed by (PID, start-time ticks).

    The start-time component distinguishes ordinary PID reuse. Its clock-tick resolution is finite, so it is a practical guard rather than a mathematically unique process identifier.
    Children are enumerated for every thread because any thread may fork a child.
    """
    root = Path(proc_root)
    ticks_per_second = clock_ticks or os.sysconf("SC_CLK_TCK")
    pending = [pid]
    seen_pids: set[int] = set()
    snapshot: dict[tuple[int, int], tuple[float, int]] = {}

    while pending:
        current = pending.pop()
        if current in seen_pids:
            continue
        seen_pids.add(current)
        process_dir = root / str(current)
        try:
            cpu_seconds, start_ticks = parse_proc_stat(
                (process_dir / "stat").read_text(encoding="utf-8"),
                ticks_per_second,
            )
            rss_kib = 0
            for line in (process_dir / "status").read_text(encoding="utf-8").splitlines():
                if line.startswith("VmRSS:"):
                    rss_kib = int(line.split()[1])
                    break
            snapshot[(current, start_ticks)] = (cpu_seconds, rss_kib * 1024)

            task_root = process_dir / "task"
            for task in task_root.iterdir():
                try:
                    children = (task / "children").read_text(encoding="ascii").split()
                except (OSError, UnicodeError):
                    continue
                pending.extend(int(child) for child in children)
        except (OSError, ValueError, IndexError):
            # A process can exit between discovery and inspection. Its last
            # successful sample remains in the accumulator.
            continue

    return snapshot


class ProcessTreeCpuTracker:
    """Accumulate per-process CPU maxima so exited children remain accounted for."""

    def __init__(self) -> None:
        self._cpu_by_identity: dict[tuple[int, int], float] = {}
        self.peak_tree_rss_bytes = 0

    def observe(self, snapshot: dict[tuple[int, int], tuple[float, int]]) -> None:
        current_tree_rss = 0
        for identity, (cpu_seconds, rss_bytes) in snapshot.items():
            previous = self._cpu_by_identity.get(identity, 0.0)
            self._cpu_by_identity[identity] = max(previous, cpu_seconds)
            current_tree_rss += rss_bytes
        self.peak_tree_rss_bytes = max(self.peak_tree_rss_bytes, current_tree_rss)

    @property
    def total_cpu_seconds(self) -> float:
        return sum(self._cpu_by_identity.values())


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
    cpu_tracker = ProcessTreeCpuTracker()
    stop_monitor = threading.Event()

    try:
        startup_started = time.perf_counter()
        wait_ready(process)
        startup_seconds = time.perf_counter() - startup_started
        with concurrent.futures.ThreadPoolExecutor(max_workers=args.concurrency) as pool:
            warmup_results = list(pool.map(lambda _: request("/work?ms=0"), range(args.warmup)))
            if any(status != 200 or body != b"completed:0" for status, body in warmup_results):
                raise RuntimeError("candidate failed one or more warm-up requests")

            raw: list[dict] = []
            # Establish a cumulative CPU baseline after warm-up. The tracker
            # retains the last observed CPU for children that exit during load.
            cpu_tracker.observe(proc_tree_sample(process.pid))
            start_cpu_seconds = cpu_tracker.total_cpu_seconds

            def monitor() -> None:
                while not stop_monitor.is_set():
                    cpu_tracker.observe(proc_tree_sample(process.pid))
                    stop_monitor.wait(PROCESS_SAMPLE_INTERVAL_SECONDS)

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
            cpu_tracker.observe(proc_tree_sample(process.pid))

        latencies = [item["latency_ms"] for item in raw]
        status_counts: dict[str, int] = {}
        for item in raw:
            key = str(item["status"]) if item["status"] is not None else "error"
            status_counts[key] = status_counts.get(key, 0) + 1

        cpu_seconds = max(0.0, cpu_tracker.total_cpu_seconds - start_cpu_seconds)
        peak_rss = cpu_tracker.peak_tree_rss_bytes or None
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
            "measurement_note": (
                "Process-tree CPU is accumulated from 5 ms /proc samples keyed by PID and "
                "start-time; exited processes retain their last observed CPU. A child that "
                "starts and exits entirely between samples can still be missed. RSS is the "
                "peak sum of visible process-tree RSS samples. This is not cgroup accounting."
            ),
            "cpu_accounting": {
                "method": "sampled_process_tree_cumulative_max",
                "sample_interval_seconds": PROCESS_SAMPLE_INTERVAL_SECONDS,
                "identity": "pid_plus_proc_starttime_ticks",
                "limitations": [
                    "short-lived descendants entirely between samples may be missed",
                    "processes reparented before discovery may no longer be visible below the root",
                    "shared hosted-runner noise remains",
                    "not cgroup-level accounting",
                ],
            },
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
