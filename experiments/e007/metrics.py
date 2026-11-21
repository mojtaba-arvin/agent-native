import argparse
import json
import math
import statistics
from collections import defaultdict
from pathlib import Path


EVENT_TYPES = {
    "task_started", "tool_call", "model_usage", "repair",
    "human_intervention", "runtime_metric", "task_finished",
}
IDENTITY_FIELDS = ("run_id", "candidate_id", "model_id")
MAX_TRACE_BYTES = 64 * 1024 * 1024
INVALID_TOOL_FAILURES = {
    "UNKNOWN_TOOL", "TOOL_NAME", "ARGUMENT_SHAPE",
    "REQUEST_SHAPE", "REQUEST_ID", "REQUEST_FIELDS", "MESSAGE_TYPE",
    "INVALID_JSON", "INVALID_UTF8", "MESSAGE_TOO_LARGE",
    "DUPLICATE_JSON_KEY", "NON_FINITE_JSON_NUMBER",
    "ARGUMENT_FIELDS", "ARGUMENTS_REQUIRED", "ARGUMENT_TYPE",
}
SCHEMA_ARGUMENT_FAILURES = {
    "ARGUMENT_FIELDS", "ARGUMENTS_REQUIRED", "ARGUMENT_TYPE",
}
ALLOWED_FIELDS = {
    "event_id", "task_id", "attempt", "timestamp_ns", "event_type",
    *IDENTITY_FIELDS,
    "tool_name", "schema_lookup", "change_set_id", "validation_valid", "plan_valid",
    "plan_will_mutate", "plan_will_deploy", "input_tokens", "output_tokens", "cost_usd",
    "accepted", "eligible_for_acceptance", "failure_class", "metric_name", "metric_value",
    "metric_unit", "retry",
}


