from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import run_schedule


class RunScheduleTests(unittest.TestCase):
    def _schedule(self):
        return {
            "plan_id": "a" * 64,
            "protocol": {
                "source_revision": "b" * 40,
                "model_id": "local-test-model",
                "pairs": 1,
            },
            "trials": [
                {
                    "sequence": 1,
                    "pair_id": "pair-0001",
                    "run_id": "pair-0001-progressive",
                    "candidate_id": "progressive",
                },
                {
                    "sequence": 2,
                    "pair_id": "pair-0001",
                    "run_id": "pair-0001-upfront",
                    "candidate_id": "upfront",
                },
            ],
        }

    def _record(self, trial, status, failure_class=None):
        return {
            "sequence": trial["sequence"],
            "pair_id": trial["pair_id"],
            "run_id": trial["run_id"],
            "candidate_id": trial["candidate_id"],
            "model_id": "local-test-model",
            "status": status,
            "failure_class": failure_class,
            "failure_detail": None,
            "agent_started_at_ns": 10 + trial["sequence"],
            "agent_finished_at_ns": 20 + trial["sequence"],
            "trace_path": f"/outside/{trial['run_id']}/gateway.jsonl",
            "candidate_path": None,
            "candidate_sha256": None,
            "candidate_summary": None,
            "evaluator_status": "not_run",
        }

    def test_schedule_runs_serially_and_preserves_each_trial_outcome(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "checkout"
            root.mkdir()
            results = Path(temporary) / "results"
            first, second = self._schedule()["trials"]
            outcomes = [
                self._record(first, "candidate_ready_for_external_evaluation"),
                self._record(second, "failed", "INVALID_CANDIDATE"),
            ]
            with (
                patch("run_schedule.verify_schedule_checkout") as verify,
                patch("run_schedule.run_one_trial", side_effect=outcomes) as run_one,
            ):
                batch = run_schedule.run_schedule(
                    self._schedule(),
                    results_dir=results,
                    root=root,
                )

            verify.assert_called_once()
            self.assertEqual(
                [entry.args[0]["sequence"] for entry in run_one.call_args_list],
                [1, 2],
            )
            self.assertEqual(batch["status"], "completed")
            self.assertEqual(batch["completed_trials"], 2)
            self.assertEqual(batch["candidate_ready_count"], 1)
            self.assertEqual(batch["failed_count"], 1)
            self.assertEqual(batch["failure_counts"], {"INVALID_CANDIDATE": 1})
            saved = json.loads(Path(batch["batch_manifest_path"]).read_text(encoding="utf-8"))
            self.assertEqual(saved["batch_manifest_path"], batch["batch_manifest_path"])
            self.assertEqual(saved["trials"][0]["candidate_id"], "progressive")
            self.assertEqual(saved["trials"][1]["failure_class"], "INVALID_CANDIDATE")
            self.assertIsNone(saved["trials"][1]["candidate_sha256"])

    def test_candidate_ready_gate_rejects_completed_execution_with_agent_failures(self):
        with self.assertRaisesRegex(RuntimeError, "candidate_not_ready"):
            run_schedule.assert_candidate_ready({
                "status": "completed",
                "scheduled_trials": 2,
                "candidate_ready_count": 1,
            })

    def test_candidate_ready_gate_accepts_only_fully_correlated_pair(self):
        run_schedule.assert_candidate_ready({
            "status": "completed",
            "scheduled_trials": 2,
            "candidate_ready_count": 2,
        })

    def test_results_directory_must_be_outside_checkout(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "checkout"
            root.mkdir()
            with patch("run_schedule.verify_schedule_checkout"):
                with self.assertRaisesRegex(ValueError, "outside_checkout"):
                    run_schedule.run_schedule(
                        self._schedule(),
                        results_dir=root / "results",
                        root=root,
                    )

    def test_runner_interruption_writes_partial_batch_manifest(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "checkout"
            root.mkdir()
            results = Path(temporary) / "results"
            with (
                patch("run_schedule.verify_schedule_checkout"),
                patch("run_schedule.run_one_trial", side_effect=OSError("disk unavailable")),
            ):
                with self.assertRaisesRegex(RuntimeError, "batch_interrupted_after_0_trials"):
                    run_schedule.run_schedule(
                        self._schedule(),
                        results_dir=results,
                        root=root,
                    )

            manifest = results / f"batch-{'a' * 64}.json"
            saved = json.loads(manifest.read_text(encoding="utf-8"))
            self.assertEqual(saved["status"], "interrupted")
            self.assertEqual(saved["completed_trials"], 0)
            self.assertEqual(saved["runner_error"]["class"], "OSError")


if __name__ == "__main__":
    unittest.main()
