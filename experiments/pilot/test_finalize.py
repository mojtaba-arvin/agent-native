import copy
import hashlib
import json
import tempfile
import time
import unittest
from pathlib import Path

from candidate import MAX_CANDIDATE_BYTES
from finalize import FinalizationError, finalize_run
from gateway import PilotGateway


class FinalizeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.run_id = "finalize-test-run"
        self.candidate_id = "upfront"
        self.task_id = "pilot-catalog-add-readonly-operation"
        self.model_id = "test-model"
        self.events = []
        self.gateway = PilotGateway(
            "upfront",
            trace_sink=self.events.append,
            trace_context={
                "run_id": self.run_id,
                "candidate_id": self.candidate_id,
                "model_id": self.model_id,
                "task_id": self.task_id,
                "attempt": 1,
            },
        )
        self.base_revision = self.gateway.interface.revision("catalog")
        self.ir = copy.deepcopy(self.gateway.interface.services["catalog"])
        self.ir["operations"].append({
            "name": "get_item_by_name",
            "method": "GET",
            "path": "/items/by-name/{name}",
            "input": [{"name": "name", "type": "String", "source": "path"}],
            "output": "Item",
            "errors": ["InvalidInput", "NotFound", "Unauthorized"],
            "validation": ["name.non_empty"],
            "effects": ["repository.read"],
            "capability": "items.read",
        })
        self.gateway_call("service.inspect", {"service_id": "catalog"})
        proposed = self.gateway_call("service.propose", {
            "service_id": "catalog",
            "base_revision": self.base_revision,
            "ir": self.ir,
        })
        self.change_set_id = proposed["response"]["result"]["change_set_id"]
        self.gateway_call("service.validate", {"change_set_id": self.change_set_id})
        self.gateway_call("service.plan", {"change_set_id": self.change_set_id})

        self.candidate = {
            "schema_version": 1,
            "task_id": self.task_id,
            "service_id": "catalog",
            "base_revision": self.base_revision,
            "change_set_id": self.change_set_id,
            "ir": self.ir,
        }
        self.candidate_bytes = (json.dumps(
            self.candidate,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ) + "\n").encode("utf-8")
        self.trace_path = self.root / "trace.jsonl"
        self.candidate_path = self.root / "candidate.json"
        self.result_path = self.root / "result.json"
        self.output_trace_path = self.root / "final-trace.jsonl"
        self.output_summary_path = self.root / "summary.json"
        self.write_trace()
        self.candidate_path.write_bytes(self.candidate_bytes)

        self.agent_finished = max(event["timestamp_ns"] for event in self.events) + 1_000_000
        self.result = {
            "schema_version": 1,
            "run_id": self.run_id,
            "candidate_id": self.candidate_id,
            "task_id": self.task_id,
            "attempt": 1,
            "candidate_sha256": hashlib.sha256(self.candidate_bytes).hexdigest(),
            "accepted": True,
            "eligible_for_acceptance": True,
            "failure_class": None,
            "agent_finished_at_ns": self.agent_finished,
            "evaluated_at_ns": self.agent_finished + 1_000_000,
            "evaluator_version": "test-evaluator-v1",
        }
        self.write_result()

    def tearDown(self):
        self.temp.cleanup()

    def gateway_call(self, tool, arguments):
        return self.gateway.handle_message({
            "type": "tool_call",
            "request_id": f"req-{len(self.events)}",
            "tool": tool,
            "arguments": arguments,
        })

    def write_trace(self):
        self.trace_path.write_text(
            "".join(json.dumps(event, sort_keys=True) + "\n" for event in self.events),
            encoding="utf-8",
        )

    def write_result(self):
        self.result_path.write_text(
            json.dumps(self.result, sort_keys=True),
            encoding="utf-8",
        )

    def test_accepted_result_is_correlated_and_finalized(self):
        summary = finalize_run(
            trace_path=self.trace_path,
            evaluation_result_path=self.result_path,
            candidate_path=self.candidate_path,
            output_trace_path=self.output_trace_path,
            output_summary_path=self.output_summary_path,
        )
        self.assertEqual(summary["accepted_tasks"], 1)
        self.assertEqual(summary["task_count"], 1)
        self.assertTrue(self.output_trace_path.exists())
        self.assertTrue(self.output_summary_path.exists())
        final_events = [
            json.loads(line)
            for line in self.output_trace_path.read_text(encoding="utf-8").splitlines()
        ]
        finish = final_events[-1]
        self.assertEqual(finish["event_type"], "task_finished")
        self.assertTrue(finish["accepted"])
        self.assertEqual(finish["timestamp_ns"], self.agent_finished)

    def test_infrastructure_failure_is_excluded_from_acceptance_denominator(self):
        failed_trace = self.root / "provider-failure-trace.jsonl"
        failed_events = self.events[:2]
        failed_trace.write_text(
            "".join(json.dumps(event, sort_keys=True) + "\n" for event in failed_events),
            encoding="utf-8",
        )
        failed_result = dict(
            self.result,
            candidate_sha256=None,
            accepted=False,
            eligible_for_acceptance=False,
            failure_class="PROVIDER_ERROR",
            agent_finished_at_ns=max(e["timestamp_ns"] for e in failed_events) + 1000,
        )
        failed_result["evaluated_at_ns"] = failed_result["agent_finished_at_ns"] + 1000
        failed_path = self.root / "provider-failure-result.json"
        failed_path.write_text(json.dumps(failed_result), encoding="utf-8")
        summary = finalize_run(
            trace_path=failed_trace,
            evaluation_result_path=failed_path,
            output_trace_path=self.root / "provider-failure-final.jsonl",
        )
        self.assertEqual(summary["task_count"], 1)
        self.assertEqual(summary["eligible_task_count"], 0)
        self.assertEqual(summary["excluded_task_count"], 1)
        self.assertIsNone(summary["acceptance_rate"])

    def test_provider_failure_cannot_be_marked_as_eligible(self):
        self.result["accepted"] = False
        self.result["eligible_for_acceptance"] = True
        self.result["failure_class"] = "PROVIDER_ERROR"
        self.result["candidate_sha256"] = None
        self.write_result()
        with self.assertRaisesRegex(FinalizationError, "eligibility_mismatch"):
            finalize_run(
                trace_path=self.trace_path,
                evaluation_result_path=self.result_path,
                output_trace_path=self.output_trace_path,
            )


    def test_accepted_result_requires_validate_and_plan_for_same_proposal(self):
        validation_event = next(
            event for event in self.events
            if event["event_type"] == "tool_call"
            and event.get("tool_name") == "service.validate"
        )
        validation_event["change_set_id"] = "f" * 64
        self.write_trace()
        with self.assertRaisesRegex(
            FinalizationError,
            "missing_successful_tool:service.validate",
        ):
            finalize_run(
                trace_path=self.trace_path,
                evaluation_result_path=self.result_path,
                candidate_path=self.candidate_path,
                output_trace_path=self.output_trace_path,
            )


    def test_accepted_result_rejects_invalid_validator_result(self):
        validation_event = next(
            event for event in self.events
            if event["event_type"] == "tool_call"
            and event.get("tool_name") == "service.validate"
        )
        validation_event["validation_valid"] = False
        self.write_trace()
        with self.assertRaisesRegex(
            FinalizationError,
            "requires_successful_semantic_validation",
        ):
            finalize_run(
                trace_path=self.trace_path,
                evaluation_result_path=self.result_path,
                candidate_path=self.candidate_path,
                output_trace_path=self.output_trace_path,
            )

    def test_accepted_result_rejects_mutating_or_deploying_plan(self):
        plan_event = next(
            event for event in self.events
            if event["event_type"] == "tool_call"
            and event.get("tool_name") == "service.plan"
        )
        plan_event["plan_will_mutate"] = True
        self.write_trace()
        with self.assertRaisesRegex(
            FinalizationError,
            "plan_must_not_mutate",
        ):
            finalize_run(
                trace_path=self.trace_path,
                evaluation_result_path=self.result_path,
                candidate_path=self.candidate_path,
                output_trace_path=self.output_trace_path,
            )


    def test_finalizer_rejects_oversized_candidate_before_hashing(self):
        oversized = self.root / "oversized-candidate.json"
        oversized.write_bytes(b"x" * (MAX_CANDIDATE_BYTES + 1))
        with self.assertRaisesRegex(FinalizationError, "candidate_file_too_large"):
            finalize_run(
                trace_path=self.trace_path,
                evaluation_result_path=self.result_path,
                candidate_path=oversized,
                output_trace_path=self.output_trace_path,
            )


    def test_candidate_hash_mismatch_is_rejected(self):
        self.result["candidate_sha256"] = "0" * 64
        self.write_result()
        with self.assertRaisesRegex(FinalizationError, "candidate_hash_mismatch"):
            finalize_run(
                trace_path=self.trace_path,
                evaluation_result_path=self.result_path,
                candidate_path=self.candidate_path,
                output_trace_path=self.output_trace_path,
            )

    def test_accepted_result_requires_complete_tool_sequence(self):
        events = [
            event for event in self.events
            if not (
                event["event_type"] == "tool_call"
                and event.get("tool_name") == "service.plan"
            )
        ]
        self.trace_path.write_text(
            "".join(json.dumps(event, sort_keys=True) + "\n" for event in events),
            encoding="utf-8",
        )
        with self.assertRaisesRegex(FinalizationError, "missing_successful_tool:service.plan"):
            finalize_run(
                trace_path=self.trace_path,
                evaluation_result_path=self.result_path,
                candidate_path=self.candidate_path,
                output_trace_path=self.output_trace_path,
            )

    def test_accepted_result_rejects_gateway_tool_budget_overrun(self):
        overrun_event = {
            **self.events[-1],
            "event_id": "budget-overrun",
            "timestamp_ns": max(event["timestamp_ns"] for event in self.events) + 1,
            "event_type": "tool_call",
            "tool_name": "service.inspect",
            "failure_class": "TOOL_CALL_BUDGET_EXCEEDED",
        }
        events = [*self.events, overrun_event]
        self.trace_path.write_text(
            "".join(json.dumps(event, sort_keys=True) + "\n" for event in events),
            encoding="utf-8",
        )
        self.agent_finished = overrun_event["timestamp_ns"] + 1000
        self.result["agent_finished_at_ns"] = self.agent_finished
        self.result["evaluated_at_ns"] = self.agent_finished + 1000
        self.write_result()
        with self.assertRaisesRegex(
            FinalizationError,
            "accepted_result_conflicts_with_tool_budget_overrun",
        ):
            finalize_run(
                trace_path=self.trace_path,
                evaluation_result_path=self.result_path,
                candidate_path=self.candidate_path,
                output_trace_path=self.output_trace_path,
            )


    def test_accepted_result_cannot_follow_apply_attempt(self):
        self.gateway_call("service.apply", {"change_set_id": self.change_set_id})
        self.write_trace()
        self.agent_finished = max(event["timestamp_ns"] for event in self.events) + 1_000_000
        self.result["agent_finished_at_ns"] = self.agent_finished
        self.result["evaluated_at_ns"] = self.agent_finished + 1_000_000
        self.write_result()
        with self.assertRaisesRegex(FinalizationError, "apply_attempt"):
            finalize_run(
                trace_path=self.trace_path,
                evaluation_result_path=self.result_path,
                candidate_path=self.candidate_path,
                output_trace_path=self.output_trace_path,
            )

    def test_rejected_run_can_be_finalized_without_candidate(self):
        failed_trace = self.root / "failed-trace.jsonl"
        prior_call = next(
            event for event in self.events
            if event["event_type"] == "tool_call"
        )
        failed_events = [
            self.events[0],
            self.events[1],
            {
                **prior_call,
                "event_id": "failed-call",
                "timestamp_ns": prior_call["timestamp_ns"] + 1,
                "tool_name": "service.apply",
                "failure_class": "APPLY_DISABLED",
                "schema_lookup": False,
            },
        ]
        failed_trace.write_text(
            "".join(json.dumps(event, sort_keys=True) + "\n" for event in failed_events),
            encoding="utf-8",
        )
        failed_result = dict(
            self.result,
            candidate_sha256=None,
            accepted=False,
            failure_class="FORBIDDEN_ACTION_ATTEMPTED",
            agent_finished_at_ns=max(e["timestamp_ns"] for e in failed_events) + 1000,
        )
        failed_result["evaluated_at_ns"] = failed_result["agent_finished_at_ns"] + 1000
        failed_path = self.root / "failed-result.json"
        failed_path.write_text(json.dumps(failed_result), encoding="utf-8")
        summary = finalize_run(
            trace_path=failed_trace,
            evaluation_result_path=failed_path,
            output_trace_path=self.root / "failed-final.jsonl",
        )
        self.assertEqual(summary["accepted_tasks"], 0)
        self.assertEqual(summary["tasks"][0]["failure_class"], "FORBIDDEN_ACTION_ATTEMPTED")


if __name__ == "__main__":
    unittest.main()
