import copy
import unittest

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
