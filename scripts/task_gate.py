#!/usr/bin/env python3
"""Task gate: mechanical rules every PR must satisfy before it can merge.

evaluate() is a pure function (unit tested). main() reads a JSON context file
passed via CLI argument, so it works without gh. The workflow gathers GitHub
data and writes that JSON.
"""
from __future__ import annotations

import argparse
import json
import os
import re
from typing import Any

TASK_LINE = re.compile(r"^Task:[ \t]*(T\d{2})[ \t]*$", re.M)
DEPENDS_LINE = re.compile(r"^Depends:[ \t]*(.*)$", re.M)
BUDGET_LINE = re.compile(r"^Attempt budget:[ \t]*(\d+)[ \t]*$", re.M)

PRODUCT_PREFIXES = (
    "src/", "services/", "schemas/", "runtime/", "crates/",
    "cmd/", "pkg/", "migrations/", "deploy/", "docker/",
)
KINDS = ("code", "docs", "decision", "research", "process")
DECISION_FILE = "DECISIONS.json"

KIND_RULES: dict[str, tuple[set[str], set[str]]] = {
    "code": ({"product", "test", "docs", "other"}, {"product", "test"}),
    "research": ({"research", "test", "ci", "docs"}, {"research", "test"}),
    "docs": ({"docs"}, {"docs"}),
    "decision": ({"docs", "state"}, {"state"}),
    "process": ({"ci", "test", "docs"}, {"ci", "test"}),
}


def classify(path: str) -> str:
    if path.startswith("acceptance/"):
        return "acceptance"
    if path == DECISION_FILE:
        return "state"
    if path.startswith("project-control/"):
        return "state"
    if path.startswith((".github/", "scripts/")):
        return "ci"
    name = path.rsplit("/", 1)[-1]
    if (
        path.startswith("tests/")
        or "/tests/" in path
        or name.startswith("test_")
        or name.endswith(("_test.go", "_test.py"))
    ):
        return "test"
    if path.startswith(PRODUCT_PREFIXES):
        return "product"
    if path.startswith(("experiments/", "research/")):
        return "research"
    if path.startswith("docs/") or name.endswith(".md"):
        return "docs"
    return "other"


def evaluate(ctx: dict[str, Any]) -> list[str]:
    files: list[str] = list(ctx.get("files") or [])
    match = TASK_LINE.search(ctx.get("body") or "")
    if not match:
        return ["PR description needs a line exactly like 'Task: T07'."]
    tid = match.group(1)
    task = ctx.get("task")
    if not task:
        return [f"No issue titled '[{tid}] ...' with label v1 exists."]
    if not files:
        return ["PR changes no files."]

    violations: list[str] = []
    labels = set(task.get("labels") or [])
    kinds = [label[5:] for label in labels if label.startswith("kind:")]
    kind = kinds[0] if len(kinds) == 1 and kinds[0] in KINDS else None
    if kind is None:
        violations.append(f"Issue [{tid}] needs exactly one label kind:{'|'.join(KINDS)}.")
    if task.get("state") != "open":
        violations.append(f"Issue [{tid}] is not open.")
    if "blocked" in labels:
        violations.append(f"Issue [{tid}] is labeled blocked; replan instead of retrying.")
    if not task.get("deps_closed", False):
        violations.append(f"Dependencies of [{tid}] are not all closed.")
    if task.get("attempts", 0) >= task.get("budget", 3):
        violations.append(f"Attempt budget of [{tid}] is exhausted; mark it blocked and replan.")
    if ctx.get("paused") and kind != "process":
        violations.append("New task work is paused (docs/state ratio too high); only kind:process PRs may merge.")

    classes = {path: classify(path) for path in files}

    for path, file_class in classes.items():
        if file_class == "state" and not (path == DECISION_FILE and kind == "decision"):
            violations.append(f"{path} is frozen legacy state; do not edit status or progress files.")

    if any(file_class == "acceptance" for file_class in classes.values()):
        stray = [path for path in files if not path.startswith(f"acceptance/{tid}")]
        if stray:
            violations.append(
                f"An acceptance PR may only touch acceptance/{tid}*; also touches: "
                + ", ".join(sorted(stray))
            )
        return violations

    if kind in KIND_RULES and kind != "process" and not ctx.get("acceptance_exists"):
        violations.append(f"acceptance/{tid}.sh must be merged to the base branch first, in its own PR.")

    if kind in KIND_RULES:
        allowed, required = KIND_RULES[kind]
        bad = sorted(path for path, file_class in classes.items() if file_class not in allowed and file_class != "state")
        if bad:
            violations.append(f"kind:{kind} may not change: " + ", ".join(bad))
        rules_only_process_pr = (
            kind == "process"
            and files == ["docs/V1_PLAN.md"]
        )
        if not (set(classes.values()) & required) and not rules_only_process_pr:
            violations.append(
                f"kind:{kind} PR must change at least one of: "
                + ", ".join(sorted(required)) + " files."
            )
    return violations


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--context", required=True, help="Path to JSON context file")
    args = parser.parse_args()
    with open(args.context, encoding="utf-8") as context_file:
        context = json.load(context_file)
    violations = evaluate(context)
    summary = "Task gate: PASS" if not violations else "Task gate: FAIL\n- " + "\n- ".join(violations)
    print(summary)
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_path:
        with open(summary_path, "a", encoding="utf-8") as summary_file:
            summary_file.write(summary + "\n")
    return 1 if violations else 0


if __name__ == "__main__":
    raise SystemExit(main())
