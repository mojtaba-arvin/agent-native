#!/usr/bin/env python3
"""Validate and inspect the repository's versioned project control plane.

Standard-library only. This tool validates structure and references; it cannot
attest that an evidence URL or a human review is truthful.
"""
from __future__ import annotations

import argparse
import copy
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
CONTROL = ROOT / "project-control"
FILES = {
    "roadmap": CONTROL / "ROADMAP.json",
    "tasks": CONTROL / "TASKS.json",
    "state": CONTROL / "STATE.json",
    "decisions": CONTROL / "DECISIONS.json",
    "blockers": CONTROL / "BLOCKERS.json",
    "progress": CONTROL / "PROGRESS.json",
    "policy": CONTROL / "POLICY.json",
}
STATUSES = {"pending", "ready", "in_progress", "blocked", "complete", "cancelled"}


class ControlPlaneError(ValueError):
    pass


def load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ControlPlaneError(f"missing required file: {path.relative_to(ROOT)}") from exc
    except json.JSONDecodeError as exc:
        raise ControlPlaneError(f"{path.relative_to(ROOT)}:{exc.lineno}:{exc.colno}: {exc.msg}") from exc
    if not isinstance(value, dict):
        raise ControlPlaneError(f"{path.relative_to(ROOT)} must contain a JSON object")
    return value


def validate_documents(docs: dict[str, dict[str, Any]], ledger_text: str = "") -> list[str]:
    errors: list[str] = []
    roadmap = docs["roadmap"]
    tasks_doc = docs["tasks"]
    state = docs["state"]
    decisions_doc = docs["decisions"]
    blockers_doc = docs["blockers"]
    progress = docs["progress"]
    policy = docs["policy"]

    milestones = roadmap.get("milestones")
    tasks = tasks_doc.get("tasks")
    decisions = decisions_doc.get("decisions")
    blockers = blockers_doc.get("blockers")
    if not isinstance(milestones, list) or not isinstance(tasks, list):
        return ["roadmap.milestones and tasks.tasks must be arrays"]
    if not isinstance(decisions, list) or not isinstance(blockers, list):
        return ["decisions.decisions and blockers.blockers must be arrays"]

    milestone_ids = [m.get("id") for m in milestones if isinstance(m, dict)]
    task_ids = [t.get("id") for t in tasks if isinstance(t, dict)]
    decision_ids = [d.get("id") for d in decisions if isinstance(d, dict)]
    blocker_ids = [b.get("id") for b in blockers if isinstance(b, dict)]
    for label, values in (("milestone", milestone_ids), ("task", task_ids),
                          ("decision", decision_ids), ("blocker", blocker_ids)):
        if len(values) != len(set(values)):
            errors.append(f"duplicate {label} IDs")

    milestone_set, task_set = set(milestone_ids), set(task_ids)
    for milestone in milestones:
        if not isinstance(milestone, dict):
            errors.append("each milestone must be an object")
            continue
        mid = milestone.get("id", "<unknown>")
        if milestone.get("status") not in STATUSES:
            errors.append(f"{mid}: invalid status")
        for dep in milestone.get("depends_on", []):
            if dep not in milestone_set:
                errors.append(f"{mid}: unknown milestone dependency {dep}")
        if not isinstance(milestone.get("exit_criteria"), list) or not milestone["exit_criteria"]:
            errors.append(f"{mid}: exit_criteria must be a non-empty array")

    graph: dict[str, list[str]] = {}
    for task in tasks:
        if not isinstance(task, dict):
            errors.append("each task must be an object")
            continue
        tid = task.get("id", "<unknown>")
        graph[tid] = task.get("depends_on", [])
        if task.get("status") not in STATUSES:
            errors.append(f"{tid}: invalid status")
        if task.get("milestone") not in milestone_set:
            errors.append(f"{tid}: unknown milestone {task.get('milestone')}")
        if not isinstance(task.get("acceptance"), list) or not task["acceptance"]:
            errors.append(f"{tid}: acceptance must be a non-empty array")
        if not isinstance(task.get("max_unchanged_retries"), int) or task["max_unchanged_retries"] < 0:
            errors.append(f"{tid}: max_unchanged_retries must be a non-negative integer")
        for dep in graph[tid]:
            if dep not in task_set:
                errors.append(f"{tid}: unknown task dependency {dep}")

    # Detect dependency cycles without recursion-depth dependence.
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(node: str) -> None:
        if node in visiting:
            errors.append(f"task dependency cycle includes {node}")
            return
        if node in visited:
            return
        visiting.add(node)
        for dep in graph.get(node, []):
            if dep in graph:
                visit(dep)
        visiting.remove(node)
        visited.add(node)

    for node in graph:
        visit(node)

    for task_id in state.get("active_task_ids", []):
        if task_id not in task_set:
            errors.append(f"state references unknown active task {task_id}")
    if state.get("current_milestone") not in milestone_set:
        errors.append("state.current_milestone references an unknown milestone")
    if state.get("wip_limit", 0) < len(state.get("active_task_ids", [])):
        errors.append("active task count exceeds state.wip_limit")

    progress_milestones = progress.get("milestones", {})
    for milestone in milestones:
        mid = milestone.get("id")
        record = progress_milestones.get(mid)
        if not isinstance(record, dict):
            errors.append(f"progress missing milestone {mid}")
            continue
        total = len(milestone.get("exit_criteria", []))
        if record.get("total_exit_criteria") != total:
            errors.append(f"progress {mid}: total_exit_criteria does not match roadmap")
        verified = record.get("verified_exit_criteria", [])
        if not isinstance(verified, list) or len(verified) > total:
            errors.append(f"progress {mid}: invalid verified_exit_criteria")

    for decision in decisions:
        if decision.get("status") not in {"observed", "supported", "hypothesis", "decision", "rejected"}:
            errors.append(f"{decision.get('id')}: invalid evidence/decision status")
        if not decision.get("date") or not decision.get("statement"):
            errors.append(f"{decision.get('id')}: date and statement are required")

    for line_no, line in enumerate(ledger_text.splitlines(), 1):
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError as exc:
            errors.append(f"RUN_LEDGER.jsonl:{line_no}: invalid JSON ({exc.msg})")
            continue
        required = {"event_id", "timestamp", "task_id", "kind", "outcome"}
        missing = required - set(event) if isinstance(event, dict) else required
        if missing:
            errors.append(f"RUN_LEDGER.jsonl:{line_no}: missing fields {', '.join(sorted(missing))}")
        elif event["task_id"] not in task_set:
            errors.append(f"RUN_LEDGER.jsonl:{line_no}: unknown task {event['task_id']}")

    if not isinstance(policy.get("autonomy"), dict) or not isinstance(policy.get("recovery"), dict):
        errors.append("policy must define autonomy and recovery objects")
    return errors


