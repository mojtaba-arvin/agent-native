from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from catalog import build_catalog_handlers
from kernel import ConfigurationError, HandlerContext, HandlerResult, ServiceRuntime, load_service_ir
from repository import SQLiteCatalogRepository
from security_model import Grant, RequestContext


ROOT = Path(__file__).resolve().parents[2]
SOURCE = (Path(__file__).parent / "catalog.an").read_text(encoding="utf-8")
TRUSTED_EFFECTS = {"repository.read", "repository.write"}


def context(principal="user-a", tenant="tenant-a", capabilities=None):
    capabilities = capabilities or ("items.read", "items.create")
    return RequestContext(
        principal_id=principal,
        tenant_id=tenant,
        now=0,
        grants=tuple(
            Grant(principal, tenant, capability, "/items")
            for capability in capabilities
        ),
    )


class KernelTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.repository = SQLiteCatalogRepository(
            Path(self.temporary.name) / "catalog.sqlite3"
        )
        self.ir = load_service_ir(SOURCE)
        self.audit = []
        self.runtime = ServiceRuntime(
            self.ir,
            handlers=build_catalog_handlers(self.repository),
            repository=self.repository,
            trusted_effects=TRUSTED_EFFECTS,
            clock=lambda: 100,
            audit_sink=self.audit.append,
        )

    def tearDown(self):
        self.repository.close()
        self.temporary.cleanup()

    def dispatch(self, method, target, body=None, identity=None, headers=None):
        return self.runtime.dispatch(
            method,
            target,
            body or {},
            identity or context(),
            headers=headers or {},
        )

    def test_service_contract_drives_generic_handler_runtime(self):
        self.assertEqual(
            {operation["name"] for operation in self.ir["operations"]},
            set(self.runtime.handlers),
        )
        created = self.dispatch(
            "POST",
            "/items",
            {"name": "DeskLamp"},
            headers={"idempotency-key": "create-001"},
        )
        self.assertEqual(created.status_code, 201)
        self.assertEqual(created.body["data"]["name"], "Desk lamp")
        fetched = self.dispatch("GET", f"/items/{created.body['data']['id']}")
        by_name = self.dispatch("GET", "/items/by-name/Desk%20lamp")
        self.assertEqual(fetched.status_code, 200)
        self.assertEqual(by_name.status_code, 200)
        self.assertEqual(fetched.body["data"], by_name.body["data"])

    def test_idempotent_create_replays_exact_result_and_conflicting_payload_fails(self):
        first = self.dispatch(
            "POST", "/items", {"name": "Desk lamp"},
            headers={"idempotency-key": "create-002"},
        )
        replay = self.dispatch(
            "POST", "/items", {"name": "Desk lamp"},
            headers={"idempotency-key": "create-002"},
        )
        conflict = self.dispatch(
            "POST", "/items", {"name": "Floor lamp"},
            headers={"idempotency-key": "create-002"},
        )
        self.assertEqual(first.status_code, 201)
        self.assertEqual(replay.status_code, 200)
        self.assertEqual(first.body["data"], replay.body["data"])
        self.assertEqual(replay.headers["Idempotency-Replayed"], "true")
        self.assertEqual(conflict.status_code, 409)
        self.assertEqual(conflict.body["error"]["code"], "Conflict")

    def test_missing_idempotency_key_and_empty_name_are_rejected(self):
        missing_key = self.dispatch("POST", "/items", {"name": "Desk lamp"})
        empty_name = self.dispatch(
            "POST", "/items", {"name": "  "},
            headers={"idempotency-key": "create-003"},
        )
        self.assertEqual(missing_key.status_code, 400)
        self.assertEqual(empty_name.status_code, 400)
        self.assertEqual(missing_key.body["error"]["code"], "InvalidInput")
        self.assertEqual(empty_name.body["error"]["code"], "InvalidInput")

    def test_tenant_isolation_is_enforced_inside_repository_queries(self):
        created = self.dispatch(
            "POST", "/items", {"name": "Private item"},
            headers={"idempotency-key": "tenant-a-001"},
        )
        item_id = created.body["data"]["id"]
        other = self.dispatch(
            "GET",
            f"/items/{item_id}",
            identity=context("user-b", "tenant-b"),
        )
        same_name_other_tenant = self.dispatch(
            "GET",
            "/items/by-name/Private%20item",
            identity=context("user-b", "tenant-b"),
        )
        self.assertEqual(other.status_code, 404)
        self.assertEqual(same_name_other_tenant.status_code, 404)

    def test_same_item_name_is_unique_per_tenant(self):
        first = self.dispatch(
            "POST", "/items", {"name": "Unique"},
            headers={"idempotency-key": "unique-001"},
        )
        duplicate = self.dispatch(
            "POST", "/items", {"name": "Unique"},
            headers={"idempotency-key": "unique-002"},
        )
        same_name_other_tenant = self.dispatch(
            "POST", "/items", {"name": "Unique"},
            identity=context("user-b", "tenant-b"),
            headers={"idempotency-key": "unique-003"},
        )
        self.assertEqual(first.status_code, 201)
        self.assertEqual(duplicate.status_code, 409)
        self.assertEqual(same_name_other_tenant.status_code, 201)

    def test_default_deny_happens_before_handler_and_is_audited(self):
        denied_identity = context(
            "restricted-user",
            "tenant-a",
            capabilities=("items.read",),
        )
        result = self.dispatch(
            "POST",
            "/items",
            {"name": "Must not persist"},
            identity=denied_identity,
            headers={"idempotency-key": "denied-001"},
        )
        self.assertEqual(result.status_code, 403)
        self.assertEqual(result.body["error"]["code"], "Unauthorized")
        self.assertEqual(self.audit[-1]["reason_code"], "MISSING_CAPABILITY")
        self.assertIsNone(
            self.repository.get_item_by_name(tenant_id="tenant-a", name="Must not persist")
        )

    def test_untrusted_effect_is_rejected_at_service_startup(self):
        invalid_ir = load_service_ir(SOURCE)
        invalid_ir["operations"][0]["effects"].append("network.egress")
        with self.assertRaisesRegex(ConfigurationError, "untrusted_effect"):
            ServiceRuntime(
                invalid_ir,
                handlers=build_catalog_handlers(self.repository),
                repository=self.repository,
                trusted_effects=TRUSTED_EFFECTS,
            )

    def test_audit_failure_is_fail_closed_before_application_handler(self):
        runtime = ServiceRuntime(
            self.ir,
            handlers=build_catalog_handlers(self.repository),
            repository=self.repository,
            trusted_effects=TRUSTED_EFFECTS,
            clock=lambda: 100,
            audit_sink=lambda _event: (_ for _ in ()).throw(OSError("audit offline")),
        )
        result = runtime.dispatch(
            "POST", "/items", {"name": "No write"},
            context(),
            headers={"idempotency-key": "audit-fail-001"},
        )
        self.assertEqual(result.status_code, 503)
        self.assertEqual(result.body["error"]["code"], "AUDIT_UNAVAILABLE")
        self.assertIsNone(
            self.repository.get_item_by_name(tenant_id="tenant-a", name="No write")
        )

    def test_unknown_route_and_method_mismatch_are_distinct(self):
        missing = self.dispatch("GET", "/missing")
        mismatch = self.dispatch("DELETE", "/items")
        self.assertEqual(missing.status_code, 404)
        self.assertEqual(missing.body["error"]["code"], "ROUTE_NOT_FOUND")
        self.assertEqual(mismatch.status_code, 405)
        self.assertEqual(mismatch.body["error"]["code"], "METHOD_NOT_ALLOWED")

    def test_invalid_path_uuid_and_duplicate_query_are_input_errors(self):
        bad_uuid = self.dispatch("GET", "/items/not-a-uuid")
        duplicate_query = self.dispatch("GET", "/items/by-name/Desk?x=1&x=2")
        encoded_path = self.dispatch("GET", "/items/by-name/Desk%2Flamp")
        self.assertEqual(bad_uuid.status_code, 400)
        self.assertEqual(duplicate_query.status_code, 400)
        self.assertEqual(encoded_path.status_code, 400)

    def test_handler_registration_and_output_contract_are_checked(self):
        with self.assertRaisesRegex(ConfigurationError, "handler_names"):
            ServiceRuntime(
                self.ir,
                handlers={},
                repository=self.repository,
                trusted_effects=TRUSTED_EFFECTS,
            )
        broken = dict(build_catalog_handlers(self.repository))
        broken["get_item"] = lambda _context: {"id": "not-a-uuid", "name": "bad", "extra": True}
        runtime = ServiceRuntime(
            self.ir,
            handlers=broken,
            repository=self.repository,
            trusted_effects=TRUSTED_EFFECTS,
        )
        result = runtime.dispatch("GET", "/items/00000000-0000-0000-0000-000000000001", {}, context())
        self.assertEqual(result.status_code, 500)
        self.assertEqual(result.body["error"]["code"], "INVALID_HANDLER_RESULT")


if __name__ == "__main__":
    unittest.main()