def summarize(events):
    seen = set()
    grouped = defaultdict(list)
    for event in events:
        required = {"event_id", "task_id", "attempt", "timestamp_ns", "event_type"}
        if not isinstance(event, dict) or not required.issubset(event):
            raise ValueError("trace_event_missing_required_fields")
        if event["event_type"] not in EVENT_TYPES:
            raise ValueError("unknown_event_type")
        unexpected = set(event) - ALLOWED_FIELDS
        if unexpected:
            raise ValueError(f"unexpected_trace_fields:{','.join(sorted(unexpected))}")
        for field in ("event_id", "task_id"):
            if not isinstance(event[field], str) or not event[field]:
                raise ValueError(f"invalid_{field}")
        for field in IDENTITY_FIELDS:
            if field in event and (
                not isinstance(event[field], str) or not event[field]
            ):
                raise ValueError(f"invalid_{field}")
        if not isinstance(event["attempt"], int) or isinstance(event["attempt"], bool) or event["attempt"] < 1:
            raise ValueError("invalid_attempt")
        if not isinstance(event["timestamp_ns"], int) or isinstance(event["timestamp_ns"], bool) or event["timestamp_ns"] < 0:
            raise ValueError("invalid_timestamp_ns")
        if "tool_name" in event and not isinstance(event["tool_name"], str):
            raise ValueError("invalid_tool_name")
        if "schema_lookup" in event and (event["event_type"] != "tool_call" or not isinstance(event["schema_lookup"], bool)):
            raise ValueError("invalid_schema_lookup")
        result_flag_tools = {
            "validation_valid": "service.validate",
            "plan_valid": "service.plan",
            "plan_will_mutate": "service.plan",
            "plan_will_deploy": "service.plan",
        }
        for flag, expected_tool in result_flag_tools.items():
            if flag in event and (
                event["event_type"] != "tool_call"
                or event.get("tool_name") != expected_tool
                or not isinstance(event[flag], bool)
            ):
                raise ValueError(f"invalid_{flag}")
        if event.get("schema_lookup", False) and event.get("tool_name") != "interface.describe":
            raise ValueError("schema_lookup_requires_interface_describe")
        if "change_set_id" in event:
            candidate_id = event["change_set_id"]
            if (
                not isinstance(candidate_id, str)
                or len(candidate_id) != 64
                or any(character not in "0123456789abcdef" for character in candidate_id)
            ):
                raise ValueError("invalid_change_set_id")
            if event["event_type"] != "tool_call" or event.get("tool_name") not in {"service.propose", "service.validate", "service.plan"}:
                raise ValueError("change_set_id_requires_proposal_lifecycle_tool")
        if event["event_type"] == "tool_call" and not event.get("tool_name"):
            raise ValueError("tool_call_missing_tool_name")
        if event["event_type"] == "task_finished" and not isinstance(event.get("accepted"), bool):
            raise ValueError("task_finished_missing_accepted")
        if "eligible_for_acceptance" in event and (
            event["event_type"] != "task_finished"
            or not isinstance(event["eligible_for_acceptance"], bool)
        ):
            raise ValueError("invalid_eligible_for_acceptance")
        if event["event_type"] == "task_finished" and event.get("accepted") is True and event.get("eligible_for_acceptance", True) is not True:
            raise ValueError("accepted_task_must_be_eligible")
        if "accepted" in event and not isinstance(event["accepted"], bool):
            raise ValueError("invalid_accepted")
        if "failure_class" in event and (not isinstance(event["failure_class"], str) or not event["failure_class"]):
            raise ValueError("invalid_failure_class")
        if "retry" in event and not isinstance(event["retry"], bool):
            raise ValueError("invalid_retry")
        if event["event_type"] == "runtime_metric":
            if not isinstance(event.get("metric_name"), str) or not event["metric_name"]:
                raise ValueError("runtime_metric_missing_name")
            if not isinstance(event.get("metric_unit"), str) or not event["metric_unit"]:
                raise ValueError("runtime_metric_missing_unit")
            value = event.get("metric_value")
            if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(value):
                raise ValueError("runtime_metric_invalid_value")
        token_fields = ("input_tokens", "output_tokens")
        for key in token_fields:
            if key in event:
                if event["event_type"] != "model_usage":
                    raise ValueError(f"{key}_requires_model_usage_event")
                if (
                    not isinstance(event[key], int)
                    or isinstance(event[key], bool)
                    or event[key] < 0
                ):
                    raise ValueError(f"invalid_{key}")
        if event["event_type"] == "model_usage" and any(
            key not in event for key in token_fields
        ):
            raise ValueError("model_usage_requires_token_counts")
        if "cost_usd" in event:
            if event["event_type"] != "model_usage":
                raise ValueError("cost_usd_requires_model_usage_event")
            if (
                not isinstance(event["cost_usd"], (int, float))
                or isinstance(event["cost_usd"], bool)
                or not math.isfinite(event["cost_usd"])
                or event["cost_usd"] < 0
            ):
                raise ValueError("invalid_cost_usd")
        if event["event_id"] in seen:
            raise ValueError("duplicate_event_id")
        seen.add(event["event_id"])
        # A task may be evaluated repeatedly or against multiple candidates.
        # Keep each run and attempt independent instead of merging their traces.
        group_key = (event.get("run_id", ""), event["task_id"], event["attempt"])
        grouped[group_key].append(event)

    tasks = []
    runtime_samples = defaultdict(list)
    runtime_units = {}
    for (run_id, task_id, attempt), rows in sorted(grouped.items()):
        rows.sort(key=lambda row: (row["timestamp_ns"], row["event_id"]))
        identity = {}
        for field in IDENTITY_FIELDS:
            values = {row[field] for row in rows if field in row}
            if len(values) > 1:
                raise ValueError(f"inconsistent_{field}_within_attempt")
            identity[field] = next(iter(values), None)

        model_events = [row for row in rows if row["event_type"] == "model_usage"]
        finishes = [row for row in rows if row["event_type"] == "task_finished"]
        if len(finishes) > 1:
            raise ValueError("multiple_task_finished_events")
        starts = [row["timestamp_ns"] for row in rows if row["event_type"] == "task_started"]
        finish = finishes[0] if finishes else None
        tool_call_rows = [
            row for row in rows if row["event_type"] == "tool_call"
        ]
        tool_error_classes = defaultdict(int)
        for row in tool_call_rows:
            failure_class = row.get("failure_class")
            if failure_class:
                tool_error_classes[failure_class] += 1
        tool_errors = sum(tool_error_classes.values())
        invalid_tool_calls = sum(
            count for failure_class, count in tool_error_classes.items()
            if failure_class in INVALID_TOOL_FAILURES
        )
        schema_argument_errors = sum(
            count for failure_class, count in tool_error_classes.items()
            if failure_class in SCHEMA_ARGUMENT_FAILURES
        )
        schema_lookup_calls = sum(row.get("schema_lookup", False) for row in tool_call_rows)

        token_usage_complete = bool(model_events) and all(
            "input_tokens" in row and "output_tokens" in row for row in model_events
        )
        cost_complete = bool(model_events) and all("cost_usd" in row for row in model_events)
        input_tokens = sum(row["input_tokens"] for row in model_events) if token_usage_complete else None
        output_tokens = sum(row["output_tokens"] for row in model_events) if token_usage_complete else None
        inference_cost = sum(row["cost_usd"] for row in model_events) if cost_complete else None
        eligible_for_acceptance = bool(finish.get("eligible_for_acceptance", True)) if finish else True
        accepted = bool(finish and finish.get("accepted", False))

        for row in rows:
            if row["event_type"] == "runtime_metric":
                name = row["metric_name"]
                unit = row["metric_unit"]
                if name in runtime_units and runtime_units[name] != unit:
                    raise ValueError(f"runtime_metric_unit_mismatch:{name}")
                runtime_units[name] = unit
                runtime_samples[name].append(row["metric_value"])

        tasks.append({
            "run_id": run_id or None,
            "task_id": task_id,
            "attempt": attempt,
            **identity,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "total_tokens": input_tokens + output_tokens if token_usage_complete else None,
            "token_usage_complete": token_usage_complete,
            "tool_calls": len(tool_call_rows),
            "tool_errors": tool_errors,
            "invalid_tool_calls": invalid_tool_calls,
            "schema_argument_errors": schema_argument_errors,
            "schema_lookup_calls": schema_lookup_calls,
            "tool_error_classes": dict(sorted(tool_error_classes.items())),
            "repair_events": sum(
                row["event_type"] == "repair" or row.get("retry", False) for row in rows
            ),
            "human_interventions": sum(row["event_type"] == "human_intervention" for row in rows),
            "inference_cost_usd": round(inference_cost, 8) if cost_complete else None,
            "cost_complete": cost_complete,
            "wall_clock_seconds": (
                max(0, finish["timestamp_ns"] - min(starts)) / 1_000_000_000
                if starts and finish else None
            ),
            "accepted": accepted,
            "eligible_for_acceptance": eligible_for_acceptance,
            "failure_class": None if accepted or not finish else finish.get("failure_class", "unspecified"),
            "cost_per_accepted_task_usd": (
                round(inference_cost, 8) if accepted and cost_complete else None
            ),
        })

    accepted_count = sum(row["accepted"] and row["eligible_for_acceptance"] for row in tasks)
    eligible_count = sum(row["eligible_for_acceptance"] for row in tasks)
    tokens_complete = bool(tasks) and all(row["token_usage_complete"] for row in tasks)
    costs_complete = bool(tasks) and all(row["cost_complete"] for row in tasks)
    total_cost = sum(row["inference_cost_usd"] for row in tasks) if costs_complete else None
    return {
        "task_count": len(tasks),
        "accepted_tasks": accepted_count,
        "eligible_task_count": eligible_count,
        "excluded_task_count": len(tasks) - eligible_count,
        "acceptance_rate": accepted_count / eligible_count if eligible_count else None,
        "token_usage_complete": tokens_complete,
        "cost_complete": costs_complete,
        "total_inference_cost_usd": round(total_cost, 8) if total_cost is not None else None,
        "cost_per_accepted_task_usd": (
            round(total_cost / accepted_count, 8)
            if total_cost is not None and accepted_count else None
        ),
        "totals": {
            "input_tokens": sum(row["input_tokens"] for row in tasks) if tokens_complete else None,
            "output_tokens": sum(row["output_tokens"] for row in tasks) if tokens_complete else None,
            "tool_calls": sum(row["tool_calls"] for row in tasks),
            "tool_errors": sum(row["tool_errors"] for row in tasks),
            "invalid_tool_calls": sum(row["invalid_tool_calls"] for row in tasks),
            "schema_argument_errors": sum(row["schema_argument_errors"] for row in tasks),
            "schema_lookup_calls": sum(row["schema_lookup_calls"] for row in tasks),
            "repair_events": sum(row["repair_events"] for row in tasks),
            "human_interventions": sum(row["human_interventions"] for row in tasks),
        },
        "runtime_metrics": {
            name: {
                "unit": runtime_units[name],
                "samples": len(values),
                "min": min(values),
                "median": statistics.median(values),
                "max": max(values),
            }
            for name, values in sorted(runtime_samples.items())
        },
        "tasks": tasks,
    }


