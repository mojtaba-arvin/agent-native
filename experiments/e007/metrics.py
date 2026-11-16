import argparse
import json
from collections import defaultdict
from pathlib import Path


EVENT_TYPES = {"task_started", "tool_call", "model_usage", "repair", "human_intervention", "runtime_metric", "task_finished"}


def summarize(events):
    seen = set()
    grouped = defaultdict(list)
    for event in events:
        required = {"event_id", "task_id", "attempt", "timestamp_ns", "event_type"}
        if not isinstance(event, dict) or not required.issubset(event):
            raise ValueError("trace_event_missing_required_fields")
        if event["event_type"] not in EVENT_TYPES:
            raise ValueError("unknown_event_type")
        if not isinstance(event["event_id"], str) or not event["event_id"] or not isinstance(event["task_id"], str) or not event["task_id"]:
            raise ValueError("invalid_event_or_task_id")
        if not isinstance(event["attempt"], int) or event["attempt"] < 1:
            raise ValueError("invalid_attempt")
        for key in ("input_tokens", "output_tokens"):
            if key in event and (not isinstance(event[key], int) or event[key] < 0):
                raise ValueError(f"invalid_{key}")
        if "cost_usd" in event and (not isinstance(event["cost_usd"], (int, float)) or event["cost_usd"] < 0):
            raise ValueError("invalid_cost_usd")
        if event["event_type"] == "tool_call" and not event.get("tool_name"):
            raise ValueError("tool_call_missing_tool_name")
        if event["event_type"] == "task_finished" and not isinstance(event.get("accepted"), bool):
            raise ValueError("task_finished_missing_accepted")
        if event["event_id"] in seen:
            raise ValueError("duplicate_event_id")
        if not isinstance(event["timestamp_ns"], int) or event["timestamp_ns"] < 0:
            raise ValueError("invalid_timestamp_ns")
        seen.add(event["event_id"])
        grouped[event["task_id"]].append(event)

    tasks = []
    for task_id, rows in sorted(grouped.items()):
        rows.sort(key=lambda row: (row["timestamp_ns"], row["event_id"]))
        model = [row for row in rows if row["event_type"] == "model_usage"]
        finishes = [row for row in rows if row["event_type"] == "task_finished"]
        if len(finishes) > 1:
            raise ValueError("multiple_task_finished_events")
        start = [row["timestamp_ns"] for row in rows if row["event_type"] == "task_started"]
        finish = finishes[0] if finishes else None
        input_tokens = sum(row.get("input_tokens", 0) for row in model)
        output_tokens = sum(row.get("output_tokens", 0) for row in model)
        cost = sum(row.get("cost_usd", 0.0) for row in model)
        accepted = bool(finish and finish.get("accepted", False))
        tasks.append({
            "task_id": task_id,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "total_tokens": input_tokens + output_tokens,
            "tool_calls": sum(row["event_type"] == "tool_call" for row in rows),
            "repair_events": sum(row["event_type"] == "repair" or row.get("retry", False) for row in rows),
            "human_interventions": sum(row["event_type"] == "human_intervention" for row in rows),
            "inference_cost_usd": round(cost, 8),
            "wall_clock_seconds": max(0, finish["timestamp_ns"] - min(start)) / 1e9 if start and finish else None,
            "accepted": accepted,
            "failure_class": None if accepted or not finish else finish.get("failure_class", "unspecified"),
            "cost_per_accepted_task_usd": round(cost, 8) if accepted else None,
        })
    accepted_count = sum(row["accepted"] for row in tasks)
    total_cost = sum(row["inference_cost_usd"] for row in tasks)
    return {
        "task_count": len(tasks),
        "accepted_tasks": accepted_count,
        "acceptance_rate": accepted_count / len(tasks) if tasks else 0.0,
        "total_inference_cost_usd": round(total_cost, 8),
        "cost_per_accepted_task_usd": round(total_cost / accepted_count, 8) if accepted_count else None,
        "totals": {
            "input_tokens": sum(row["input_tokens"] for row in tasks),
            "output_tokens": sum(row["output_tokens"] for row in tasks),
            "tool_calls": sum(row["tool_calls"] for row in tasks),
            "repair_events": sum(row["repair_events"] for row in tasks),
            "human_interventions": sum(row["human_interventions"] for row in tasks),
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
    encoded = json.dumps(result, indent=2, sort_keys=True) + "\\n"
    if args.output:
        Path(args.output).write_text(encoded, encoding="utf-8")
    else:
        print(encoded, end="")


if __name__ == "__main__":
    main()
