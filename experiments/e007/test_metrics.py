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
            {"event_id":"5","task_id":"a","attempt":1,"timestamp_ns":500,"event_type":"runtime_metric","metric_name":"p95_latency","metric_value":12.5,"metric_unit":"ms"},
            {"event_id":"6","task_id":"a","attempt":1,"timestamp_ns":600,"event_type":"task_finished","accepted":True},
        ]
        result = summarize(events)
        self.assertEqual(result["accepted_tasks"], 1)
        self.assertEqual(result["totals"]["input_tokens"], 100)
        self.assertEqual(result["totals"]["output_tokens"], 40)
        self.assertEqual(result["totals"]["tool_calls"], 1)
        self.assertEqual(result["totals"]["repair_events"], 1)
        self.assertEqual(result["cost_per_accepted_task_usd"], 0.02)
        self.assertEqual(result["runtime_metrics"]["p95_latency"]["median"], 12.5)

    def test_repeated_runs_and_candidates_are_kept_separate(self):
        events = []
        for run_id, candidate, accepted, tokens in [
            ("run-a", "dsl", True, 100),
            ("run-b", "go", False, 250),
        ]:
            events.extend([
                {"event_id":f"{run_id}-start","run_id":run_id,"candidate_id":candidate,
                 "model_id":"agent-x","task_id":"same-task","attempt":1,
                 "timestamp_ns":10,"event_type":"task_started"},
                {"event_id":f"{run_id}-usage","run_id":run_id,"candidate_id":candidate,
                 "model_id":"agent-x","task_id":"same-task","attempt":1,
                 "timestamp_ns":20,"event_type":"model_usage",
                 "input_tokens":tokens,"output_tokens":10,"cost_usd":0.01},
                {"event_id":f"{run_id}-finish","run_id":run_id,"candidate_id":candidate,
                 "model_id":"agent-x","task_id":"same-task","attempt":1,
                 "timestamp_ns":30,"event_type":"task_finished","accepted":accepted},
            ])
        result = summarize(events)
        self.assertEqual(result["task_count"], 2)
        self.assertEqual(result["accepted_tasks"], 1)
        self.assertEqual(result["totals"]["input_tokens"], 350)
        self.assertEqual(
            {(row["run_id"], row["candidate_id"], row["accepted"]) for row in result["tasks"]},
            {("run-a", "dsl", True), ("run-b", "go", False)},
        )

    def test_attempts_are_not_merged(self):
        events = [
            {"event_id":"1","task_id":"a","attempt":1,"timestamp_ns":1,"event_type":"task_started"},
            {"event_id":"2","task_id":"a","attempt":1,"timestamp_ns":2,"event_type":"task_finished","accepted":False},
            {"event_id":"3","task_id":"a","attempt":2,"timestamp_ns":3,"event_type":"task_started"},
            {"event_id":"4","task_id":"a","attempt":2,"timestamp_ns":4,"event_type":"task_finished","accepted":True},
        ]
        result = summarize(events)
        self.assertEqual(result["task_count"], 2)
        self.assertEqual([row["attempt"] for row in result["tasks"]], [1, 2])
        self.assertEqual(result["accepted_tasks"], 1)

    def test_inconsistent_candidate_identity_is_rejected(self):
        events = [
            {"event_id":"1","run_id":"run","candidate_id":"dsl","task_id":"a",
             "attempt":1,"timestamp_ns":1,"event_type":"task_started"},
            {"event_id":"2","run_id":"run","candidate_id":"go","task_id":"a",
             "attempt":1,"timestamp_ns":2,"event_type":"task_finished","accepted":True},
        ]
        with self.assertRaisesRegex(ValueError, "inconsistent_candidate_id"):
            summarize(events)

    def test_missing_usage_is_unknown_not_zero(self):
        events = [
            {"event_id":"1","task_id":"a","attempt":1,"timestamp_ns":1,"event_type":"task_started"},
            {"event_id":"2","task_id":"a","attempt":1,"timestamp_ns":2,"event_type":"task_finished","accepted":True},
        ]
        result = summarize(events)
        self.assertFalse(result["token_usage_complete"])
        self.assertFalse(result["cost_complete"])
        self.assertIsNone(result["totals"]["input_tokens"])
        self.assertIsNone(result["cost_per_accepted_task_usd"])

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
            path.write_text(json.dumps(event) + "\n", encoding="utf-8")
            self.assertEqual(load_jsonl(path), [event])

    def test_negative_token_counts_are_rejected(self):
        event = {"event_id":"1","task_id":"a","attempt":1,"timestamp_ns":1,"event_type":"model_usage","input_tokens":-1}
        with self.assertRaisesRegex(ValueError, "invalid_input_tokens"):
            summarize([event])

    def test_unknown_fields_are_rejected(self):
        event = {"event_id":"1","task_id":"a","attempt":1,"timestamp_ns":1,"event_type":"task_started","oracle_path":"/secret"}
        with self.assertRaisesRegex(ValueError, "unexpected_trace_fields"):
            summarize([event])

    def test_non_finite_cost_is_rejected(self):
        event = {"event_id":"1","task_id":"a","attempt":1,"timestamp_ns":1,"event_type":"model_usage","cost_usd":float("nan")}
        with self.assertRaisesRegex(ValueError, "invalid_cost_usd"):
            summarize([event])

    def test_non_finite_runtime_metric_is_rejected(self):
        event = {"event_id":"1","task_id":"a","attempt":1,"timestamp_ns":1,"event_type":"runtime_metric","metric_name":"rss","metric_value":float("inf"),"metric_unit":"bytes"}
        with self.assertRaisesRegex(ValueError, "runtime_metric_invalid_value"):
            summarize([event])

    def test_multiple_finish_events_are_rejected(self):
        events = [
            {"event_id":"1","task_id":"a","attempt":1,"timestamp_ns":1,"event_type":"task_finished","accepted":True},
            {"event_id":"2","task_id":"a","attempt":1,"timestamp_ns":2,"event_type":"task_finished","accepted":False},
        ]
        with self.assertRaisesRegex(ValueError, "multiple_task_finished"):
            summarize(events)

    def test_retry_and_failure_metadata_must_be_typed(self):
        event = {"event_id":"1","task_id":"a","attempt":1,"timestamp_ns":1,"event_type":"repair","retry":"false"}
        with self.assertRaisesRegex(ValueError, "invalid_retry"):
            summarize([event])
        event = {"event_id":"2","task_id":"a","attempt":1,"timestamp_ns":2,"event_type":"task_finished","accepted":False,"failure_class":7}
        with self.assertRaisesRegex(ValueError, "invalid_failure_class"):
            summarize([event])


    def test_tool_errors_and_schema_discovery_are_counted_separately(self):
        events = [
            {"event_id":"1","task_id":"pilot","attempt":1,"timestamp_ns":1,
             "event_type":"task_started","run_id":"r1","candidate_id":"progressive","model_id":"m1"},
            {"event_id":"2","task_id":"pilot","attempt":1,"timestamp_ns":2,
             "event_type":"tool_call","tool_name":"interface.describe",
             "run_id":"r1","candidate_id":"progressive","model_id":"m1"},
            {"event_id":"3","task_id":"pilot","attempt":1,"timestamp_ns":3,
             "event_type":"tool_call","tool_name":"service.inspect",
             "run_id":"r1","candidate_id":"progressive","model_id":"m1"},
            {"event_id":"4","task_id":"pilot","attempt":1,"timestamp_ns":4,
             "event_type":"tool_call","tool_name":"not.real",
             "failure_class":"UNKNOWN_TOOL",
             "run_id":"r1","candidate_id":"progressive","model_id":"m1"},
            {"event_id":"5","task_id":"pilot","attempt":1,"timestamp_ns":5,
             "event_type":"tool_call","tool_name":"service.propose",
             "failure_class":"ARGUMENT_FIELDS",
             "run_id":"r1","candidate_id":"progressive","model_id":"m1"},
            {"event_id":"6","task_id":"pilot","attempt":1,"timestamp_ns":6,
             "event_type":"task_finished","accepted":False,
             "run_id":"r1","candidate_id":"progressive","model_id":"m1"},
        ]
        result = summarize(events)
        task = result["tasks"][0]
        self.assertEqual(task["tool_calls"], 4)
        self.assertEqual(task["tool_errors"], 2)
        self.assertEqual(task["invalid_tool_calls"], 2)
        self.assertEqual(task["schema_argument_errors"], 1)
        self.assertEqual(task["schema_lookup_calls"], 1)
        self.assertEqual(
            task["tool_error_classes"],
            {"ARGUMENT_FIELDS": 1, "UNKNOWN_TOOL": 1},
        )
        self.assertEqual(result["totals"]["tool_errors"], 2)
        self.assertEqual(result["totals"]["invalid_tool_calls"], 2)
        self.assertEqual(result["totals"]["schema_argument_errors"], 1)
        self.assertEqual(result["totals"]["schema_lookup_calls"], 1)

    def test_legacy_traces_report_zero_tool_errors(self):
        events = [
            {"event_id":"1","task_id":"legacy","attempt":1,"timestamp_ns":1,"event_type":"task_started"},
            {"event_id":"2","task_id":"legacy","attempt":1,"timestamp_ns":2,
             "event_type":"tool_call","tool_name":"service.inspect"},
            {"event_id":"3","task_id":"legacy","attempt":1,"timestamp_ns":3,
             "event_type":"task_finished","accepted":True},
        ]
        task = summarize(events)["tasks"][0]
        self.assertEqual(task["tool_errors"], 0)
        self.assertEqual(task["invalid_tool_calls"], 0)
        self.assertEqual(task["schema_argument_errors"], 0)


if __name__ == "__main__":
    unittest.main()
