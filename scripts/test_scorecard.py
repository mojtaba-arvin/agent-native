from __future__ import annotations

import json
import unittest

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
                "total": 7,
                "skipped": 1,
                "by_suite": {
                    "unit": {"tests": 7, "skipped": 1},
                    "project-control": {"tests": 0, "skipped": 0},
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
                    "output_sha256": "c" * 64,
                },
                {
                    "name": "project-control",
                    "status": "passed",
                    "exit_code": 0,
                    "elapsed_seconds": 0.25,
                    "test_count": 0,
                    "skipped_test_count": 0,
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

    def test_generates_counts_bound_to_exact_run_and_commit(self):
        scorecard = build_scorecard(self.summary_raw, self.ledger_raw, self.progress_raw)
        self.assertEqual(scorecard["source"]["workflow_run_id"], 777)
        self.assertEqual(scorecard["source"]["commit_sha"], "a" * 40)
        self.assertEqual(scorecard["test_counts"]["total"], 7)
        self.assertEqual(scorecard["test_counts"]["skipped"], 1)
        self.assertEqual(scorecard["ci_result"]["passed_suites"], 2)
        self.assertEqual(scorecard["verified_claims"][0]["evidence_event_ids"], ["RUN-OK"])

    def test_preserves_failed_cancelled_and_ineligible_runs(self):
        scorecard = build_scorecard(self.summary_raw, self.ledger_raw, self.progress_raw)
        outcomes = {item["outcome"] for item in scorecard["run_history"]}
        self.assertEqual(outcomes, {"all_layers_passed_on_pr_head", "failed", "cancelled", "ineligible"})
        self.assertEqual(len(scorecard["run_history"]), 4)

    def test_rejects_manual_edits_to_generated_test_counts(self):
        scorecard = build_scorecard(self.summary_raw, self.ledger_raw, self.progress_raw)
        scorecard["test_counts"]["total"] = 999
        with self.assertRaisesRegex(ValueError, "differs from metrics derived"):
            validate_scorecard(scorecard, self.summary_raw, self.ledger_raw, self.progress_raw)

    def test_rejects_manual_edits_to_run_evidence(self):
        scorecard = build_scorecard(self.summary_raw, self.ledger_raw, self.progress_raw)
        scorecard["source"]["workflow_run_id"] = 999
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
        self.summary["test_counts"]["total"] = 100
        summary_raw = json.dumps(self.summary, sort_keys=True).encode()
        with self.assertRaisesRegex(ValueError, "test totals do not match"):
            build_scorecard(summary_raw, self.ledger_raw, self.progress_raw)

    def test_rejects_duplicate_run_ledger_event_ids(self):
        duplicate = self.ledger_raw + self.ledger_raw.splitlines()[0] + b"\n"
        with self.assertRaisesRegex(ValueError, "duplicate event_id"):
            build_scorecard(self.summary_raw, duplicate, self.progress_raw)


if __name__ == "__main__":
    unittest.main()
