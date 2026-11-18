"""Catalog application handlers for the E-009 framework kernel."""

from __future__ import annotations

from kernel import DomainFault, HandlerContext, HandlerResult
from repository import (
    IdempotencyConflict,
    ItemConflict,
    SQLiteCatalogRepository,
)
from work_store import AuditCommitError, JobBackpressure, JobConflict, DurableWorkStore


def build_catalog_handlers(
    repository: SQLiteCatalogRepository,
    work_store: DurableWorkStore | None = None,
) -> dict:
    def create_item(context: HandlerContext) -> HandlerResult:
        try:
            item, replayed = repository.create_item(
                tenant_id=context.identity.tenant_id or "",
                name=str(context.values["name"]),
                idempotency_key=str(context.values["idempotency_key"]),
                now=context.now,
            )
        except IdempotencyConflict as error:
            raise DomainFault("Conflict", str(error)) from error
        except ItemConflict as error:
            raise DomainFault("Conflict", str(error)) from error
        return HandlerResult(
            data=item,
            status_code=200 if replayed else 201,
            headers={"Idempotency-Replayed": "true"} if replayed else {},
        )

    def get_item(context: HandlerContext) -> dict:
        item = repository.get_item(
            tenant_id=context.identity.tenant_id or "",
            item_id=str(context.values["id"]),
        )
        if item is None:
            raise DomainFault("NotFound", "item")
        return item

    def get_item_by_name(context: HandlerContext) -> dict:
        item = repository.get_item_by_name(
            tenant_id=context.identity.tenant_id or "",
            name=str(context.values["name"]),
        )
        if item is None:
            raise DomainFault("NotFound", "item")
        return item

    def submit_rebuild(context: HandlerContext) -> HandlerResult:
        if work_store is None:
            raise DomainFault("ServiceUnavailable", "durable_work_store_unavailable")
        try:
            job, replayed = work_store.submit_job(
                tenant_id=context.identity.tenant_id or "",
                task_type="catalog.rebuild",
                payload={
                    "requested_by": context.identity.principal_id,
                },
                idempotency_key=str(context.values["idempotency_key"]),
                now=context.now,
                deadline_at=context.now + 3600,
                max_attempts=3,
                audit_event=context.audit_event,
                audit_receipt=context.audit_receipt,
            )
        except AuditCommitError as error:
            raise DomainFault("ServiceUnavailable", "atomic_audit_commit_failed") from error
        except JobConflict as error:
            raise DomainFault("Conflict", str(error)) from error
        except JobBackpressure as error:
            raise DomainFault("RateLimited", str(error)) from error
        return HandlerResult(
            data={"id": job["task_id"], "state": job["state"]},
            status_code=200 if replayed else 202,
            headers={"Idempotency-Replayed": "true"} if replayed else {},
        )

    def get_job(context: HandlerContext) -> dict:
        if work_store is None:
            raise DomainFault("ServiceUnavailable", "durable_work_store_unavailable")
        job = work_store.get_job(
            tenant_id=context.identity.tenant_id or "",
            task_id=str(context.values["id"]),
        )
        if job is None:
            raise DomainFault("NotFound", "job")
        return {"id": job["task_id"], "state": job["state"]}

    def cancel_job(context: HandlerContext) -> HandlerResult:
        if work_store is None:
            raise DomainFault("ServiceUnavailable", "durable_work_store_unavailable")
        job = work_store.cancel_job(
            tenant_id=context.identity.tenant_id or "",
            task_id=str(context.values["id"]),
            now=context.now,
        )
        if job is None:
            raise DomainFault("NotFound", "job")
        status = 202 if job["state"] == "cancellation_requested" else 200
        return HandlerResult(
            data={"id": job["task_id"], "state": job["state"]},
            status_code=status,
        )

    return {
        "create_item": create_item,
        "get_item": get_item,
        "get_item_by_name": get_item_by_name,
        "submit_rebuild": submit_rebuild,
        "get_job": get_job,
        "cancel_job": cancel_job,
    }
