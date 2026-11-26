"""Isolated E-010 demo apply adapter; never connects to production services."""

from __future__ import annotations

import sys
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
E009_ROOT = ROOT / "experiments" / "e009"
E004_ROOT = ROOT / "experiments" / "e004"
for candidate in (E004_ROOT, E009_ROOT):
    if str(candidate) not in sys.path:
        sys.path.insert(0, str(candidate))

from audit import SQLiteAuditSink
from catalog import build_catalog_handlers
from kernel import DomainFault, ServiceRuntime, load_service_ir
from repository import SQLiteCatalogRepository
from security_model import Grant, RequestContext
from interface import digest

TRUSTED_EFFECTS = {
    "repository.read", "repository.write", "queue.submit", "queue.read", "queue.cancel"
}
NEW_OPERATION = {
    "name": "get_item_by_normalized_name",
    "method": "GET",
    "path": "/items/by-normalized-name/{name}",
    "input": [{"name": "name", "source": "path", "type": "String"}],
    "output": "Item",
    "errors": ["InvalidInput", "NotFound", "Unauthorized"],
    "validation": ["name.non_empty"],
    "effects": ["repository.read"],
    "capability": "items.read",
}


class SandboxApplyCoordinator:
    """Publishes one validated demo runtime at a time inside a private directory.

    The lock and idempotency cache are process-local. They are not a cross-process
    lock, a filesystem sandbox, or a production deployment boundary.
    """

    def __init__(self, root: str | Path):
        self.root = Path(root).expanduser().resolve()
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.now = 1_800_000_000
        self.repository = SQLiteCatalogRepository(self.root / "catalog.sqlite")
        self.audit_sink = SQLiteAuditSink(self.root / "audit.sqlite")
        self.initial_ir = load_service_ir((E009_ROOT / "catalog.an").read_text(encoding="utf-8"))
        self.repository.create_item(
            tenant_id="demo-tenant",
            name="blue-lamp",
            idempotency_key="e010-seed-item",
            now=self.now,
        )
        self.identity = RequestContext(
            principal_id="demo-agent",
            tenant_id="demo-tenant",
            now=self.now,
            grants=(Grant(
                principal_id="demo-agent",
                tenant_id="demo-tenant",
                capability="items.read",
            ),),
        )
        self.runtime = self._build_runtime(self.initial_ir)
        self.applied_revision: str | None = None
        self._applied_result: dict | None = None
        self._apply_lock = threading.RLock()

    def _get_item_by_normalized_name(self, context):
        normalized = str(context.values["name"]).strip().casefold()
        item = self.repository.get_item_by_name(
            tenant_id=context.identity.tenant_id or "",
            name=normalized,
        )
        if item is None:
            raise DomainFault("NotFound", "item")
        return item

    def _build_runtime(self, ir: dict, *, audit_sink=None) -> ServiceRuntime:
        handlers = build_catalog_handlers(self.repository)
        if any(item.get("name") == NEW_OPERATION["name"] for item in ir["operations"]):
            handlers[NEW_OPERATION["name"]] = self._get_item_by_normalized_name
        return ServiceRuntime(
            ir,
            handlers=handlers,
            repository=self.repository,
            trusted_effects=TRUSTED_EFFECTS,
            clock=lambda: self.now,
            audit_sink=self.audit_sink if audit_sink is None else (None if audit_sink is False else audit_sink),
        )

    def apply(self, proposal: dict, context: dict) -> dict:
        # Serialize validation, smoke, audit, and publication. A same-revision
        # contender observes the committed result instead of publishing twice.
        with self._apply_lock:
            return self._apply_locked(proposal, context)

    def _apply_locked(self, proposal: dict, context: dict) -> dict:
        ir = proposal.get("ir")
        if not isinstance(ir, dict) or not isinstance(ir.get("operations"), list):
            raise ValueError("sandbox_apply_ir_missing")
        if (
            proposal.get("service_id") != "catalog"
            or proposal.get("base_revision") != digest(self.initial_ir)
        ):
            raise ValueError("sandbox_apply_base_identity_mismatch")

        expected_ir = {
            **self.initial_ir,
            "operations": [*self.initial_ir["operations"], NEW_OPERATION],
        }
        if ir != expected_ir:
            raise ValueError("sandbox_apply_contract_not_preserved")

        revision = digest(ir)
        if self.applied_revision == revision and self._applied_result is not None:
            return {**self._applied_result, "replayed": True}

        request_id = context.get("request_id")
        if not isinstance(request_id, str) or not request_id:
            raise ValueError("sandbox_apply_request_id_required")

        # Smoke the candidate without writing an audit record. A failed
        # candidate must not look like an applied revision in the durable log.
        candidate_runtime = self._build_runtime(ir, audit_sink=False)
        smoke = candidate_runtime.dispatch(
            "GET",
            "/items/by-normalized-name/BLUE-LAMP",
            {},
            self.identity,
            request_id=f"{request_id}-runtime-smoke",
        )
        if smoke.status_code != 200 or smoke.body.get("data", {}).get("name") != "blue-lamp":
            raise ValueError("sandbox_runtime_smoke_test_failed")

        published_runtime = self._build_runtime(ir)
        published_smoke = published_runtime.dispatch(
            "GET",
            "/items/by-normalized-name/BLUE-LAMP",
            {},
            self.identity,
            request_id=f"{request_id}-runtime-smoke",
        )
        if published_smoke.status_code != 200 or published_smoke.body.get("data", {}).get("name") != "blue-lamp":
            raise ValueError("sandbox_runtime_smoke_test_failed")

        self.audit_sink({
            "principal_id": self.identity.principal_id,
            "tenant_id": self.identity.tenant_id,
            "operation": "service.apply",
            "resource": "catalog",
            "requested_effects": ["service.apply"],
            "decision": "allow",
            "reason_code": "ISOLATED_SANDBOX_APPLY",
            "request_id": request_id,
            "timestamp": self.now,
        })
        # These assignments occur under the same process-local lock.
        self.runtime = published_runtime
        self.applied_revision = revision
        result = {
            "applied": True,
            "sandbox_only": True,
            "revision": revision,
            "runtime_smoke_test": {"status_code": smoke.status_code, "body": smoke.body},
            "audit_event_count": len(self.audit_sink.list_events()),
            "apply_request_id": request_id,
            "runtime_request_id": f"{request_id}-runtime-smoke",
            "replayed": False,
        }
        self._applied_result = result
        return dict(result)
