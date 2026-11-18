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
    Suite("e001-prototype", (sys.executable, "-m", "unittest", "discover", "-s", "experiments/e001/prototype", "-p", "test*.py"), ("experiments/e001/**",)),
    Suite("e002-python", (sys.executable, "-m", "unittest", "discover", "-s", "experiments/e002", "-p", "test*.py"), ("experiments/e002/**",)),
    Suite("e003-semantics", (sys.executable, "-m", "unittest", "discover", "-s", "experiments/e003", "-p", "test*.py"), ("experiments/e003/**",)),
    Suite("e004-security", (sys.executable, "-m", "unittest", "discover", "-s", "experiments/e004", "-p", "test*.py"), ("experiments/e004/**",)),
    Suite("e005-interface", (sys.executable, "-m", "unittest", "discover", "-s", "experiments/e005", "-p", "test*.py"), ("experiments/e005/**",)),
    Suite("e006-durable", (sys.executable, "-m", "unittest", "discover", "-s", "experiments/e006", "-p", "test*.py"), ("experiments/e006/**",)),
    Suite("e007-corpus", (sys.executable, "-m", "unittest", "discover", "-s", "experiments/e007", "-p", "test*.py"), ("experiments/e007/**",)),
    Suite("e008-outbox", (sys.executable, "-m", "unittest", "discover", "-s", "experiments/e008", "-p", "test*.py"), ("experiments/e008/**",)),
    Suite("e009-kernel", (sys.executable, "-m", "unittest", "discover", "-s", "experiments/e009", "-p", "test*.py"), ("experiments/e009/**",)),
    Suite("e010-apply", (sys.executable, "-m", "unittest", "discover", "-s", "experiments/e010", "-p", "test*.py"), ("experiments/e010/**",)),
    Suite("e011-semantics", (sys.executable, "-m", "unittest", "discover", "-s", "experiments/e011", "-p", "test*.py"), ("experiments/e011/**",)),
    Suite("pilot-protocol", (sys.executable, "-m", "unittest", "discover", "-s", "experiments/pilot", "-p", "test*.py"), ("experiments/pilot/**",)),
    Suite("project-control", (sys.executable, "project_control.py", "validate"), ("project-control/**", "project_control.py")),
    Suite("ci-runner", (sys.executable, "-m", "unittest", "discover", "-s", "scripts", "-p", "test*.py"), ("scripts/**",)),
)
DEPENDENCIES = {
    "experiments/e001/": {"e001-prototype", "pilot-protocol"},
    "experiments/e004/": {"e004-security", "e009-kernel"},
    "experiments/e005/": {"e005-interface", "pilot-protocol"},
    "experiments/e009/": {"e009-kernel", "e010-apply"},
}
ALWAYS_ALL = (".github/workflows/", "scripts/ci.py", "scripts/fast.sh")

def changed_paths(base: str) -> list[str]:
    result = subprocess.run(
        ["git", "diff", "--name-only", "--no-renames", "--diff-filter=ACMRTD", f"{base}...HEAD"],
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

PRECHECKS = {
    "e002-python": ((sys.executable, "-m", "py_compile",
        "experiments/e002/conformance.py", "experiments/e002/benchmark.py",
        "experiments/e002/run_matrix.py", "experiments/e002/measure_artifacts.py"),),
    "e009-kernel": ((sys.executable, "-m", "py_compile",
        "experiments/e009/serve.py", "experiments/e009/performance_smoke.py"),),
    "e011-semantics": ((sys.executable, "-m", "py_compile",
        "experiments/e011/semantics.py", "experiments/e011/test_semantics.py"),),
    "project-control": ((sys.executable, "project_control.py", "status"),
        (sys.executable, "project_control.py", "self-test")),
}

def run_suite(suite: Suite) -> tuple[str, int, float, str]:
    started = time.monotonic()
    output = []
    commands = (*PRECHECKS.get(suite.name, ()), suite.command)
    try:
        for command in commands:
            result = subprocess.run(
                command, cwd=ROOT, text=True, stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT, timeout=45, check=False,
            )
            output.append(result.stdout)
            if result.returncode:
                return suite.name, result.returncode, time.monotonic() - started, "\n".join(output)
        if suite.name == "e001-prototype":
            command = (sys.executable, "experiments/e001/prototype/agent_native.py",
                       "experiments/e001/examples/catalog.an")
            first = subprocess.run(command, cwd=ROOT, capture_output=True, check=True, timeout=45)
            second = subprocess.run(command, cwd=ROOT, capture_output=True, check=True, timeout=45)
            if first.stdout != second.stdout:
                return suite.name, 1, time.monotonic() - started, "E-001 CLI output is not deterministic\n"
            output.append("E-001 CLI output determinism: PASS\n")
        return suite.name, 0, time.monotonic() - started, "\n".join(output)
    except subprocess.TimeoutExpired as exc:
        detail = exc.stdout or ""
        if isinstance(detail, bytes):
            detail = detail.decode(errors="replace")
        return suite.name, 124, time.monotonic() - started, "\n".join(output) + detail + "\nTIMEOUT: command exceeded 45 seconds\n"
    except subprocess.CalledProcessError as exc:
        return suite.name, exc.returncode, time.monotonic() - started, "\n".join(output) + (exc.stderr or "")

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--layer", choices=("fast",), default="fast")
    parser.add_argument("--base", help="base git ref; only affected suites run")
    parser.add_argument("--jobs", type=int, default=min(8, os.cpu_count() or 2))
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
