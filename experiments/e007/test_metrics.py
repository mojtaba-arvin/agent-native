import json
import tempfile
import unittest
from pathlib import Path
from metrics import load_jsonl, summarize


class MetricsTests(unittest.TestCase):
    def test_agent_effort_and_cost_per_accepted_task(self):
        events = [
            {"event_id":"1","task_id":"a","attempt":1,"timestamp_ns":100,"event_type":"task_started"},
            {"event_id":"2","task_id":"a","attempt":1,"timestamp_ns":200,"event_type":"model_usage","input_tokens":100,"output_tokens":40,"cost_usd":0.02},
            {"event_id":"3","task_id":"a","attempt":1,"timestamp_ns":300,"event_type":"tool_call","tool_name":"service.inspect"},
            {"event_id":"4","task_id":"a","attempt":1,"timestamp_ns":400,"event_type":"repair","retry":True},
            {"event_id":"5","task_id":"a","attempt":1,"timestamp_ns":500,"event_type":"task_finished","accepted":True},
        ]
        result = summarize(events)
        self.assertEqual(result["accepted_tasks"], 1)
        self.assertEqual(result["totals"]["input_tokens"], 100)
        self.assertEqual(result["totals"]["output_tokens"], 40)
        self.assertEqual(result["totals"]["tool_calls"], 1)
        self.assertEqual(result["totals"]["repair_events"], 1)
        self.assertEqual(result["cost_per_accepted_task_usd"], 0.02)

    def test_no_accepted_tasks_returns_null_cost(self):
        self.assertIsNone(summarize([])["cost_per_accepted_task_usd"])

    def test_duplicate_event_id_is_rejected(self):
        event = {"event_id":"x","task_id":"a","attempt":1,"timestamp_ns":1,"event_type":"task_started"}
        with self.assertRaisesRegex(ValueError, "duplicate_event_id"):
            summarize([event, event])

    def test_trace_jsonl_loader_preserves_raw_events(self):
        event = {"event_id":"1","task_id":"a","attempt":1,"timestamp_ns":1,"event_type":"task_started"}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "trace.jsonl"
            path.write_text(json.dumps(event) + "\\n", encoding="utf-8")
            self.assertEqual(load_jsonl(path), [event])

    def test_negative_token_counts_are_rejected(self):
        event = {"event_id":"1","task_id":"a","attempt":1,"timestamp_ns":1,"event_type":"model_usage","input_tokens":-1}
        with self.assertRaisesRegex(ValueError, "invalid_input_tokens"):
            summarize([event])

    def test_multiple_finish_events_are_rejected(self):
        events = [
            {"event_id":"1","task_id":"a","attempt":1,"timestamp_ns":1,"event_type":"task_finished","accepted":True},
            {"event_id":"2","task_id":"a","attempt":1,"timestamp_ns":2,"event_type":"task_finished","accepted":False},
        ]
        with self.assertRaisesRegex(ValueError, "multiple_task_finished"):
            summarize(events)


if __name__ == "__main__":
    unittest.main()
