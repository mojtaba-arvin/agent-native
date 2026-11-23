"""Regression tests for the path-aware fast-CI suite selector."""
from __future__ import annotations

import subprocess
import unittest
from pathlib import Path
from unittest.mock import patch

import ci


class ChangedPathTests(unittest.TestCase):
    def test_git_diff_includes_deleted_paths_and_disables_rename_collapse(self):
        completed = subprocess.CompletedProcess(args=[], returncode=0, stdout="experiments/e009/removed.py\n")
        with patch.object(ci.subprocess, "run", return_value=completed) as run:
            self.assertEqual(ci.changed_paths("base-sha"), ["experiments/e009/removed.py"])
        command = run.call_args.args[0]
        self.assertIn("--no-renames", command)
        self.assertIn("--diff-filter=ACMRTD", command)

    def test_git_diff_failure_is_not_silently_treated_as_no_changes(self):
        completed = subprocess.CompletedProcess(args=[], returncode=128, stdout="", stderr="bad base")
        with patch.object(ci.subprocess, "run", return_value=completed):
            with self.assertRaisesRegex(RuntimeError, "bad base"):
                ci.changed_paths("missing-base")


class SuiteSelectionTests(unittest.TestCase):
    def names(self, paths):
        return {suite.name for suite in ci.selected_suites(paths)}

    def test_deleted_e009_file_selects_kernel_and_apply_dependents(self):
        self.assertEqual(self.names(["experiments/e009/removed.py"]), {"e009-kernel", "e010-apply"})

    def test_e004_change_selects_security_and_kernel(self):
        self.assertEqual(self.names(["experiments/e004/removed.py"]), {"e004-security", "e009-kernel"})

    def test_e001_change_selects_prototype_and_pilot(self):
        self.assertEqual(self.names(["experiments/e001/examples/catalog.an"]), {"e001-prototype", "pilot-protocol"})

    def test_project_control_files_select_control_validator(self):
        self.assertEqual(self.names(["project-control/STATE.json"]), {"project-control"})
        self.assertEqual(self.names(["project_control.py"]), {"project-control"})

    def test_ci_selector_tests_select_themselves(self):
        self.assertEqual(self.names(["scripts/test_ci.py"]), {"ci-runner"})

    def test_ci_runner_and_workflow_changes_run_all_suites(self):
        all_names = {suite.name for suite in ci.SUITES}
        self.assertEqual(self.names(["scripts/ci.py"]), all_names)
        self.assertEqual(self.names([".github/workflows/ci.yml"]), all_names)

    def test_unrelated_research_document_does_not_select_a_test_suite(self):
        self.assertEqual(self.names(["research/notes.md"]), set())

    def test_no_base_runs_all_suites(self):
        self.assertEqual({suite.name for suite in ci.selected_suites(None)},
                         {suite.name for suite in ci.SUITES})


class WorkflowConcurrencyTests(unittest.TestCase):
    def test_expensive_ci_lanes_have_isolated_non_cancelling_groups(self):
        workflow = Path(".github/workflows/ci.yml").read_text(encoding="utf-8")
        lanes = ("fast", "extended", "models", "benchmark", "performance-confirmation", "lockfiles")
        groups = set()
        for lane in lanes:
            expected = "\n".join((
                f"  {lane}:",
                "    concurrency:",
                "      group: agent-native-" + lane + "-${{ github.event.pull_request.number || github.ref }}",
                "      cancel-in-progress: false",
            ))
            self.assertIn(expected, workflow, f"{lane} must have an isolated non-cancelling concurrency group")
            groups.add(f"agent-native-{lane}-<ref>")
        self.assertEqual(len(groups), len(lanes))

    def test_scorecard_does_not_turn_an_earlier_gate_skip_into_a_secondary_failure(self):
        workflow = Path(".github/workflows/ci.yml").read_text(encoding="utf-8")
        self.assertIn("if: always() && steps.paths.outcome == 'success'", workflow)
        self.assertIn('if [[ ! -s "$RUNNER_TEMP/fast-ci-summary.json" ]]; then', workflow)
        self.assertIn("if-no-files-found: ignore", workflow)

if __name__ == "__main__":
    unittest.main()
