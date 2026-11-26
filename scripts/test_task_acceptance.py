import unittest

from task_acceptance import evaluate_exit_status, select_mode


class TaskAcceptanceTests(unittest.TestCase):
    def context(self, *, labels=("v1", "kind:code"), paths=("src/runtime.py",), has_acceptance=True):
        return {
            "task_id": "T07",
            "issue_labels": list(labels),
            "changed_paths": list(paths),
            "has_acceptance": has_acceptance,
        }


    def research_context(self, *, labels=("kind:research",), state="open",
                         has_goal=True, has_acceptance=True,
                         paths=("experiments/e007/m3_alt_model_cohort.py",
                                "experiments/e007/test_m3_alt_model_cohort.py",
                                "research/M3_007_ALTERNATIVE_COHORT.md")):
        return {
            "task_id": None,
            "research_issue": {
                "number": 290,
                "state": state,
                "labels": list(labels),
                "has_goal": has_goal,
                "has_acceptance": has_acceptance,
            },
            "changed_paths": list(paths),
        }

    def test_research_issue_selects_test_backed_research_ci_mode(self):
        self.assertEqual(select_mode(self.research_context()), "research-ci")

    def test_research_issue_requires_open_unblocked_research_label(self):
        with self.assertRaisesRegex(ValueError, "open"):
            select_mode(self.research_context(state="closed"))
        with self.assertRaisesRegex(ValueError, "kind:research"):
            select_mode(self.research_context(labels=("kind:docs",)))
        with self.assertRaisesRegex(ValueError, "kind:research"):
            select_mode(self.research_context(labels=("kind:research", "kind:docs")))
        with self.assertRaisesRegex(ValueError, "kind:research"):
            select_mode(self.research_context(labels=("kind:research", "blocked")))

    def test_research_issue_requires_goal_and_acceptance(self):
        with self.assertRaisesRegex(ValueError, "Goal and Acceptance"):
            select_mode(self.research_context(has_acceptance=False))

    def test_research_issue_requires_research_and_test_files(self):
        with self.assertRaisesRegex(ValueError, "research artifacts"):
            select_mode(self.research_context(paths=("tests/test_only.py",)))
        with self.assertRaisesRegex(ValueError, "test file"):
            select_mode(self.research_context(paths=("research/only.md",)))

    def test_research_issue_rejects_product_and_frozen_state_paths(self):
        with self.assertRaisesRegex(ValueError, "non-research paths"):
            select_mode(self.research_context(paths=("src/agent_native/runtime.py",
                                                     "experiments/e007/test_x.py")))
        with self.assertRaisesRegex(ValueError, "frozen project state"):
            select_mode(self.research_context(paths=("experiments/e007/test_x.py",
                                                     "project-control/HANDOFF.md")))

    def test_research_ci_exit_status_is_the_acceptance_result(self):
        self.assertEqual(evaluate_exit_status("research-ci", 0), 0)
        self.assertEqual(evaluate_exit_status("research-ci", 3), 3)

    def test_acceptance_only_pr_is_expected_failure_mode(self):
        ctx = self.context(paths=("acceptance/T07.sh",))
        self.assertEqual(select_mode(ctx), "expect-failure")

    def test_acceptance_only_pr_requires_script_at_head(self):
        ctx = self.context(paths=("acceptance/T07.sh",), has_acceptance=False)
        with self.assertRaisesRegex(ValueError, "not present"):
            select_mode(ctx)

    def test_process_maintenance_can_omit_acceptance(self):
        ctx = self.context(labels=("v1", "kind:process"), has_acceptance=False)
        self.assertEqual(select_mode(ctx), "skip-process")

    def test_non_process_pr_cannot_omit_acceptance(self):
        ctx = self.context(has_acceptance=False)
        with self.assertRaisesRegex(ValueError, "Missing acceptance/T07.sh"):
            select_mode(ctx)

    def test_implementation_pr_uses_normal_mode(self):
        self.assertEqual(select_mode(self.context()), "normal")

    def test_expected_failure_is_a_successful_required_check(self):
        self.assertEqual(evaluate_exit_status("expect-failure", 1), 0)
        self.assertEqual(evaluate_exit_status("expect-failure", 0), 1)

    def test_normal_mode_preserves_script_exit_code(self):
        self.assertEqual(evaluate_exit_status("normal", 0), 0)
        self.assertEqual(evaluate_exit_status("normal", 9), 9)

    def test_process_skip_is_successful(self):
        self.assertEqual(evaluate_exit_status("skip-process", 0), 0)

    def test_exact_acceptance_path_is_required_for_negative_mode(self):
        ctx = self.context(paths=("acceptance/T07.sh", "README.md"))
        self.assertEqual(select_mode(ctx), "normal")


if __name__ == "__main__":
    unittest.main()