def load_documents() -> tuple[dict[str, dict[str, Any]], str]:
    docs = {name: load_json(path) for name, path in FILES.items()}
    ledger_path = CONTROL / "RUN_LEDGER.jsonl"
    try:
        ledger = ledger_path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise ControlPlaneError("missing required file: project-control/RUN_LEDGER.jsonl") from exc
    return docs, ledger


def command_validate() -> int:
    try:
        docs, ledger = load_documents()
        errors = validate_documents(docs, ledger)
    except ControlPlaneError as exc:
        print(f"INVALID: {exc}", file=sys.stderr)
        return 1
    if errors:
        print("INVALID project control plane:")
        for error in errors:
            print(f"- {error}")
        return 1
    print("VALID project control plane")
    print(f"Milestones: {len(docs['roadmap']['milestones'])}; tasks: {len(docs['tasks']['tasks'])}; "
          f"decisions: {len(docs['decisions']['decisions'])}; blockers: {len(docs['blockers']['blockers'])}")
    return 0


def command_status() -> int:
    try:
        docs, ledger = load_documents()
        errors = validate_documents(docs, ledger)
    except ControlPlaneError as exc:
        print(f"Cannot read project state: {exc}", file=sys.stderr)
        return 1
    if errors:
        print(f"Project state has {len(errors)} validation error(s); run 'validate'.")
    state = docs["state"]
    print(f"Branch: {state.get('active_branch', 'unknown')} (baseline: {state.get('baseline_branch', 'unknown')})")
    print(f"Milestone: {state.get('current_milestone', 'unknown')}")
    print(f"Active tasks: {', '.join(state.get('active_task_ids', [])) or 'none'}")
    for milestone in docs["roadmap"]["milestones"]:
        record = docs["progress"]["milestones"].get(milestone["id"], {})
        verified = len(record.get("verified_exit_criteria", []))
        total = record.get("total_exit_criteria", len(milestone.get("exit_criteria", [])))
        print(f"  {milestone['id']:>3}  {milestone['status']:<11} {verified}/{total} verified  {milestone['name']}")
    for task in sorted(docs["tasks"]["tasks"], key=lambda item: (item.get("priority", 999), item["id"])):
        print(f"  {task['id']:<9} {task['status']:<11} {task['title']}")
    print(f"Blockers: {sum(1 for item in docs['blockers']['blockers'] if item.get('status') == 'open')}")
    return 1 if errors else 0


def command_self_test() -> int:
    """Exercise representative negative cases without modifying repository files."""
    try:
        docs, ledger = load_documents()
    except ControlPlaneError as exc:
        print(f"SELF-TEST BLOCKED: {exc}", file=sys.stderr)
        return 1
    baseline = validate_documents(docs, ledger)
    if baseline:
        print("SELF-TEST BLOCKED: baseline state is invalid")
        for error in baseline:
            print(f"- {error}")
        return 1

    cases = []
    bad = copy.deepcopy(docs)
    bad["tasks"]["tasks"][0]["depends_on"] = ["TASK-DOES-NOT-EXIST"]
    cases.append(("unknown dependency", bad, ledger, "unknown task dependency"))
    bad = copy.deepcopy(docs)
    bad["tasks"]["tasks"][0]["status"] = "almost_done"
    cases.append(("invalid task status", bad, ledger, "invalid status"))
    bad = copy.deepcopy(docs)
    bad["tasks"]["tasks"][0]["depends_on"] = ["CP-002"]
    cases.append(("dependency cycle", bad, ledger, "dependency cycle"))
    cases.append(("malformed ledger event", docs, '{"event_id": "bad"}', "missing fields"))

    for name, candidate, candidate_ledger, expected in cases:
        found = validate_documents(candidate, candidate_ledger)
        if not any(expected in error for error in found):
            print(f"SELF-TEST FAIL: {name} was not rejected")
            return 1
        print(f"PASS: rejects {name}")
    print(f"SELF-TEST PASS: {len(cases)} negative cases")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("validate", "status", "self-test"))
    args = parser.parse_args()
    if args.command == "validate":
        return command_validate()
    if args.command == "status":
        return command_status()
    return command_self_test()


if __name__ == "__main__":
    raise SystemExit(main())
