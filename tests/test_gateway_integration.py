"""Cross-service gateway proof using only declarative service assets."""

from __future__ import annotations

import unittest
from pathlib import Path

from agent_native import AgentGateway, GatewayError, Grant, RequestContext, ServiceRegistry, built_in_handler_registry

ROOT = Path(__file__).resolve().parents[2]
REGISTRY = ServiceRegistry(
    ROOT / "services",
    trusted_handler_ids=built_in_handler_registry().handler_ids,
)
NOW = 1_800_000_000


def context(tenant: str, capability: str | None, scope: str = "/stock") -> RequestContext:
    grants = () if capability is None else (
        Grant("integration-agent", tenant, capability, resource_prefix=scope),
    )
    return RequestContext("integration-agent", tenant, NOW, grants=grants)


class MultiServiceGatewayProof(unittest.TestCase):
    def setUp(self):
        self.gateway = AgentGateway(REGISTRY)

    def test_catalog_and_inventory_use_the_same_gateway_contract(self):
        catalog_identity = context("tenant-a", "items.read", "/items")
        inventory_identity = context("tenant-a", "stock.read")
        catalog = self.gateway.propose(
            "catalog", "get_item",
            {"id": "00000000-0000-0000-0000-000000000001"},
            catalog_identity,
        )
        inventory = self.gateway.propose(
            "inventory", "list_stock", {"warehouse_id": "WH-1"},
            inventory_identity,
        )
        self.assertEqual(catalog.service_id, "catalog")
        self.assertEqual(inventory.service_id, "inventory")
        self.assertEqual(self.gateway.validate(catalog, catalog_identity).service_id, "catalog")
        self.assertEqual(self.gateway.validate(inventory, inventory_identity).service_id, "inventory")

    def test_second_service_supports_write_propose_validate_plan_without_apply(self):
        identity = context("tenant-a", "stock.write")
        proposal = self.gateway.propose(
            "inventory", "create_stock",
            {"sku": "LAMP-001", "quantity": 12, "warehouse_id": "WH-1"},
            identity,
        )
        self.assertEqual(proposal.effect_mode, "write")
        self.assertEqual(proposal.required_capability, "stock.write")
        validation = self.gateway.validate(proposal, identity)
        plan = self.gateway.plan(proposal, validation, identity)
        self.assertTrue(plan.no_apply)
        self.assertFalse(plan.apply_endpoint_exposed)
        self.assertFalse(hasattr(self.gateway, "apply"))

    def test_second_service_denies_write_without_grant(self):
        with self.assertRaises(GatewayError) as caught:
            self.gateway.propose(
                "inventory", "create_stock",
                {"sku": "LAMP-001", "quantity": 12, "warehouse_id": "WH-1"},
                context("tenant-a", None),
            )
        self.assertEqual(caught.exception.code, "MISSING_CAPABILITY")

    def test_second_service_denies_cross_tenant_write_grant(self):
        foreign = RequestContext(
            "integration-agent", "tenant-b", NOW,
            grants=(Grant("integration-agent", "tenant-a", "stock.write", resource_prefix="/stock"),),
        )
        with self.assertRaises(GatewayError) as caught:
            self.gateway.propose(
                "inventory", "create_stock",
                {"sku": "LAMP-001", "quantity": 12, "warehouse_id": "WH-1"},
                foreign,
            )
        self.assertEqual(caught.exception.code, "TENANT_MISMATCH")


if __name__ == "__main__":
    unittest.main()
