"""Catalog application handlers for the E-009 framework kernel."""

from __future__ import annotations

from kernel import DomainFault, HandlerContext, HandlerResult
from repository import (
    IdempotencyConflict,
    ItemConflict,
    SQLiteCatalogRepository,
)


def build_catalog_handlers(repository: SQLiteCatalogRepository) -> dict:
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

    return {
        "create_item": create_item,
        "get_item": get_item,
        "get_item_by_name": get_item_by_name,
    }
