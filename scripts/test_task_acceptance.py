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
