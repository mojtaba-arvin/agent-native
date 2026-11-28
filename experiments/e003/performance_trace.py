"""Emit a deterministic logical scheduling trace for the E-003 reference model.

This is a queueing/concurrency trace, not a wall-clock throughput benchmark.
"""
from __future__ import annotations

import json
import math
from typing import Any

from semantics import Engine


def _nearest_rank(values: list[int], percentile: int) -> int:
    ordered = sorted(values)
    return ordered[max(0, math.ceil(percentile * len(ordered) / 100) - 1)]


def run_trace(*, task_count: int = 16, concurrency: int = 4) -> dict[str, Any]:
    if not isinstance(task_count, int) or isinstance(task_count, bool) or task_count < 1:
        raise ValueError("invalid_task_count")
    if (not isinstance(concurrency, int) or isinstance(concurrency, bool)
            or concurrency < 1 or concurrency > task_count):
        raise ValueError("invalid_concurrency")
    engine = Engine(max_outstanding=task_count, max_concurrency=concurrency)
    events: list[dict[str, Any]] = []
    submitted_at: dict[str, int] = {}
    queue_wait: list[int] = []
    for index in range(task_count):
        task_id = f"task-{index:04d}"
        result = engine.submit(task_id, f"key-{index:04d}", ttl=task_count + 1)
        if result.status != "accepted":
            raise RuntimeError(f"unexpected_admission:{result.status}")
        submitted_at[task_id] = engine.now
        events.append({"tick": engine.now, "event": "accepted", "task_id": task_id})

    completed = 0
    max_active = 0
    while completed < task_count:
        active: list[tuple[str, str]] = []
        for worker_index in range(concurrency):
            worker_id = f"worker-{worker_index:02d}"
            task_id = engine.start(worker_id)
            if task_id is not None:
                active.append((worker_id, task_id))
                queue_wait.append(engine.now - submitted_at[task_id])
                events.append({
                    "tick": engine.now, "event": "started",
                    "task_id": task_id, "worker_id": worker_id,
                })
        max_active = max(max_active, len(active))
        if not active:
            raise RuntimeError("trace_stalled")
        engine.advance(1)
        for worker_id, task_id in active:
            status = engine.finish(worker_id, "ok", result="ok")
            if status != "completed":
                raise RuntimeError(f"unexpected_completion:{status}")
            completed += 1
            events.append({
                "tick": engine.now, "event": "completed",
                "task_id": task_id, "worker_id": worker_id,
            })

    return {
        "schema_version": 1,
        "reference_only": True,
        "measurement": "logical_ticks_not_wall_clock",
        "workload": {"tasks": task_count, "worker_limit": concurrency},
        "result": {
            "accepted": task_count,
            "completed": completed,
            "attempts": sum(task.attempts for task in engine.tasks.values()),
            "max_observed_concurrency": max_active,
            "logical_duration_ticks": engine.now,
            "queue_wait_ticks_p50": _nearest_rank(queue_wait, 50),
            "queue_wait_ticks_p99": _nearest_rank(queue_wait, 99),
        },
        "events": events,
    }


if __name__ == "__main__":
    print(json.dumps(run_trace(), sort_keys=True, separators=(",", ":")))