def _reject_duplicate_json_keys(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate_json_key")
        result[key] = value
    return result


def _reject_non_finite_json_number(value):
    raise ValueError("non_finite_json_number")


def load_jsonl(path):
    trace_path = Path(path)
    try:
        if trace_path.stat().st_size > MAX_TRACE_BYTES:
            raise ValueError("trace_file_too_large")
        raw = trace_path.read_bytes()
    except ValueError:
        raise
    except OSError as error:
        raise ValueError("trace_file_unavailable") from error
    if len(raw) > MAX_TRACE_BYTES:
        raise ValueError("trace_file_too_large")
    try:
        lines = raw.decode("utf-8").splitlines()
    except UnicodeDecodeError as error:
        raise ValueError("trace_file_invalid_utf8") from error

    events = []
    for line_number, line in enumerate(lines, 1):
        if not line.strip():
            continue
        try:
            events.append(json.loads(
                line,
                object_pairs_hook=_reject_duplicate_json_keys,
                parse_constant=_reject_non_finite_json_number,
            ))
        except (json.JSONDecodeError, ValueError) as error:
            raise ValueError(f"invalid_jsonl_line:{line_number}") from error
    return events


def main():
    parser = argparse.ArgumentParser(description="Aggregate an Agent Native trace JSONL file.")
    parser.add_argument("--input", required=True, help="Path to raw provider-neutral JSONL trace.")
    parser.add_argument("--output", help="Optional output JSON path; defaults to stdout.")
    args = parser.parse_args()
    result = summarize(load_jsonl(args.input))
    encoded = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.output:
        Path(args.output).write_text(encoded, encoding="utf-8")
    else:
        print(encoded, end="")


if __name__ == "__main__":
    main()
