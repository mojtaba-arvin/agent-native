"""Reference worker and outbox relay for the integrated E-009 kernel.

The worker is deliberately explicit: claim, execute, acknowledge. Lease tokens
are required for completion. A stop request does not free a lease until the
supervisor confirms that the worker has stopped.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from repository import SQLiteCatalogRepository
from work_store import DurableWorkStore


@dataclass(frozen=True)
class WorkerResult:
    claimed: bool
    task_id: str | None
    state: str | None
    result: dict | None = None


class CatalogWorker:
    """Executes only the registered Catalog task types."""

    def __init__(
        self,
        repository: SQLiteCatalogRepository,
        work_store: DurableWorkStore,
        *,
        lease_seconds: int = 30,
    ):
        if type(lease_seconds) is not int or lease_seconds < 1:
            raise ValueError("lease_seconds_must_be_positive_integer")
        self.repository = repository
        self.work_store = work_store
        self.lease_seconds = lease_seconds

    def run_once(self, *, worker_id: str, now: int) -> WorkerResult:
        job = self.work_store.claim_job(
            worker_id=worker_id,
            now=now,
            lease_seconds=self.lease_seconds,
        )
        if job is None:
            return WorkerResult(False, None, None)

        task_id = job["task_id"]
        token = job["lease_token"]
        try:
            if job["task_type"] != "catalog.rebuild":
                completed = self.work_store.fail_job(
                    task_id=task_id,
                    worker_id=worker_id,
                    lease_token=token,
                    now=now,
                    error_code="UNKNOWN_TASK_TYPE",
                )
                return WorkerResult(True, task_id, completed["state"])
            items = self.repository.list_items(tenant_id=job["tenant_id"])
            result = {
                "items_seen": len(items),
                "item_ids": [item["id"] for item in items],
            }
            completed = self.work_store.complete_job(
                task_id=task_id,
                worker_id=worker_id,
                lease_token=token,
                now=now,
                result=result,
            )
            return WorkerResult(True, task_id, completed["state"], result)
        except Exception as error:
            # A stale/fenced lease is not retried here: the job state is owned
            # by the newer worker/supervisor and must remain untouched.
            from work_store import StaleJobLease
            if isinstance(error, StaleJobLease):
                raise
            failed = self.work_store.fail_job(
                task_id=task_id,
                worker_id=worker_id,
                lease_token=token,
                now=now,
                error_code=type(error).__name__.upper(),
            )
            return WorkerResult(True, task_id, failed["state"])


@dataclass(frozen=True)
class RelayResult:
    claimed: bool
    event_id: str | None
    duplicate: bool | None
    total: int | None
    acknowledged: bool


class OutboxRelay:
    """At-least-once relay with an idempotent local Inbox consumer."""

    def __init__(
        self,
        work_store: DurableWorkStore,
        *,
        consumer_id: str = "catalog-observer",
        lease_seconds: int = 15,
    ):
        if type(lease_seconds) is not int or lease_seconds < 1:
            raise ValueError("relay_lease_seconds_must_be_positive_integer")
        if not isinstance(consumer_id, str) or not consumer_id.strip():
            raise ValueError("consumer_id_required")
        self.work_store = work_store
        self.consumer_id = consumer_id
        self.lease_seconds = lease_seconds

    def run_once(
        self,
        *,
        relay_id: str,
        now: int,
        acknowledge: bool = True,
    ) -> RelayResult:
        event = self.work_store.claim_outbox(
            relay_id=relay_id,
            now=now,
            lease_seconds=self.lease_seconds,
        )
        if event is None:
            return RelayResult(False, None, None, None, False)
        consumed = self.work_store.consume_delta_event(
            consumer_id=self.consumer_id,
            event_id=event["event_id"],
            payload=event["payload"],
            now=now,
        )
        if acknowledge:
            self.work_store.ack_outbox(
                event_id=event["event_id"],
                relay_id=relay_id,
                lease_token=event["lease_token"],
                now=now,
            )
        return RelayResult(
            True,
            event["event_id"],
            consumed["duplicate"],
            consumed["total"],
            acknowledge,
        )
