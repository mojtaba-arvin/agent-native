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
ALLOWED_FIELDS = {
    "event_id", "task_id", "attempt", "timestamp_ns", "event_type",
    "tool_name", "input_tokens", "output_tokens", "cost_usd",
    "accepted", "failure_class", "metric_name", "metric_value",
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
        if not isinstance(event["event_id"], str) or not event["event_id"]:
            raise ValueError("invalid_event_id")
        if not isinstance(event["task_id"], str) or not event["task_id"]:
            raise ValueError("invalid_task_id")
        if not isinstance(event["attempt"], int) or isinstance(event["attempt"], bool) or event["attempt"] < 1:
            raise ValueError("invalid_attempt")
        if not isinstance(event["timestamp_ns"], int) or isinstance(event["timestamp_ns"], bool) or event["timestamp_ns"] < 0:
            raise ValueError("invalid_timestamp_ns")
        if "tool_name" in event and not isinstance(event["tool_name"], str):
            raise ValueError("invalid_tool_name")
        if event["event_type"] == "tool_call" and not event.get("tool_name"):
            raise ValueError("tool_call_missing_tool_name")
        if event["event_type"] == "task_finished" and not isinstance(event.get("accepted"), bool):
            raise ValueError("task_finished_missing_accepted")
        if "failure_class" in event and not isinstance(event["failure_class"], str):
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
        for key in ("input_tokens", "output_tokens"):
            if key in event and (
                not isinstance(event[key], int) or isinstance(event[key], bool) or event[key] < 0
            ):
                raise ValueError(f"invalid_{key}")
        if "cost_usd" in event and (
            not isinstance(event["cost_usd"], (int, float))
            or isinstance(event["cost_usd"], bool)
            or not math.isfinite(event["cost_usd"])
            or event["cost_usd"] < 0
        ):
            raise ValueError("invalid_cost_usd")
        if event["event_id"] in seen:
            raise ValueError("duplicate_event_id")
        seen.add(event["event_id"])
        grouped[event["task_id"]].append(event)

    tasks = []
    runtime_samples = defaultdict(list)
    runtime_units = {}
    for task_id, rows in sorted(grouped.items()):
        rows.sort(key=lambda row: (row["timestamp_ns"], row["event_id"]))
        model_events = [row for row in rows if row["event_type"] == "model_usage"]
        finishes = [row for row in rows if row["event_type"] == "task_finished"]
        if len(finishes) > 1:
            raise ValueError("multiple_task_finished_events")
        starts = [row["timestamp_ns"] for row in rows if row["event_type"] == "task_started"]
        finish = finishes[0] if finishes else None

        token_usage_complete = bool(model_events) and all(
            "input_tokens" in row and "output_tokens" in row for row in model_events
        )
        cost_complete = bool(model_events) and all("cost_usd" in row for row in model_events)
        input_tokens = (
            sum(row["input_tokens"] for row in model_events)
            if token_usage_complete else None
        )
        output_tokens = (
            sum(row["output_tokens"] for row in model_events)
            if token_usage_complete else None
        )
        inference_cost = (
            sum(row["cost_usd"] for row in model_events)
            if cost_complete else None
        )
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
            "task_id": task_id,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "total_tokens": input_tokens + output_tokens if token_usage_complete else None,
            "token_usage_complete": token_usage_complete,
            "tool_calls": sum(row["event_type"] == "tool_call" for row in rows),
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
            "failure_class": None if accepted or not finish else finish.get("failure_class", "unspecified"),
            "cost_per_accepted_task_usd": (
                round(inference_cost, 8) if accepted and cost_complete else None
            ),
        })

    accepted_count = sum(row["accepted"] for row in tasks)
    tokens_complete = bool(tasks) and all(row["token_usage_complete"] for row in tasks)
    costs_complete = bool(tasks) and all(row["cost_complete"] for row in tasks)
    total_cost = sum(row["inference_cost_usd"] for row in tasks) if costs_complete else None
    return {
        "task_count": len(tasks),
        "accepted_tasks": accepted_count,
        "acceptance_rate": accepted_count / len(tasks) if tasks else 0.0,
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


def load_jsonl(path):
    events = []
    for line_number, line in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError as error:
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
