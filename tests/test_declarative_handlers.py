from __future__ import annotations

import unittest
from dataclasses import replace
from pathlib import Path
from types import MappingProxyType

from agent_native import (
    ConfigurationError,
    Grant,
    RequestContext,
    RuntimeAdapters,
    ServiceRegistry,
    build_service_runtime,
    built_in_handler_registry,
)

ROOT = Path(__file__).resolve().parents[1]
SERVICES = ROOT / "services"
HANDLERS = built_in_handler_registry()
REGISTRY = ServiceRegistry(SERVICES, trusted_handler_ids=HANDLERS.handler_ids)
NOW = 1_800_000_000
ITEM_ID = "00000000-0000-0000-0000-000000000001"
JOB_ID = "00000000-0000-0000-0000-000000000002"


class FakeRepository:
    def __init__(self):
        self.records = {}
        self.calls = []

    def read(self, resource, key, *, tenant_id):
        self.calls.append(("read", resource, tenant_id))
        return self.records.get((resource, tenant_id, key))

    def read_by_field(self, resource, field, value, *, tenant_id):
        self.calls.append(("read_by_field", resource, tenant_id))
        for (stored_resource, stored_tenant, _), record in self.records.items():
            if stored_resource == resource and stored_tenant == tenant_id and record.get(field) == value:
                return dict(record)
        return None

    def create(self, resource, payload, *, tenant_id, idempotency_key=None):
        self.calls.append(("create", resource, tenant_id, idempotency_key))
        key = ITEM_ID if resource == "items" else payload["sku"]
        record = ({"id": key, **payload} if resource == "items" else dict(payload))
        self.records[(resource, tenant_id, key)] = record
        return dict(record)

    def update(self, resource, key, payload, *, tenant_id):
        self.calls.append(("update", resource, tenant_id))
        record = self.records.get((resource, tenant_id, key))
        if record is None:
            return None
        record.update(payload)
        return dict(record)

    def delete(self, resource, key, *, tenant_id):
        self.calls.append(("delete", resource, tenant_id))
        return self.records.pop((resource, tenant_id, key), None) is not None


class FakeJobs:
    def __init__(self):
        self.jobs = {}
        self.calls = []

    def submit(self, queue, payload, *, tenant_id, idempotency_key, request_id):
        self.calls.append(("submit", queue, tenant_id, idempotency_key))
        result = {"id": JOB_ID, "state": "queued"}
        self.jobs[(queue, tenant_id, JOB_ID)] = result
        return result

    def get(self, queue, job_id, *, tenant_id):
        self.calls.append(("get", queue, tenant_id))
        return self.jobs.get((queue, tenant_id, job_id))

    def cancel(self, queue, job_id, *, tenant_id):
        self.calls.append(("cancel", queue, tenant_id))
        job = self.jobs.get((queue, tenant_id, job_id))
        if job is None:
            return None
        job["state"] = "cancelled"
        return dict(job)


class FakeEvents:
    def __init__(self):
        self.events = []

    def publish(self, event_type, payload, *, tenant_id, request_id):
        event = {"id": ITEM_ID, "state": "published", "type": event_type, "tenant_id": tenant_id, "payload": payload}
        self.events.append(event)
        return {"id": event["id"], "state": event["state"]}


def identity(tenant_id: str, capability: str, prefix: str) -> RequestContext:
    return RequestContext(
        principal_id="user-1",
        tenant_id=tenant_id,
        now=NOW,
        grants=(Grant("user-1", tenant_id, capability, resource_prefix=prefix),),
    )


