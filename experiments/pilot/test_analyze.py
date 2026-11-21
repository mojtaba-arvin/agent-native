from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import analyze


class PairedAnalysisTests(unittest.TestCase):
    def _schedule(self):
        arms = [
            ("pair-0001", "progressive"),
            ("pair-0001", "upfront"),
            ("pair-0002", "upfront"),
            ("pair-0002", "progressive"),
        ]
        trials = []
        for sequence, (pair_id, arm) in enumerate(arms, 1):
            trials.append({
                "sequence": sequence,
                "pair_id": pair_id,
                "run_id": f"{pair_id}-{arm}",
                "candidate_id": arm,
                "model_id": "local-model",
                "task_id": "pilot-catalog-add-readonly-operation",
                "attempt": 1,
            })
        return {
            "plan_id": "a" * 64,
            "protocol": {
                "source_revision": "b" * 40,
                "model_id": "local-model",
                "pairs": 2,
            },
            "trials": trials,
        }

    def _write_trace(
        self,
        results_root,
        trial,
        *,
        accepted,
        input_tokens,
        output_tokens,
        tool_calls,
        wall_seconds,
        eligible=True,
        failure_class=None,
    ):
        run_dir = Path(results_root) / trial["run_id"]
        run_dir.mkdir(parents=True)
        base = trial["sequence"] * 100_000_000_000
        identity = {
            "run_id": trial["run_id"],
            "candidate_id": trial["candidate_id"],
            "model_id": trial["model_id"],
            "task_id": trial["task_id"],
            "attempt": trial["attempt"],
        }
        events = [{
            **identity,
            "event_id": f"{trial['run_id']}-start",
            "timestamp_ns": base,
            "event_type": "task_started",
        }, {
            **identity,
            "event_id": f"{trial['run_id']}-usage",
            "timestamp_ns": base + 1,
            "event_type": "model_usage",
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
        }]
        for index in range(tool_calls):
            tool_name = "interface.describe" if index == 0 else "service.inspect"
            event = {
                **identity,
                "event_id": f"{trial['run_id']}-tool-{index}",
                "timestamp_ns": base + 2 + index,
                "event_type": "tool_call",
                "tool_name": tool_name,
            }
            if tool_name == "interface.describe":
                event["schema_lookup"] = trial["candidate_id"] == "progressive"
            events.append(event)
        finish = {
            **identity,
            "event_id": f"{trial['run_id']}-finish",
            "timestamp_ns": base + int(wall_seconds * 1_000_000_000),
            "event_type": "task_finished",
            "accepted": accepted,
            "eligible_for_acceptance": eligible,
        }
        if not accepted and failure_class:
            finish["failure_class"] = failure_class
        events.append(finish)
        trace_path = run_dir / "finalized.jsonl"
        trace_path.write_text(
            "".join(json.dumps(event, sort_keys=True) + "\n" for event in events),
            encoding="utf-8",
        )
        return trace_path

    def _populate(self, results_root, *, infra_exclusion=False):
        schedule = self._schedule()
        values = {
            ("pair-0001", "progressive"): (True, 100, 20, 3, 10),
            ("pair-0001", "upfront"): (False, 90, 20, 2, 8),
            ("pair-0002", "upfront"): (True, 110, 20, 4, 11),
            ("pair-0002", "progressive"): (False, 120, 20, 5, 12),
        }
        for trial in schedule["trials"]:
            accepted, inputs, outputs, calls, wall = values[
                (trial["pair_id"], trial["candidate_id"])
            ]
            eligible = not (
                infra_exclusion
                and trial["pair_id"] == "pair-0001"
                and trial["candidate_id"] == "progressive"
            )
            self._write_trace(
                results_root,
                trial,
                accepted=accepted if eligible else False,
                input_tokens=inputs,
                output_tokens=outputs,
                tool_calls=calls,
                wall_seconds=wall,
                eligible=eligible,
                failure_class="ADAPTER_ERROR" if not eligible else (
                    None if accepted else "TASK_NOT_SATISFIED"
                ),
            )
        return schedule

    def test_analysis_calculates_complete_paired_differences(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "checkout"
            root.mkdir()
            results = Path(temporary) / "results"
            results.mkdir()
            schedule = self._populate(results)
            output = Path(temporary) / "analysis.json"

            with patch("analyze.verify_schedule_checkout"):
                result = analyze.analyze_schedule(
                    schedule,
                    results_dir=results,
                    output_path=output,
                    root=root,
                )

            self.assertEqual(result["completed_pairs"], 2)
            self.assertEqual(result["paired_acceptance"]["eligible_pairs"], 2)
            self.assertEqual(
                result["paired_acceptance"]["upfront_minus_progressive"]["mean_upfront_minus_progressive"],
                0,
            )
            self.assertEqual(
                result["paired_acceptance"]["mcnemar"]["exact_two_sided_p_value"],
                1,
            )
            token_delta = result["paired_effort_differences"]["total_tokens"]
            self.assertEqual(token_delta["n_pairs"], 2)
            self.assertEqual(token_delta["mean_upfront_minus_progressive"], -10)
            self.assertEqual(
                result["paired_effort_differences"]["tool_calls"]["mean_upfront_minus_progressive"],
                -1,
            )
            saved = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(saved["analysis_output"], str(output.resolve()))
            self.assertEqual(len(saved["trace_sha256"]), 4)

    def test_infrastructure_exclusion_removes_entire_pair_from_primary_paired_stats(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "checkout"
            root.mkdir()
            results = Path(temporary) / "results"
            results.mkdir()
            schedule = self._populate(results, infra_exclusion=True)

            with patch("analyze.verify_schedule_checkout"):
                result = analyze.analyze_schedule(
                    schedule,
                    results_dir=results,
                    output_path=Path(temporary) / "analysis.json",
                    root=root,
                )

            paired = result["paired_acceptance"]
            self.assertEqual(paired["eligible_pairs"], 1)
            self.assertEqual(paired["infrastructure_excluded_pairs"], ["pair-0001"])
            self.assertEqual(
                result["paired_effort_differences"]["total_tokens"]["n_pairs"],
                1,
            )
            self.assertEqual(
                result["by_arm"]["progressive"]["infrastructure_exclusions"],
                1,
            )

    def test_missing_finalized_trace_is_not_silently_dropped(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "checkout"
            root.mkdir()
            results = Path(temporary) / "results"
            results.mkdir()
            schedule = self._schedule()

            with patch("analyze.verify_schedule_checkout"):
                with self.assertRaisesRegex(analyze.AnalysisError, "finalized_trace_missing"):
                    analyze.analyze_schedule(
                        schedule,
                        results_dir=results,
                        output_path=Path(temporary) / "analysis.json",
                        root=root,
                    )

    def test_analysis_output_must_be_outside_checkout(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "checkout"
            root.mkdir()
            results = Path(temporary) / "results"
            results.mkdir()
            schedule = self._populate(results)

            with patch("analyze.verify_schedule_checkout"):
                with self.assertRaisesRegex(analyze.AnalysisError, "outside_checkout"):
                    analyze.analyze_schedule(
                        schedule,
                        results_dir=results,
                        output_path=root / "analysis.json",
                        root=root,
                    )


if __name__ == "__main__":
    unittest.main()
