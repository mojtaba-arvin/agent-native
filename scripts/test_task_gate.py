import copy
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import task_gate as gate

BASE_TASK = {
    "state": "open",
    "labels": ["v1", "kind:code"],
    "deps_closed": True,
    "attempts": 0,
    "budget": 3,
}


def make_context(files, kind="code", **overrides):
    task = copy.deepcopy(BASE_TASK)
    task["labels"] = ["v1", f"kind:{kind}"]
    context = {
        "files": files,
        "body": "Task: T07\n\nok",
        "task": task,
        "acceptance_exists": True,
        "paused": False,
    }
    for key, value in overrides.items():
        if key in task:
            task[key] = value
        else:
            context[key] = value
    return context



def make_research_context(files, **overrides):
    context = {
        "files": files,
        "body": "Research issue: #290\n\nM3-007 implementation",
        "research_issue": {
            "number": 290,
            "title": "[M3-007] Preregister alternative zero-cost CPU model feasibility cohort",
            "state": "open",
            "labels": ["kind:research"],
            "has_goal": True,
            "has_acceptance": True,
        },
        "paused": False,
    }
    context.update(overrides)
    return context


class TaskGateTests(unittest.TestCase):
    def assert_passes(self, context):
        self.assertEqual(gate.evaluate(context), [])

    def assert_fails(self, context, needle):
        violations = gate.evaluate(context)
        self.assertTrue(any(needle in item for item in violations), violations)

    def test_valid_code_pr(self):
        self.assert_passes(make_context(["src/agent_native/runtime.py", "tests/test_runtime.py"]))

    def test_missing_task_line(self):
        self.assert_fails({"files": ["src/a.py"], "body": "no task"}, "Task: T07")

    def test_unknown_task_issue(self):
        self.assert_fails({"files": ["src/a.py"], "body": "Task: T07", "task": None}, "No issue")

    def test_docs_only_pr_rejected_for_code_task(self):
        self.assert_fails(make_context(["README.md", "docs/status.md"]), "must change at least one")

    def test_status_files_frozen(self):
        self.assert_fails(make_context(["src/a.py", "project-control/HANDOFF.md"]), "frozen")
        self.assert_fails(make_context(["src/a.py", "project-control/TASKS.json"]), "frozen")

    def test_root_decision_registry_only_for_decision_kind(self):
        self.assert_passes(make_context(["DECISIONS.json", "docs/decision.md"], kind="decision"))
        self.assert_fails(make_context(["DECISIONS.json", "docs/decision.md"], kind="code"), "frozen")

    def test_project_control_decision_event_remains_frozen(self):
        self.assert_fails(
            make_context(
                ["project-control/DECISION_EVENTS.jsonl", "docs/decision.md"],
                kind="decision",
            ),
            "frozen",
        )

    def test_owner_authorized_t29_governance_pin_is_narrowly_allowed(self):
        self.assert_passes(
            make_context(
                [
                    "project-control/PREREGISTRATIONS.json",
                    "project-control/DECISION_EVENTS.jsonl",
                ],
                kind="process",
                body="Task: T29",
                owner_authorized_governance=True,
                acceptance_exists=False,
            )
        )

    def test_governance_pin_requires_exact_owner_authorization(self):
        context = make_context(
            [
                "project-control/PREREGISTRATIONS.json",
                "project-control/DECISION_EVENTS.jsonl",
            ],
            kind="process",
            body="Task: T29",
            owner_authorized_governance=False,
            acceptance_exists=False,
        )
        self.assert_fails(context, "frozen")

    def test_governance_pin_exception_rejects_extra_paths_and_other_tasks(self):
        paths = [
            "project-control/PREREGISTRATIONS.json",
            "project-control/DECISION_EVENTS.jsonl",
            ".github/workflows/task-gate.yml",
            "project-control/HANDOFF.md",
        ]
        context = make_context(
            paths,
            kind="process",
            body="Task: T29",
            owner_authorized_governance=True,
            acceptance_exists=False,
        )
        self.assert_fails(context, "frozen")
        other_task = make_context(
            paths[:2],
            kind="process",
            body="Task: T30",
            owner_authorized_governance=True,
            acceptance_exists=False,
        )
        self.assert_fails(other_task, "frozen")


    def test_owner_authorization_event_is_bound_to_exact_head_and_repo_owner(self):
        head = "a" * 40
        event = {
            "repository": {"owner": {"login": "mojtaba-arvin"}},
            "pull_request": {
                "user": {"login": "mojtaba-arvin"},
                "head": {"sha": head},
                "body": f"Task: T29\n\nGovernance authorization: {head}",
            },
        }
        with tempfile.TemporaryDirectory() as temporary:
            event_path = Path(temporary) / "event.json"
            with patch.dict(os.environ, {"GITHUB_EVENT_PATH": str(event_path)}):
                event_path.write_text(json.dumps(event), encoding="utf-8")
                self.assertTrue(gate.owner_authorized_governance_from_event())

                stale = copy.deepcopy(event)
                stale["pull_request"]["body"] = "Task: T29\n\nGovernance authorization: " + "b" * 40
                event_path.write_text(json.dumps(stale), encoding="utf-8")
                self.assertFalse(gate.owner_authorized_governance_from_event())

                non_owner = copy.deepcopy(event)
                non_owner["pull_request"]["user"]["login"] = "contributor"
                event_path.write_text(json.dumps(non_owner), encoding="utf-8")
                self.assertFalse(gate.owner_authorized_governance_from_event())

    def test_owner_authorization_event_fails_closed_when_missing_or_malformed(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertFalse(gate.owner_authorized_governance_from_event())
        with tempfile.TemporaryDirectory() as temporary:
            event_path = Path(temporary) / "event.json"
            event_path.write_text("{", encoding="utf-8")
            with patch.dict(os.environ, {"GITHUB_EVENT_PATH": str(event_path)}):
                self.assertFalse(gate.owner_authorized_governance_from_event())

    def test_acceptance_pr_must_be_separate(self):
        self.assert_passes(make_context(["acceptance/T07.sh"], acceptance_exists=False))
        self.assert_fails(make_context(["acceptance/T07.sh", "src/a.py"]), "only touch acceptance/T07")
        self.assert_fails(make_context(["acceptance/T08.sh"]), "only touch acceptance/T07")

    def test_implementation_needs_acceptance_first(self):
        self.assert_fails(make_context(["src/a.py"], acceptance_exists=False), "merged to the base branch first")

    def test_process_kind_exempt_from_acceptance(self):
        self.assert_passes(make_context([".github/workflows/x.yml", "scripts/task_gate.py"], kind="process", acceptance_exists=False))

    def test_process_rules_only_exception_is_exact(self):
        self.assert_passes(
            make_context(["docs/V1_PLAN.md"], kind="process", acceptance_exists=False)
        )
        self.assert_fails(
            make_context(
                ["docs/V1_PLAN.md", "README.md"],
                kind="process",
                acceptance_exists=False,
            ),
            "must change at least one",
        )

    def test_process_kind_cannot_touch_product(self):
        self.assert_fails(make_context([".github/workflows/x.yml", "src/a.py"], kind="process"), "may not change")

    def test_blocked_closed_deps_budget(self):
        self.assert_fails(make_context(["src/a.py"], state="closed"), "not open")
        self.assert_fails(make_context(["src/a.py"], labels=["v1", "kind:code", "blocked"]), "blocked")
        self.assert_fails(make_context(["src/a.py"], deps_closed=False), "Dependencies")
        self.assert_fails(make_context(["src/a.py"], attempts=3), "budget")

    def test_exactly_one_kind(self):
        self.assert_fails(make_context(["src/a.py"], labels=["v1"]), "exactly one label")
        self.assert_fails(make_context(["src/a.py"], labels=["v1", "kind:code", "kind:docs"]), "exactly one label")

    def test_paused_blocks_non_process(self):
        self.assert_fails(make_context(["src/a.py"], paused=True), "paused")
        self.assert_passes(make_context(["scripts/x.py"], kind="process", paused=True, acceptance_exists=False))

    def test_docs_kind_allows_docs_only(self):
        self.assert_passes(make_context(["docs/prd.md"], kind="docs"))
        self.assert_fails(make_context(["docs/prd.md", "src/a.py"], kind="docs"), "may not change")

    def test_empty_pr(self):
        self.assert_fails(make_context([]), "no files")


    def test_valid_research_issue_pr(self):
        self.assert_passes(make_research_context([
            "experiments/e007/m3_alt_model_cohort.py",
            "experiments/e007/test_m3_alt_model_cohort.py",
            ".github/workflows/m3-007-alternative-models.yml",
            "research/M3_007_ALTERNATIVE_COHORT.md",
        ]))

    def test_research_issue_requires_exact_reference_and_resolved_issue(self):
        self.assert_fails(
            {"files": ["research/a.md"], "body": "Research issue: #290", "research_issue": None},
            "could not be resolved",
        )
        self.assert_fails(
            make_research_context(["research/a.md"], body="Research issue: #0"),
            "Task: T07",
        )

    def test_research_issue_must_be_open_research_and_unblocked(self):
        context = make_research_context(["research/a.md"])
        context["research_issue"]["state"] = "closed"
        self.assert_fails(context, "not open")
        context = make_research_context(["research/a.md"])
        context["research_issue"]["labels"] = ["kind:docs"]
        self.assert_fails(context, "kind:research")
        context = make_research_context(["research/a.md"])
        context["research_issue"]["labels"] = ["kind:research", "blocked"]
        self.assert_fails(context, "labeled blocked")

    def test_research_issue_requires_goal_and_acceptance_sections(self):
        context = make_research_context(["research/a.md"])
        context["research_issue"]["has_acceptance"] = False
        self.assert_fails(context, "Goal and Acceptance")

    def test_research_issue_file_allowlist_and_evidence_requirements(self):
        self.assert_fails(make_research_context(["src/agent_native/runtime.py"]), "may not change")
        self.assert_fails(make_research_context(["research/a.md"]), "research or test")
        self.assert_fails(
            make_research_context(["experiments/a.py", "project-control/HANDOFF.md"]),
            "frozen legacy state",
        )

    def test_paused_state_blocks_research_issue_prs(self):
        self.assert_fails(make_research_context(["experiments/a.py"], paused=True), "paused")

    def test_v1_task_path_still_takes_precedence_and_requires_task_issue(self):
        context = make_context(["src/a.py"], body="Task: T07\nResearch issue: #290")
        self.assert_passes(context)

    def test_classify(self):
        self.assertEqual(gate.classify("scripts/test_x.py"), "ci")
        self.assertEqual(gate.classify("tests/a.py"), "test")
        self.assertEqual(gate.classify("src/a/test_b.py"), "test")
        self.assertEqual(gate.classify("services/x/service.an"), "product")
        self.assertEqual(gate.classify("experiments/e1/x.py"), "research")
        self.assertEqual(gate.classify("DECISIONS.json"), "state")
        self.assertEqual(gate.classify("README.md"), "docs")


if __name__ == "__main__":
    unittest.main()
