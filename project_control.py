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
        if task.get("status") in {"ready", "in_progress"}:
            execution = task.get("execution")
            if not isinstance(execution, dict) or not all(
                isinstance(execution.get(key), str) and execution[key].strip()
                for key in ("branch", "base_branch", "integration_owner")
            ):
                errors.append(f"{tid}: executable task requires branch, base_branch, and integration_owner")
            elif execution["branch"] == execution["base_branch"]:
                errors.append(f"{tid}: execution branch must differ from base branch")

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
    workstreams = state.get("active_workstreams")
    if workstreams is not None:
        if not isinstance(workstreams, list):
            errors.append("state.active_workstreams must be an array")
        else:
            workstream_ids = [item.get("task_id") for item in workstreams if isinstance(item, dict)]
            workstream_branches = [item.get("branch") for item in workstreams if isinstance(item, dict)]
            if len(workstream_ids) != len(set(workstream_ids)) or set(workstream_ids) != set(state.get("active_task_ids", [])):
                errors.append("state.active_workstreams must map every active task exactly once")
            if len(workstream_branches) != len(set(workstream_branches)):
                errors.append("state.active_workstreams contains duplicate branches")
            for item in workstreams:
                if not isinstance(item, dict) or not all(
                    isinstance(item.get(key), str) and item[key].strip()
                    for key in ("task_id", "branch", "base_branch", "integration_owner")
                ):
                    errors.append("state.active_workstreams entries require task_id, branch, base_branch, and integration_owner")
                elif item["branch"] == item["base_branch"]:
                    errors.append("state.active_workstreams branch must differ from base_branch")
                else:
                    task = next((candidate for candidate in tasks if candidate.get("id") == item["task_id"]), None)
                    execution = task.get("execution") if isinstance(task, dict) else None
                    if not isinstance(execution, dict) or any(
                        execution.get(key) != item.get(key)
                        for key in ("branch", "base_branch", "integration_owner")
                    ):
                        errors.append(f"state.active_workstreams ownership does not match task contract: {item['task_id']}")

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
        elif event.get("kind") == "task_attempt":
            if event.get("outcome") not in {"failed", "no_progress", "progress", "completed"}:
                errors.append(f"RUN_LEDGER.jsonl:{line_no}: invalid task_attempt outcome")
            if event.get("outcome") == "failed" and (
                not isinstance(event.get("failure_signature"), str) or not event["failure_signature"].strip()
            ):
                errors.append(f"RUN_LEDGER.jsonl:{line_no}: failed task_attempt requires failure_signature")

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


def build_resume_checkpoint(
    docs: dict[str, dict[str, Any]], handoff_text: str
) -> dict[str, Any]:
    """Build a stateless resume checkpoint from committed repository state."""
    state = docs["state"]
    tasks = docs["tasks"].get("tasks", [])
    blockers = docs["blockers"].get("blockers", [])
    by_id = {task.get("id"): task for task in tasks if isinstance(task, dict)}
    active_ids = state.get("active_task_ids", [])
    limit = state.get("wip_limit", 0)
    if not isinstance(active_ids, list) or len(active_ids) > limit:
        raise ControlPlaneError("active task set exceeds the configured WIP limit")
    if not isinstance(handoff_text, str) or "## Resume protocol" not in handoff_text:
        raise ControlPlaneError("HANDOFF.md is missing its resume protocol")
    active = []
    for task_id in active_ids:
        task = by_id.get(task_id)
        if task is None:
            raise ControlPlaneError(f"active task does not exist: {task_id}")
        if task.get("status") not in {"ready", "in_progress"}:
            raise ControlPlaneError(f"active task is not executable: {task_id}")
        unsatisfied = [
            dependency for dependency in task.get("depends_on", [])
            if by_id.get(dependency, {}).get("status") != "complete"
        ]
        if unsatisfied:
            raise ControlPlaneError(
                f"active task {task_id} has incomplete dependencies: {', '.join(unsatisfied)}"
            )
        active.append({
            "id": task_id,
            "title": task.get("title"),
            "status": task.get("status"),
            "depends_on": task.get("depends_on", []),
            "acceptance": task.get("acceptance", []),
            "execution": task.get("execution"),
        })
    return {
        "schema_version": 1,
        "status": "ready",
        "active_branch": state.get("active_branch"),
        "baseline_branch": state.get("baseline_branch"),
        "baseline_commit": state.get("baseline_commit"),
        "current_milestone": state.get("current_milestone"),
        "active_tasks": active,
        "wip_limit": limit,
        "next_action": state.get("next_action"),
        "open_blockers": [
            {
                "id": item.get("id"),
                "title": item.get("title"),
                "next_step": item.get("next_step"),
            }
            for item in blockers if item.get("status") == "open"
        ],
    }


def command_resume() -> int:
    """Print a machine-readable checkpoint sufficient for a fresh agent handoff."""
    try:
        docs, ledger = load_documents()
        errors = validate_documents(docs, ledger)
        if errors:
            raise ControlPlaneError("control-plane validation failed: " + "; ".join(errors))
        handoff = (CONTROL / "HANDOFF.md").read_text(encoding="utf-8")
        checkpoint = build_resume_checkpoint(docs, handoff)
    except (ControlPlaneError, OSError) as exc:
        print(json.dumps({"status": "blocked", "error": str(exc)}, sort_keys=True), file=sys.stderr)
        return 1
    print(json.dumps(checkpoint, ensure_ascii=False, sort_keys=True, indent=2))
    return 0




