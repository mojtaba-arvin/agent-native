from __future__ import annotations

import json
import os
import unittest
from pathlib import Path
from unittest.mock import patch

from ci import Suite, build_ci_summary, parse_negative_self_test_count, parse_test_counts
from generate_scorecard import build_scorecard, validate_scorecard


class EvidenceScorecardTests(unittest.TestCase):
    def setUp(self):
        self.summary = {
            "schema_version": 1,
            "generated_at_utc": "2026-11-19T02:30:00Z",
            "source": {
                "repository": "mojtaba-arvin/agent-native",
                "workflow_run_id": 777,
                "workflow_run_attempt": 1,
                "commit_sha": "a" * 40,
                "branch": "feat/example",
                "base_sha": "b" * 40,
                "event_name": "pull_request",
            },
            "selection": {
                "changed_paths": ["scripts/example.py"],
                "selected_suites": ["unit", "project-control"],
                "selected_suite_count": 2,
            },
            "result": {
                "status": "passed",
                "passed_suites": 2,
                "failed_suites": 0,
                "elapsed_seconds": 1.25,
            },
            "test_counts": {
                "total_known": 7,
                "skipped_known": 1,
                "complete": False,
                "unknown_suites": ["project-control"],
                "negative_self_test_cases": 4,
                "by_suite": {
                    "unit": {"tests": 7, "skipped": 1, "negative_self_test_cases": None, "source": "unittest-output"},
                    "project-control": {"tests": None, "skipped": None, "negative_self_test_cases": 4, "source": "not-reported"},
                },
            },
            "suites": [
                {
                    "name": "unit",
                    "status": "passed",
                    "exit_code": 0,
                    "elapsed_seconds": 1.0,
                    "test_count": 7,
                    "skipped_test_count": 1,
                    "negative_self_test_count": None,
                    "test_count_source": "unittest-output",
                    "output_sha256": "c" * 64,
                },
                {
                    "name": "project-control",
                    "status": "passed",
                    "exit_code": 0,
                    "elapsed_seconds": 0.25,
                    "test_count": None,
                    "skipped_test_count": None,
                    "negative_self_test_count": 4,
                    "test_count_source": "not-reported",
                    "output_sha256": "d" * 64,
                },
            ],
        }
        self.ledger_events = [
            {
                "event_id": "RUN-OK",
                "timestamp": "2026-11-19T01:00:00Z",
                "kind": "workflow_run",
                "outcome": "all_layers_passed_on_pr_head",
                "task_id": "M0-001",
                "summary": "Successful run.",
                "evidence": [{"run_id": 101}],
                "limitations": [],
            },
            {
                "event_id": "RUN-FAILED",
                "timestamp": "2026-11-19T01:10:00Z",
                "kind": "workflow_run",
                "outcome": "failed",
                "task_id": "M0-002",
                "summary": "Failed run retained.",
                "evidence": [{"run_id": 102}],
                "limitations": ["Negative outcome."],
            },
            {
                "event_id": "RUN-CANCELLED",
                "timestamp": "2026-11-19T01:20:00Z",
                "kind": "workflow_run",
                "outcome": "cancelled",
                "task_id": "M0-002",
                "summary": "Cancelled run retained.",
                "evidence": [{"run_id": 103}],
                "limitations": ["Cancellation is not a pass."],
            },
            {
                "event_id": "RUN-INELIGIBLE",
                "timestamp": "2026-11-19T01:30:00Z",
                "kind": "model_run",
                "outcome": "ineligible",
                "task_id": "M3-001",
                "summary": "Ineligible model run retained.",
                "evidence": [{"run_id": 104}],
                "limitations": ["Not decision-grade."],
            },
        ]
        self.progress = {
            "schema_version": 1,
            "completion_claims": [
                {
                    "id": "CLAIM-1",
                    "status": "verified",
                    "milestone_id": "M0",
                    "criterion": "A criterion",
                    "statement": "A verified claim.",
                    "evidence_event_ids": ["RUN-OK"],
                },
                {
                    "id": "CLAIM-PENDING",
                    "status": "pending",
                    "evidence_event_ids": [],
                },
            ],
        }
        self.summary_raw = json.dumps(self.summary, sort_keys=True).encode()
        self.ledger_raw = b"".join(
            json.dumps(event, sort_keys=True).encode() + b"\n"
            for event in self.ledger_events
        )
        self.progress_raw = json.dumps(self.progress, sort_keys=True).encode()

    def test_ci_summary_binds_run_head_checkout_and_parsed_counts(self):
        suite = Suite("unit", ("python", "-m", "unittest"), ("scripts/**",))
        output = "Ran 3 tests in 0.01s\n\nOK (skipped=1)\n"
        with patch.dict(os.environ, {
            "AGENT_NATIVE_SOURCE_SHA": "a" * 40,
            "GITHUB_SHA": "b" * 40,
            "AGENT_NATIVE_SOURCE_BRANCH": "feat/example",
            "GITHUB_RUN_ID": "888",
            "GITHUB_RUN_ATTEMPT": "2",
            "GITHUB_EVENT_NAME": "pull_request",
            "GITHUB_REPOSITORY": "mojtaba-arvin/agent-native",
        }, clear=True):
            summary = build_ci_summary(
                suites=[suite],
                results=[("unit", 0, 0.01, output)],
                paths=["scripts/test_scorecard.py"],
                base_sha="c" * 40,
                elapsed_seconds=0.02,
            )
        self.assertEqual(summary["source"]["commit_sha"], "a" * 40)
        self.assertEqual(summary["source"]["checkout_sha"], "b" * 40)
        self.assertEqual(summary["source"]["workflow_run_id"], 888)
        self.assertEqual(summary["test_counts"]["total_known"], 3)
        self.assertEqual(summary["test_counts"]["skipped_known"], 1)

    def test_ci_summary_keeps_non_unittest_suite_counts_unknown(self):
        suite = Suite("project-control", ("python", "project_control.py", "status"), ("project-control/**",))
        output = "SELF-TEST PASS: 4 negative cases\n"
        with patch.dict(os.environ, {
            "AGENT_NATIVE_SOURCE_SHA": "a" * 40,
            "GITHUB_SHA": "b" * 40,
            "AGENT_NATIVE_SOURCE_BRANCH": "feat/example",
            "GITHUB_RUN_ID": "889",
            "GITHUB_RUN_ATTEMPT": "1",
        }, clear=True):
            summary = build_ci_summary(
                suites=[suite],
                results=[("project-control", 0, 0.01, output)],
                paths=["project-control/TASKS.json"],
                base_sha="c" * 40,
                elapsed_seconds=0.02,
            )
        self.assertIsNone(summary["test_counts"]["by_suite"]["project-control"]["tests"])
        self.assertFalse(summary["test_counts"]["complete"])
        self.assertEqual(summary["test_counts"]["unknown_suites"], ["project-control"])
        self.assertEqual(summary["test_counts"]["negative_self_test_cases"], 4)

    def test_unreported_counts_remain_unknown_and_self_tests_are_separate(self):
        self.assertEqual(parse_test_counts("project control precheck completed"), (None, None))
        self.assertEqual(parse_negative_self_test_count("SELF-TEST PASS: 4 negative cases"), 4)

    def test_ci_runner_parses_reported_test_and_skip_counts(self):
        output = "Ran 12 tests in 0.05s\n\nOK (skipped=3)\n"
        self.assertEqual(parse_test_counts(output), (12, 3))

    def test_fast_workflow_generates_and_uploads_scorecard_even_after_failure(self):
        root = Path(__file__).resolve().parents[1]
        workflow = (root / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
        fast_job = workflow.split("  fast:\n", 1)[1].split("\n  extended:", 1)[0]
        self.assertIn("--json-summary", fast_job)
        self.assertIn("Generate source-verified evidence scorecard\n        if: always()", fast_job)
        self.assertIn("Upload fast-CI evidence artifacts\n        if: always()", fast_job)
        self.assertIn("fast-ci-summary.json", fast_job)
        self.assertIn("fast-ci-scorecard.json", fast_job)

    def test_generates_counts_bound_to_exact_run_and_commit(self):
        scorecard = build_scorecard(self.summary_raw, self.ledger_raw, self.progress_raw)
        self.assertEqual(scorecard["source"]["workflow_run_id"], 777)
        self.assertEqual(scorecard["source"]["commit_sha"], "a" * 40)
        self.assertEqual(scorecard["test_counts"]["total_known"], 7)
        self.assertEqual(scorecard["test_counts"]["skipped_known"], 1)
        self.assertEqual(scorecard["ci_result"]["passed_suites"], 2)
        self.assertEqual(scorecard["verified_claims"][0]["evidence_event_ids"], ["RUN-OK"])

    def test_failed_ci_run_still_produces_a_failed_scorecard(self):
        summary = json.loads(self.summary_raw)
        summary["suites"][0]["status"] = "failed"
        summary["suites"][0]["exit_code"] = 1
        summary["result"]["status"] = "failed"
        summary["result"]["passed_suites"] = 1
        summary["result"]["failed_suites"] = 1
        summary_raw = json.dumps(summary, sort_keys=True).encode()
        scorecard = build_scorecard(summary_raw, self.ledger_raw, self.progress_raw)
        self.assertEqual(scorecard["ci_result"]["status"], "failed")
        self.assertEqual(scorecard["ci_result"]["failed_suites"], 1)

    def test_preserves_failed_cancelled_and_ineligible_runs(self):
        scorecard = build_scorecard(self.summary_raw, self.ledger_raw, self.progress_raw)
        outcomes = {item["outcome"] for item in scorecard["run_history"]}
        self.assertEqual(outcomes, {"all_layers_passed_on_pr_head", "failed", "cancelled", "ineligible"})
        self.assertEqual(len(scorecard["run_history"]), 4)

    def test_rejects_manual_edits_to_generated_test_counts(self):
        scorecard = build_scorecard(self.summary_raw, self.ledger_raw, self.progress_raw)
        scorecard["test_counts"]["total_known"] = 999
        with self.assertRaisesRegex(ValueError, "differs from metrics derived"):
            validate_scorecard(scorecard, self.summary_raw, self.ledger_raw, self.progress_raw)

    def test_rejects_manual_edits_to_run_evidence(self):
        scorecard = build_scorecard(self.summary_raw, self.ledger_raw, self.progress_raw)
        scorecard["source"]["workflow_run_id"] = 999
        with self.assertRaisesRegex(ValueError, "differs from metrics derived"):
            validate_scorecard(scorecard, self.summary_raw, self.ledger_raw, self.progress_raw)

    def test_rejects_manual_edits_to_source_revision(self):
        scorecard = build_scorecard(self.summary_raw, self.ledger_raw, self.progress_raw)
        scorecard["source"]["commit_sha"] = "f" * 40
        with self.assertRaisesRegex(ValueError, "differs from metrics derived"):
            validate_scorecard(scorecard, self.summary_raw, self.ledger_raw, self.progress_raw)

    def test_rejects_manual_edits_to_verified_claim_evidence(self):
        scorecard = build_scorecard(self.summary_raw, self.ledger_raw, self.progress_raw)
        scorecard["verified_claims"][0]["evidence_event_ids"] = ["UNVERIFIED"]
        with self.assertRaisesRegex(ValueError, "differs from metrics derived"):
            validate_scorecard(scorecard, self.summary_raw, self.ledger_raw, self.progress_raw)

    def test_rejects_verified_claim_with_missing_ledger_evidence(self):
        self.progress["completion_claims"][0]["evidence_event_ids"] = ["MISSING"]
        progress_raw = json.dumps(self.progress, sort_keys=True).encode()
        with self.assertRaisesRegex(ValueError, "references missing ledger events"):
            build_scorecard(self.summary_raw, self.ledger_raw, progress_raw)

    def test_rejects_missing_workflow_run_id(self):
        self.summary["source"]["workflow_run_id"] = None
        summary_raw = json.dumps(self.summary, sort_keys=True).encode()
        with self.assertRaisesRegex(ValueError, "positive GitHub workflow run ID"):
            build_scorecard(summary_raw, self.ledger_raw, self.progress_raw)

    def test_rejects_summary_test_count_mismatch(self):
        self.summary["test_counts"]["total_known"] = 100
        summary_raw = json.dumps(self.summary, sort_keys=True).encode()
        with self.assertRaisesRegex(ValueError, "test totals or unknown-count markers"):
            build_scorecard(summary_raw, self.ledger_raw, self.progress_raw)

    def test_rejects_duplicate_run_ledger_event_ids(self):
        duplicate = self.ledger_raw + self.ledger_raw.splitlines()[0] + b"\n"
        with self.assertRaisesRegex(ValueError, "duplicate event_id"):
            build_scorecard(self.summary_raw, duplicate, self.progress_raw)


if __name__ == "__main__":
    unittest.main()
