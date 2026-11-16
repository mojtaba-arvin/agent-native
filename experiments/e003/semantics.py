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


@dataclass(frozen=True)
class Submission:
    status: str
    task_id: str | None


class Engine:
    def __init__(self, *, max_outstanding: int, max_concurrency: int):
        if max_outstanding < 1 or max_concurrency < 1:
            raise ValueError("limits must be positive")
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
        if ttl < 1 or max_attempts < 1:
            raise ValueError("ttl and max_attempts must be positive")
        if idempotency_key in self.keys:
            return Submission("deduplicated", self.keys[idempotency_key])
        if not self.accepting:
            return Submission("shutting_down", None)
        if task_id in self.tasks:
            raise ValueError(f"task id already exists: {task_id}")
        active = sum(t.status in {"queued", "running"} for t in self.tasks.values())
        if active >= self.max_outstanding:
            return Submission("backpressure", None)
        task = Task(task_id, idempotency_key, self.now + ttl, max_attempts)
        self.tasks[task_id] = task
        self.keys[idempotency_key] = task_id
        self.queue.append(task_id)
        return Submission("accepted", task_id)

    def start(self, worker_id: str) -> str | None:
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
        if outcome not in {"ok", "transient", "fatal"}:
            raise ValueError(f"unsupported outcome: {outcome}")
        if worker_id not in self.workers:
            raise ValueError(f"worker is not running a task: {worker_id}")
        task_id = self.workers.pop(worker_id)
        task = self.tasks[task_id]
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
        task = self.tasks[task_id]
        if task.status not in {"queued", "running"}:
            return False
        task.status = "cancelled"
        for worker_id, active_id in list(self.workers.items()):
            if active_id == task_id:
                del self.workers[worker_id]
        return True

    def crash(self, worker_id: str) -> str:
        if worker_id not in self.workers:
            raise ValueError(f"worker is not running a task: {worker_id}")
        task_id = self.workers.pop(worker_id)
        task = self.tasks[task_id]
        if task.deadline <= self.now:
            task.status = "expired"
        elif task.attempts < task.max_attempts:
            task.status = "queued"
            self.queue.appendleft(task_id)
        else:
            task.status = "failed"
        return task.status

    def advance(self, ticks: int = 1) -> None:
        if ticks < 0:
            raise ValueError("time cannot move backwards")
        self.now += ticks
        for task in self.tasks.values():
            if task.status in {"queued", "running"} and task.deadline <= self.now:
                task.status = "expired"
        for worker_id, task_id in list(self.workers.items()):
            if self.tasks[task_id].status == "expired":
                del self.workers[worker_id]

    def shutdown(self, *, graceful: bool = True) -> bool:
        """Stop admission; optionally cancel all outstanding work immediately."""
        self.accepting = False
        if not graceful:
            for task in self.tasks.values():
                if task.status in {"queued", "running"}:
                    task.status = "cancelled"
            self.workers.clear()
        return self.is_drained()

    def is_drained(self) -> bool:
        return not any(task.status in {"queued", "running"} for task in self.tasks.values())