def _task_attempt_streaks(ledger_text: str, task_id: str) -> tuple[int, int, str | None]:
    """Return unchanged-failure and no-progress streaks from explicit task attempts."""
    unchanged = 0
    no_progress = 0
    last_signature: str | None = None
    for line in ledger_text.splitlines():
        if not line.strip():
            continue
        event = json.loads(line)
        if not isinstance(event, dict) or event.get("kind") != "task_attempt" or event.get("task_id") != task_id:
            continue
        outcome = event.get("outcome")
        if outcome == "failed":
            signature = event.get("failure_signature")
            if unchanged and signature == last_signature:
                unchanged += 1
            else:
                unchanged = 1
            no_progress = 0
            last_signature = signature
        elif outcome == "no_progress":
            no_progress += 1
            unchanged = 0
            last_signature = None
        else:
            unchanged = 0
            no_progress = 0
            last_signature = None
    return unchanged, no_progress, last_signature


def build_schedule_plan(docs: dict[str, dict[str, Any]], ledger_text: str) -> dict[str, Any]:
    """Select only dependency-ready work with explicit branch/integration ownership."""
    state = docs["state"]
    tasks = docs["tasks"].get("tasks", [])
    milestones = {item["id"]: item for item in docs["roadmap"].get("milestones", [])}
    by_id = {task["id"]: task for task in tasks}
    active_ids = state.get("active_task_ids", [])
    limit = state.get("wip_limit", 0)
    slots = max(0, limit - len(active_ids))
    recovery = docs["policy"]["recovery"]
    unchanged_limit = recovery.get("unchanged_failure_limit", 2)
    no_progress_limit = recovery.get("no_progress_attempt_limit", 3)

    replan_required: list[dict[str, Any]] = []
    candidates: list[dict[str, Any]] = []
    deferred: list[dict[str, str]] = []
    for task in sorted(tasks, key=lambda item: (item.get("priority", 999), item["id"])):
        task_id = task["id"]
        if task_id in active_ids or task.get("status") in {"complete", "cancelled", "blocked", "in_progress"}:
            continue
        unchanged, no_progress, signature = _task_attempt_streaks(ledger_text, task_id)
        if unchanged >= unchanged_limit or no_progress >= no_progress_limit:
            replan_required.append({
                "task_id": task_id,
                "reason": "unchanged_failure_limit" if unchanged >= unchanged_limit else "no_progress_attempt_limit",
                "unchanged_failure_streak": unchanged,
                "no_progress_streak": no_progress,
                "failure_signature": signature,
                "required_action": "stop_retries_record_root_cause_and_replan",
            })
            continue
        unsatisfied = [
            dependency for dependency in task.get("depends_on", [])
            if by_id.get(dependency, {}).get("status") != "complete"
        ]
        if unsatisfied:
            deferred.append({"task_id": task_id, "reason": "dependencies_incomplete:" + ",".join(unsatisfied)})
            continue
        milestone = milestones.get(task.get("milestone"), {})
        if milestone.get("status") not in {"ready", "in_progress"}:
            deferred.append({"task_id": task_id, "reason": "milestone_not_ready"})
            continue
        execution = task.get("execution")
        if not isinstance(execution, dict) or not all(
            isinstance(execution.get(key), str) and execution[key].strip()
            for key in ("branch", "base_branch", "integration_owner")
        ):
            deferred.append({"task_id": task_id, "reason": "execution_metadata_missing"})
            continue
        if execution["branch"] == execution["base_branch"]:
            deferred.append({"task_id": task_id, "reason": "working_branch_must_differ_from_base"})
            continue
        occupied_branches = {
            item.get("branch") for item in state.get("active_workstreams", [])
            if isinstance(item, dict) and isinstance(item.get("branch"), str)
        }
        if execution["branch"] in occupied_branches:
            deferred.append({"task_id": task_id, "reason": "working_branch_already_active"})
            continue
        if any(item["execution"]["branch"] == execution["branch"] for item in candidates):
            deferred.append({"task_id": task_id, "reason": "duplicate_working_branch"})
            continue
        candidates.append({
            "id": task_id,
            "title": task.get("title"),
            "milestone": task.get("milestone"),
            "priority": task.get("priority", 999),
            "depends_on": task.get("depends_on", []),
            "execution": execution,
            "acceptance": task.get("acceptance", []),
        })
    return {
        "schema_version": 1,
        "status": "ready",
        "wip_limit": limit,
        "active_task_ids": active_ids,
        "active_workstreams": state.get("active_workstreams", []),
        "available_slots": slots,
        "selected_tasks": candidates[:slots],
        "replan_required": replan_required,
        "deferred_tasks": deferred,
        "mutates_repository_state": False,
        "next_step": "Record a task_attempt event before retrying; update task status and STATE.json in a reviewed branch when work is accepted.",
    }


def command_schedule() -> int:
    """Print a deterministic ready-work and recovery plan without mutating state."""
    try:
        docs, ledger = load_documents()
        errors = validate_documents(docs, ledger)
        if errors:
            raise ControlPlaneError("control-plane validation failed: " + "; ".join(errors))
        plan = build_schedule_plan(docs, ledger)
    except (ControlPlaneError, OSError, json.JSONDecodeError) as exc:
        print(json.dumps({"status": "blocked", "error": str(exc)}, sort_keys=True), file=sys.stderr)
        return 1
    print(json.dumps(plan, ensure_ascii=False, sort_keys=True, indent=2))
    return 0

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
    parser.add_argument("command", choices=("validate", "status", "self-test", "resume", "schedule"))
    args = parser.parse_args()
    if args.command == "validate":
        return command_validate()
    if args.command == "status":
        return command_status()
    if args.command == "resume":
        return command_resume()
    if args.command == "schedule":
        return command_schedule()
    return command_self_test()


if __name__ == "__main__":
    raise SystemExit(main())
