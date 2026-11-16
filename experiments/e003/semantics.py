"""Deterministic reference model for E-003; not a production runtime."""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import Literal


Outcome = Literal["ok", "transient", "fatal"]


@dataclass
class Task:
    task_id: str
    idempotency_key: str
    deadline: int
    max_attempts: int
    attempts: int = 0
    status: str = "queued"
    result: str | None = None
    terminal_after_stop: str | None = None


@dataclass(frozen=True)
class Submission:
    status: str
    task_id: str | None


def _require_text(value: object, name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"invalid_{name}")


def _require_int(value: object, name: str, *, minimum: int = 0) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or value < minimum:
        raise ValueError(f"invalid_{name}")


class Engine:
    def __init__(self, *, max_outstanding: int, max_concurrency: int):
        _require_int(max_outstanding, "max_outstanding", minimum=1)
        _require_int(max_concurrency, "max_concurrency", minimum=1)
        if max_concurrency > max_outstanding:
            raise ValueError("max_concurrency cannot exceed max_outstanding")
        self.max_outstanding = max_outstanding
        self.max_concurrency = max_concurrency
        self.now = 0
        self.queue: deque[str] = deque()
        self.tasks: dict[str, Task] = {}
        self.workers: dict[str, str] = {}
        self.keys: dict[str, str] = {}
        self.completed_keys: set[str] = set()
        self.accepting = True

    def submit(
        self, task_id: str, idempotency_key: str, *, ttl: int, max_attempts: int = 1
    ) -> Submission:
        _require_text(task_id, "task_id")
        _require_text(idempotency_key, "idempotency_key")
        _require_int(ttl, "ttl", minimum=1)
        _require_int(max_attempts, "max_attempts", minimum=1)
        if idempotency_key in self.keys:
            return Submission("deduplicated", self.keys[idempotency_key])
        if not self.accepting:
            return Submission("shutting_down", None)
        if task_id in self.tasks:
            raise ValueError(f"task id already exists: {task_id}")
        active = sum(t.status in {"queued", "running", "cancelling"} for t in self.tasks.values())
        if active >= self.max_outstanding:
            return Submission("backpressure", None)
        task = Task(task_id, idempotency_key, self.now + ttl, max_attempts)
        self.tasks[task_id] = task
        self.keys[idempotency_key] = task_id
        self.queue.append(task_id)
        return Submission("accepted", task_id)

    def start(self, worker_id: str) -> str | None:
        _require_text(worker_id, "worker_id")
        if worker_id in self.workers or len(self.workers) >= self.max_concurrency:
            return None
        while self.queue:
            task_id = self.queue.popleft()
            task = self.tasks[task_id]
            if task.status != "queued":
                continue
            if task.deadline <= self.now:
                task.status = "expired"
                continue
            task.attempts += 1
            task.status = "running"
            self.workers[worker_id] = task_id
            return task_id
        return None

    def finish(self, worker_id: str, outcome: Outcome, *, result: str | None = None) -> str:
        _require_text(worker_id, "worker_id")
        if not isinstance(outcome, str) or outcome not in {"ok", "transient", "fatal"}:
            raise ValueError("unsupported_outcome")
        if result is not None and not isinstance(result, str):
            raise ValueError("invalid_result")
        if worker_id not in self.workers:
            raise ValueError(f"worker is not running a task: {worker_id}")
        task_id = self.workers.pop(worker_id)
        task = self.tasks[task_id]
        if task.status == "cancelling":
            task.status = task.terminal_after_stop or "cancelled"
            task.terminal_after_stop = None
            return task.status
        if task.deadline <= self.now:
            task.status = "expired"
        elif outcome == "ok":
            task.status = "completed"
            task.result = result
            self.completed_keys.add(task.idempotency_key)
        elif outcome == "transient" and task.attempts < task.max_attempts:
            task.status = "queued"
            self.queue.appendleft(task_id)
        else:
            task.status = "failed"
        return task.status

    def cancel(self, task_id: str) -> bool:
        _require_text(task_id, "task_id")
        task = self.tasks[task_id]
        if task.status not in {"queued", "running"}:
            return False
        if task.status == "queued":
            task.status = "cancelled"
        else:
            task.status = "cancelling"
            task.terminal_after_stop = "cancelled"
        return True

    def crash(self, worker_id: str) -> str:
        _require_text(worker_id, "worker_id")
        if worker_id not in self.workers:
            raise ValueError(f"worker is not running a task: {worker_id}")
        task_id = self.workers.pop(worker_id)
        task = self.tasks[task_id]
        if task.status == "cancelling":
            task.status = task.terminal_after_stop or "cancelled"
            task.terminal_after_stop = None
        elif task.deadline <= self.now:
            task.status = "expired"
        elif task.attempts < task.max_attempts:
            task.status = "queued"
            self.queue.appendleft(task_id)
        else:
            task.status = "failed"
        return task.status

    def advance(self, ticks: int = 1) -> None:
        _require_int(ticks, "ticks")
        self.now += ticks
        for task in self.tasks.values():
            if task.status == "queued" and task.deadline <= self.now:
                task.status = "expired"
            elif task.status == "running" and task.deadline <= self.now:
                task.status = "cancelling"
                task.terminal_after_stop = "expired"

    def shutdown(self, *, graceful: bool = True) -> bool:
        """Stop admission; optionally cancel all outstanding work immediately."""
        if not isinstance(graceful, bool):
            raise ValueError("invalid_graceful_shutdown_flag")
        self.accepting = False
        if not graceful:
            for task in self.tasks.values():
                if task.status == "queued":
                    task.status = "cancelled"
                elif task.status == "running":
                    task.status = "cancelling"
                    task.terminal_after_stop = "cancelled"
        return self.is_drained()

    def is_drained(self) -> bool:
        return not self.workers and not any(
            task.status in {"queued", "running", "cancelling"}
            for task in self.tasks.values()
        )
