from collections import defaultdict


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
