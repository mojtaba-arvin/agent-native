#!/usr/bin/env python3
"""Randomized repeated E-002 candidate runner; preserves all individual runs."""
from __future__ import annotations

import argparse
import json
import random
import shlex
import statistics
import subprocess
import sys
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--go-command", required=True)
    parser.add_argument("--rust-command", required=True)
    parser.add_argument("--wasi-command", required=True)
    parser.add_argument("--go-cwd", default="experiments/e002/go")
    parser.add_argument("--rust-cwd", default="experiments/e002/rust")
    parser.add_argument("--wasi-cwd", default="experiments/e002/wasi-p2")
    parser.add_argument("--requests", type=int, default=5000)
    parser.add_argument("--concurrency", type=int, default=64)
    parser.add_argument("--warmup", type=int, default=250)
    parser.add_argument("--repetitions", type=int, default=10)
    parser.add_argument("--seed", type=int, default=20261116)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    if min(args.requests, args.concurrency, args.repetitions) < 1 or args.warmup < 0:
        parser.error("requests, concurrency, repetitions must be positive; warmup non-negative")

    root = Path(args.output)
    root.mkdir(parents=True, exist_ok=True)
    candidates = [
        {"id": "go-net-http", "command": args.go_command, "cwd": args.go_cwd},
        {"id": "rust-tokio-hyper", "command": args.rust_command, "cwd": args.rust_cwd},
        {"id": "wasi-p2-wasmtime-50.0.1", "command": args.wasi_command, "cwd": args.wasi_cwd},
    ]
    rng = random.Random(args.seed)
    runs: list[dict] = []
    benchmark_script = Path(__file__).with_name("benchmark.py")

    for repetition in range(1, args.repetitions + 1):
        order = candidates.copy()
        rng.shuffle(order)
        for position, candidate in enumerate(order, start=1):
            prefix = root / candidate["id"] / f"rep-{repetition:02d}"
            command = [
                sys.executable, str(benchmark_script),
                "--command", candidate["command"],
                "--cwd", candidate["cwd"],
                "--requests", str(args.requests),
                "--concurrency", str(args.concurrency),
                "--warmup", str(args.warmup),
                "--label", candidate["id"],
                "--output", str(prefix),
            ]
            completed = subprocess.run(command, text=True, capture_output=True)
            record = {
                "candidate": candidate["id"],
                "repetition": repetition,
                "order_position": position,
                "seed": args.seed,
                "exit_code": completed.returncode,
                "stdout": completed.stdout[-4000:],
                "stderr": completed.stderr[-4000:],
                "summary_path": str(prefix.with_suffix(".json")),
                "raw_path": str(prefix.with_suffix(".jsonl")),
            }
            if completed.returncode == 0 and prefix.with_suffix(".json").exists():
                record["summary"] = json.loads(prefix.with_suffix(".json").read_text())
            runs.append(record)
            print(f"{repetition}/{args.repetitions} {candidate['id']}: exit={completed.returncode}")
            if completed.returncode != 0:
                (root / "matrix.json").write_text(
                    json.dumps({"seed": args.seed, "runs": runs}, indent=2) + "\n",
                    encoding="utf-8",
                )
                raise SystemExit(f"candidate failed; details retained under {prefix}")

    aggregate = {}
    for candidate in candidates:
        samples = [
            run["summary"] for run in runs
            if run["candidate"] == candidate["id"] and "summary" in run
        ]
        aggregate[candidate["id"]] = {
            "successful_repetitions": len(samples),
            "median_throughput_rps": statistics.median(
                item["throughput_requests_per_second"] for item in samples
            ) if samples else None,
            "median_p50_ms": statistics.median(
                item["latency_ms"]["p50"] for item in samples
            ) if samples else None,
            "median_p95_ms": statistics.median(
                item["latency_ms"]["p95"] for item in samples
            ) if samples else None,
            "median_p99_ms": statistics.median(
                item["latency_ms"]["p99"] for item in samples
            ) if samples else None,
        }

    result = {
        "seed": args.seed,
        "requests_per_run": args.requests,
        "concurrency": args.concurrency,
        "warmup": args.warmup,
        "repetitions_per_candidate": args.repetitions,
        "randomized_order": True,
        "aggregate": aggregate,
        "runs": runs,
        "interpretation": "Descriptive medians only; no confidence intervals or performance decision.",
    }
    (root / "matrix.json").write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(aggregate, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
