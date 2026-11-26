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

    def test_model_usage_events_require_both_token_counts(self):
        event = {
            "event_id": "usage-1",
            "task_id": "pilot",
            "attempt": 1,
            "timestamp_ns": 1,
            "event_type": "model_usage",
            "input_tokens": 123,
        }
        with self.assertRaisesRegex(ValueError, "model_usage_requires_token_counts"):
            summarize([event])

    def test_token_counts_are_rejected_on_non_usage_events(self):
        event = {
            "event_id": "tool-1",
            "task_id": "pilot",
            "attempt": 1,
            "timestamp_ns": 1,
            "event_type": "tool_call",
            "tool_name": "service.inspect",
            "input_tokens": 123,
            "output_tokens": 0,
        }
        with self.assertRaisesRegex(ValueError, "input_tokens_requires_model_usage_event"):
            summarize([event])

    def test_cost_is_rejected_on_non_usage_events(self):
        event = {
            "event_id": "tool-cost-1",
            "task_id": "pilot",
            "attempt": 1,
            "timestamp_ns": 1,
            "event_type": "tool_call",
            "tool_name": "service.inspect",
            "cost_usd": 0.01,
        }
        with self.assertRaisesRegex(ValueError, "cost_usd_requires_model_usage_event"):
            summarize([event])


    def test_negative_token_counts_are_rejected(self):
        event = {"event_id":"1","task_id":"a","attempt":1,"timestamp_ns":1,"event_type":"model_usage","input_tokens":-1}
        with self.assertRaisesRegex(ValueError, "invalid_input_tokens"):
            summarize([event])

    def test_unknown_fields_are_rejected(self):
        event = {"event_id":"1","task_id":"a","attempt":1,"timestamp_ns":1,"event_type":"task_started","oracle_path":"/secret"}
        with self.assertRaisesRegex(ValueError, "unexpected_trace_fields"):
            summarize([event])

    def test_non_finite_cost_is_rejected(self):
        event = {"event_id":"1","task_id":"a","attempt":1,"timestamp_ns":1,"event_type":"model_usage","input_tokens":1,"output_tokens":1,"cost_usd":float("nan")}
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
             "event_type":"tool_call","tool_name":"interface.describe","schema_lookup":True,
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

    def test_schema_lookup_flag_is_typed_and_bound_to_discovery_tool(self):
        base = {
            "event_id": "schema-1",
            "task_id": "pilot",
            "attempt": 1,
            "timestamp_ns": 1,
            "event_type": "tool_call",
            "tool_name": "service.inspect",
            "schema_lookup": True,
        }
        with self.assertRaisesRegex(ValueError, "schema_lookup_requires_interface_describe"):
            summarize([base])
        base["tool_name"] = "interface.describe"
        base["schema_lookup"] = "true"
        with self.assertRaisesRegex(ValueError, "invalid_schema_lookup"):
            summarize([base])

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


    def test_change_set_hash_is_allowed_on_proposal_lifecycle_tool_calls(self):
        event = {
            "event_id": "proposal-1",
            "task_id": "pilot",
            "attempt": 1,
            "timestamp_ns": 1,
            "event_type": "tool_call",
            "tool_name": "service.propose",
            "change_set_id": "a" * 64,
        }
        result = summarize([event])
        self.assertEqual(result["tasks"][0]["tool_calls"], 1)

        malformed = dict(event, change_set_id="not-a-hash")
        with self.assertRaisesRegex(ValueError, "invalid_change_set_id"):
            summarize([malformed])

        for tool_name in ("service.validate", "service.plan"):
            lifecycle_event = dict(event, tool_name=tool_name)
            self.assertEqual(summarize([lifecycle_event])["tasks"][0]["tool_calls"], 1)

        wrong_tool = dict(event, tool_name="service.inspect")
        with self.assertRaisesRegex(ValueError, "change_set_id_requires_proposal_lifecycle_tool"):
            summarize([wrong_tool])


    def test_trace_jsonl_loader_rejects_duplicate_keys(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "trace.jsonl"
            path.write_text(
                '{"event_id":"a","task_id":"t","task_id":"other","attempt":1,'
                '"timestamp_ns":1,"event_type":"task_started"}\\n',
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "invalid_jsonl_line:1"):
                load_jsonl(path)

    def test_trace_jsonl_loader_rejects_non_finite_json_numbers(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "trace.jsonl"
            path.write_text(
                '{"event_id":"a","task_id":"t","attempt":1,"timestamp_ns":1,'
                '"event_type":"runtime_metric","metric_name":"m","metric_unit":"x",'
                '"metric_value":NaN}\\n',
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "invalid_jsonl_line:1"):
                load_jsonl(path)


    def test_infrastructure_invalid_trials_are_excluded_from_acceptance_denominator(self):
        events = []
        for run_id, accepted, eligible, failure in [
            ("valid-run", True, True, None),
            ("provider-outage", False, False, "PROVIDER_ERROR"),
        ]:
            events.append({
                "event_id": f"{run_id}-start",
                "run_id": run_id,
                "task_id": "pilot",
                "attempt": 1,
                "timestamp_ns": 1,
                "event_type": "task_started",
            })
            finish = {
                "event_id": f"{run_id}-finish",
                "run_id": run_id,
                "task_id": "pilot",
                "attempt": 1,
                "timestamp_ns": 2,
                "event_type": "task_finished",
                "accepted": accepted,
                "eligible_for_acceptance": eligible,
            }
            if failure is not None:
                finish["failure_class"] = failure
            events.append(finish)

        result = summarize(events)
        self.assertEqual(result["task_count"], 2)
        self.assertEqual(result["accepted_tasks"], 1)
        self.assertEqual(result["eligible_task_count"], 1)
        self.assertEqual(result["excluded_task_count"], 1)
        self.assertEqual(result["acceptance_rate"], 1.0)
        excluded = next(task for task in result["tasks"] if task["run_id"] == "provider-outage")
        self.assertFalse(excluded["eligible_for_acceptance"])

    def test_accepted_task_cannot_be_marked_ineligible(self):
        event = {
            "event_id": "finish",
            "task_id": "pilot",
            "attempt": 1,
            "timestamp_ns": 2,
            "event_type": "task_finished",
            "accepted": True,
            "eligible_for_acceptance": False,
        }
        with self.assertRaisesRegex(ValueError, "accepted_task_must_be_eligible"):
            summarize([event])


    def test_gateway_protocol_failures_are_counted_as_invalid_tool_calls(self):
        rows = []
        for index, failure in enumerate((
            "REQUEST_ID",
            "INVALID_JSON",
            "INVALID_UTF8",
            "MESSAGE_TOO_LARGE",
            "DUPLICATE_JSON_KEY",
            "NON_FINITE_JSON_NUMBER",
        ), 1):
            rows.append({
                "event_id": f"event-{index}",
                "task_id": "pilot",
                "attempt": 1,
                "timestamp_ns": index,
                "event_type": "tool_call",
                "tool_name": "<invalid>",
                "failure_class": failure,
            })
        result = summarize(rows)
        task = result["tasks"][0]
        self.assertEqual(task["tool_calls"], 6)
        self.assertEqual(task["tool_errors"], 6)
        self.assertEqual(task["invalid_tool_calls"], 6)
        self.assertEqual(task["schema_argument_errors"], 0)


    def test_trace_loader_enforces_size_and_utf8_limits(self):
        from unittest.mock import patch

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "trace.jsonl"
            path.write_bytes(b"12345")
            with patch("metrics.MAX_TRACE_BYTES", 4):
                with self.assertRaisesRegex(ValueError, "trace_file_too_large"):
                    load_jsonl(path)
            path.write_bytes(bytes([0xFF]))
            with self.assertRaisesRegex(ValueError, "trace_file_invalid_utf8"):
                load_jsonl(path)


if __name__ == "__main__":
    unittest.main()
