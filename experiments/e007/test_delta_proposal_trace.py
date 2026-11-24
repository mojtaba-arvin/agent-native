import json
import unittest
from pathlib import Path

from metrics import summarize


class DeltaProposalTraceTests(unittest.TestCase):
    def test_delta_proposal_change_set_is_a_lifecycle_event(self):
        events = [
            {
                "event_id": "start",
                "task_id": "delta-task",
                "attempt": 1,
                "timestamp_ns": 1,
                "event_type": "task_started",
            },
            {
                "event_id": "proposal",
                "task_id": "delta-task",
                "attempt": 1,
                "timestamp_ns": 2,
                "event_type": "tool_call",
                "tool_name": "service.propose_delta",
                "change_set_id": "a" * 64,
            },
            {
                "event_id": "validation",
                "task_id": "delta-task",
                "attempt": 1,
                "timestamp_ns": 3,
                "event_type": "tool_call",
                "tool_name": "service.validate",
                "change_set_id": "a" * 64,
                "validation_valid": True,
            },
            {
                "event_id": "plan",
                "task_id": "delta-task",
                "attempt": 1,
                "timestamp_ns": 4,
                "event_type": "tool_call",
                "tool_name": "service.plan",
                "change_set_id": "a" * 64,
                "plan_valid": True,
                "plan_will_mutate": False,
                "plan_will_deploy": False,
            },
            {
                "event_id": "finish",
                "task_id": "delta-task",
                "attempt": 1,
                "timestamp_ns": 5,
                "event_type": "task_finished",
                "accepted": True,
            },
        ]
        result = summarize(events)
        self.assertEqual(result["accepted_tasks"], 1)
        self.assertEqual(result["totals"]["tool_calls"], 3)

    def test_change_set_id_remains_restricted_to_lifecycle_tools(self):
        event = {
            "event_id": "inspect",
            "task_id": "delta-task",
            "attempt": 1,
            "timestamp_ns": 1,
            "event_type": "tool_call",
            "tool_name": "service.inspect",
            "change_set_id": "a" * 64,
        }
        with self.assertRaisesRegex(
            ValueError, "change_set_id_requires_proposal_lifecycle_tool"
        ):
            summarize([event])

    def test_trace_json_schema_allows_delta_proposal_and_rejects_other_tools(self):
        schema_path = Path(__file__).with_name("trace.schema.json")
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        rule = next(
            item for item in schema["allOf"]
            if item.get("if", {}).get("required") == ["change_set_id"]
        )
        allowed = rule["then"]["properties"]["tool_name"]["enum"]
        self.assertIn("service.propose_delta", allowed)
        self.assertNotIn("service.inspect", allowed)


if __name__ == "__main__":
    unittest.main()
