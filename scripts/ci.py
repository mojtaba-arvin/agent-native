#!/usr/bin/env python3
"""Run deterministic fast CI suites with path-aware selection."""

from __future__ import annotations
import argparse
import concurrent.futures
import fnmatch
import os
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

@dataclass(frozen=True)
class Suite:
    name: str
    command: tuple[str, ...]
    paths: tuple[str, ...]

SUITES = (
    Suite("e001-prototype", ("python", "-m", "unittest", "discover", "-s", "experiments/e001/prototype", "-p", "test_*.py"), ("experiments/e001/**",)),
    Suite("e002-python", ("python", "-m", "unittest", "discover", "-s", "experiments/e002", "-p", "test_*.py"), ("experiments/e002/**",)),
    Suite("e003-semantics", ("python", "-m", "unittest", "discover", "-s", "experiments/e003", "-p", "test_*.py"), ("experiments/e003/**",)),
    Suite("e004-security", ("python", "-m", "unittest", "discover", "-s", "experiments/e004", "-p", "test_*.py"), ("experiments/e004/**",)),
    Suite("e005-interface", ("python", "-m", "unittest", "discover", "-s", "experiments/e005", "-p", "test_*.py"), ("experiments/e005/**",)),
    Suite("e006-durable", ("python", "-m", "unittest", "discover", "-s", "experiments/e006", "-p", "test_*.py"), ("experiments/e006/**",)),
    Suite("e007-corpus", ("python", "-m", "unittest", "discover", "-s", "experiments/e007", "-p", "test_*.py"), ("experiments/e007/**",)),
    Suite("e008-outbox", ("python", "-m", "unittest", "discover", "-s", "experiments/e008", "-p", "test_*.py"), ("experiments/e008/**",)),
    Suite("e009-kernel", ("python", "-m", "unittest", "discover", "-s", "experiments/e009", "-p", "test_*.py"), ("experiments/e009/**",)),
    Suite("e010-apply", ("python", "-m", "unittest", "discover", "-s", "experiments/e010", "-p", "test_*.py"), ("experiments/e010/**",)),
    Suite("e011-semantics", ("python", "-m", "unittest", "discover", "-s", "experiments/e011", "-p", "test_*.py"), ("experiments/e011/**",)),
    Suite("pilot-protocol", ("python", "-m", "unittest", "discover", "-s", "experiments/pilot", "-p", "test_*.py"), ("experiments/pilot/**",)),
)
DEPENDENCIES = {
    "experiments/e001/": {"e001-prototype", "pilot-protocol"},
    "experiments/e004/": {"e004-security", "e009-kernel"},
    "experiments/e005/": {"e005-interface", "pilot-protocol"},
    "experiments/e009/": {"e009-kernel", "e010-apply"},
}
ALL_NAMES = {suite.name for suite in SUITES}
ALWAYS_ALL = (".github/workflows/", "scripts/ci.py", "scripts/fast.sh")

def changed_paths(base: str) -> list[str]:
    result = subprocess.run(
        ["git", "diff", "--name-only", "--diff-filter=ACMRT", f"{base}...HEAD"],
        cwd=ROOT, text=True, capture_output=True, check=False,
    )
    if result.returncode:
        raise RuntimeError(f"cannot calculate changed paths against {base}: {result.stderr.strip()}")
    return [line for line in result.stdout.splitlines() if line]

def selected_suites(paths: list[str] | None) -> list[Suite]:
    if paths is None or any(path == marker or path.startswith(marker) for path in paths for marker in ALWAYS_ALL):
        return list(SUITES)
    selected: set[str] = set()
    for path in paths:
        for suite in SUITES:
            if any(fnmatch.fnmatch(path, pattern) for pattern in suite.paths):
                selected.add(suite.name)
        for prefix, dependents in DEPENDENCIES.items():
            if path.startswith(prefix):
                selected.update(dependents)
    return [suite for suite in SUITES if suite.name in selected]

def run_suite(suite: Suite) -> tuple[str, int, float, str]:
    started = time.monotonic()
    try:
        result = subprocess.run(
            suite.command, cwd=ROOT, text=True, stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT, timeout=45, check=False,
        )
        return suite.name, result.returncode, time.monotonic() - started, result.stdout
    except subprocess.TimeoutExpired as exc:
        output = exc.stdout or ""
        if isinstance(output, bytes):
            output = output.decode(errors="replace")
        return suite.name, 124, time.monotonic() - started, output + "\nTIMEOUT: suite exceeded 45 seconds\n"

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--layer", choices=("fast",), default="fast")
    parser.add_argument("--base", help="base git ref; only affected suites run")
    parser.add_argument("--jobs", type=int, default=min(12, os.cpu_count() or 2))
    args = parser.parse_args()
    paths = changed_paths(args.base) if args.base else None
    suites = selected_suites(paths)
    if paths is not None:
        print(f"Changed paths: {len(paths)}; selected suites: {', '.join(s.name for s in suites) or 'none'}", flush=True)
    if not suites:
        print("No fast test suites are affected by this change.")
        return 0
    started = time.monotonic()
    failures = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, min(args.jobs, len(suites)))) as pool:
        futures = [pool.submit(run_suite, suite) for suite in suites]
        for future in concurrent.futures.as_completed(futures):
            name, code, elapsed, output = future.result()
            print(f"\n===== {name}: {'PASS' if code == 0 else 'FAIL'} ({elapsed:.2f}s) =====", flush=True)
            if output:
                print(output, end="" if output.endswith("\n") else "\n", flush=True)
            if code:
                failures.append((name, code))
    elapsed = time.monotonic() - started
    print(f"\nFast CI: {len(suites) - len(failures)}/{len(suites)} suites passed in {elapsed:.2f}s")
    if failures:
        print("Failed suites: " + ", ".join(f"{name} (exit {code})" for name, code in failures))
        return 1
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
