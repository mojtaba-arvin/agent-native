#!/usr/bin/env python3
"""Classify and evaluate task-acceptance workflow runs.

An acceptance-only PR is a negative baseline test: its script must fail on the
current base. The required GitHub check succeeds only when that expected
failure is observed. Implementation PRs must run the same script successfully.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def select_mode(context: dict[str, Any]) -> str:
    task_id = context.get("task_id")
    if not isinstance(task_id, str) or len(task_id) != 3 or not task_id.startswith("T") or not task_id[1:].isdigit():
        raise ValueError("Task ID must have the form Txx.")

    labels = set(context.get("issue_labels") or [])
    paths = context.get("changed_paths") or []
    expected_script = f"acceptance/{task_id}.sh"
    has_acceptance = bool(context.get("has_acceptance"))

    if paths == [expected_script]:
        if not has_acceptance:
            raise ValueError(f"{expected_script} is changed but is not present at the PR head.")
        return "expect-failure"

    if "kind:process" in labels and not has_acceptance:
        return "skip-process"

    if not has_acceptance:
        raise ValueError(f"Missing {expected_script}; only workflow/gate-maintenance process PRs may omit acceptance.")

    return "normal"


def evaluate_exit_status(mode: str, exit_code: int) -> int:
    if mode == "expect-failure":
        if exit_code == 0:
            print("Acceptance PR failed its baseline test: the script unexpectedly passed before implementation.")
            return 1
        print(f"Expected baseline failure observed (acceptance script exit code {exit_code}).")
        return 0
    if mode == "skip-process":
        print("Acceptance script skipped: kind:process maintenance issue has no task acceptance script.")
        return 0
    if mode == "normal":
        if exit_code == 0:
            print("Implementation acceptance passed.")
        else:
            print(f"Implementation acceptance failed (exit code {exit_code}).")
        return exit_code
    raise ValueError(f"Unknown acceptance mode: {mode}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--context-file", type=Path)
    parser.add_argument("--mode", choices=("expect-failure", "skip-process", "normal"))
    parser.add_argument("--exit-code", type=int)
    args = parser.parse_args()

    if args.context_file is not None:
        if args.mode is not None or args.exit_code is not None:
            parser.error("--context-file cannot be combined with --mode or --exit-code")
        context = json.loads(args.context_file.read_text(encoding="utf-8"))
        print(select_mode(context))
        return 0

    if args.mode is None or args.exit_code is None:
        parser.error("provide --context-file or both --mode and --exit-code")
    return evaluate_exit_status(args.mode, args.exit_code)


if __name__ == "__main__":
    raise SystemExit(main())