class DeclarativeHandlerTests(unittest.TestCase):
    def setUp(self):
        self.repository = FakeRepository()
        self.jobs = FakeJobs()
        self.events = FakeEvents()
        self.adapters = RuntimeAdapters(self.repository, self.jobs, self.events)
        self.handlers = built_in_handler_registry()

    def runtime(self, service_id):
        service = REGISTRY.load(service_id)
        return build_service_runtime(
            service,
            handlers=self.handlers,
            adapters=self.adapters,
            clock=lambda: NOW,
        )

    def test_catalog_read_and_create_are_service_independent_crud_handlers(self):
        runtime = self.runtime("catalog")
        self.repository.records[("items", "tenant-a", ITEM_ID)] = {"id": ITEM_ID, "name": "Desk lamp"}
        read = runtime.dispatch("GET", f"/items/{ITEM_ID}", {}, identity("tenant-a", "items.read", "/items"))
        self.assertEqual(read.status_code, 200)
        self.assertEqual(read.body["data"]["name"], "Desk lamp")

        created = runtime.dispatch(
            "POST", "/items", {"name": "Floor lamp"},
            identity("tenant-a", "items.create", "/items"),
            headers={"Idempotency-Key": "idem-item-1"},
        )
        self.assertEqual(created.status_code, 201)
        self.assertEqual(created.body["data"]["name"], "Floor lamp")
        self.assertIn(("create", "items", "tenant-a", "idem-item-1"), self.repository.calls)

    def test_tenant_scope_comes_only_from_trusted_request_context(self):
        runtime = self.runtime("catalog")
        self.repository.records[("items", "tenant-a", ITEM_ID)] = {"id": ITEM_ID, "name": "Private item"}
        response = runtime.dispatch(
            "GET", f"/items/{ITEM_ID}", {},
            identity("tenant-b", "items.read", "/items"),
        )
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.body["error"]["code"], "NotFound")
        self.assertIn(("read", "items", "tenant-b"), self.repository.calls)
        injected = runtime.dispatch(
            "GET", f"/items/{ITEM_ID}", {"tenant_id": "tenant-a"},
            identity("tenant-b", "items.read", "/items"),
        )
        self.assertEqual(injected.status_code, 400)
        self.assertEqual(injected.body["error"]["code"], "InvalidInput")

    def test_jobs_submit_get_and_cancel_use_generic_queue_handlers(self):
        runtime = self.runtime("catalog")
        grant = identity("tenant-a", "jobs.submit", "/items")
        submitted = runtime.dispatch(
            "POST", "/items/rebuild", {}, grant, headers={"Idempotency-Key": "idem-job-1"}
        )
        self.assertEqual(submitted.status_code, 202)
        self.assertEqual(submitted.body["data"]["state"], "queued")

        read = runtime.dispatch("GET", f"/jobs/{JOB_ID}", {}, identity("tenant-a", "jobs.read", "/jobs"))
        self.assertEqual(read.status_code, 200)
        cancelled = runtime.dispatch(
            "POST", f"/jobs/{JOB_ID}/cancel", {}, identity("tenant-a", "jobs.cancel", "/jobs")
        )
        self.assertEqual(cancelled.status_code, 200)
        self.assertEqual(cancelled.body["data"]["state"], "cancelled")

    def test_inventory_crud_and_event_handlers_need_no_service_specific_core_code(self):
        runtime = self.runtime("inventory")
        created = runtime.dispatch(
            "POST", "/stock", {"sku": "SKU-1", "quantity": 7},
            identity("tenant-a", "stock.write", "/stock"),
        )
        self.assertEqual(created.status_code, 201)
        updated = runtime.dispatch(
            "PATCH", "/stock/SKU-1", {"quantity": 9},
            identity("tenant-a", "stock.write", "/stock"),
        )
        self.assertEqual(updated.status_code, 200)
        self.assertEqual(updated.body["data"]["quantity"], 9)

        event = runtime.dispatch(
            "POST", "/stock/events", {"sku": "SKU-1", "quantity": 9},
            identity("tenant-a", "stock.events.publish", "/stock"),
        )
        self.assertEqual(event.status_code, 202)
        self.assertEqual(self.events.events[0]["tenant_id"], "tenant-a")

        deleted = runtime.dispatch(
            "DELETE", "/stock/SKU-1", {}, identity("tenant-a", "stock.write", "/stock")
        )
        self.assertEqual(deleted.status_code, 204)

    def test_missing_tenant_identity_is_denied_before_handler_execution(self):
        runtime = self.runtime("catalog")
        anonymous = RequestContext(principal_id="user-1", tenant_id=None, now=NOW, grants=())
        response = runtime.dispatch("GET", f"/items/{ITEM_ID}", {}, anonymous)
        self.assertEqual(response.status_code, 403)
        self.assertEqual(self.repository.calls, [])

    def test_host_handler_effects_must_cover_the_service_ir(self):
        service = REGISTRY.load("inventory")
        from agent_native import TrustedHandlerRegistry
        registry = TrustedHandlerRegistry()
        registry.register(
            "crud.read_by_field", lambda config: (lambda context: {}),
            allowed_effects={"repository.write"},
        )
        with self.assertRaises(ConfigurationError):
            registry.build_handlers(service)

    def test_handler_config_cannot_read_trusted_identity_from_agent_input(self):
        service = REGISTRY.load("inventory")
        configs = dict(service.handler_configs)
        configs["create_stock"] = MappingProxyType({
            "resource": "stock",
            "input_fields": ["tenant_id"],
        })
        unsafe = replace(service, handler_configs=MappingProxyType(configs))
        with self.assertRaises(ConfigurationError):
            self.handlers.build_handlers(unsafe)


if __name__ == "__main__":
    unittest.main()
