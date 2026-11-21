from __future__ import annotations

import unittest
from dataclasses import replace
from pathlib import Path

from agent_native.gateway.core import GatewayError as CoreGatewayError, _canonical_hash, _freeze_json, _thaw_json

from agent_native import (
    AgentGateway,
    GatewayError,
    Grant,
    RequestContext,
    ServiceRegistry,
    built_in_handler_registry,
    classify_effects,
)

ROOT = Path(__file__).resolve().parents[1]
REGISTRY = ServiceRegistry(
    ROOT / "services",
    trusted_handler_ids=built_in_handler_registry().handler_ids,
)
NOW = 1_800_000_000
ITEM_ID = "00000000-0000-0000-0000-000000000001"


def identity(tenant_id: str, capability: str, resource_prefix: str) -> RequestContext:
    return RequestContext(
        principal_id="agent-1",
        tenant_id=tenant_id,
        now=NOW,
        grants=(Grant("agent-1", tenant_id, capability, resource_prefix=resource_prefix),),
    )


class AgentGatewayTests(unittest.TestCase):
    def setUp(self):
        self.gateway = AgentGateway(REGISTRY)

    def test_read_proposal_can_be_validated_and_planned_without_execution(self):
        context = identity("tenant-a", "items.read", "/items")
        proposal = self.gateway.propose("catalog", "get_item", {"id": ITEM_ID}, context)
        self.assertEqual(proposal.effect_mode, "read")
        self.assertEqual(proposal.resource, f"/items/{ITEM_ID}")

        validation = self.gateway.validate(proposal, context)
        self.assertTrue(validation.allowed)
        plan = self.gateway.plan(proposal, validation, context)
        self.assertTrue(plan.no_apply)
        self.assertFalse(plan.apply_endpoint_exposed)
        self.assertFalse(hasattr(self.gateway, "apply"))

    def test_write_proposal_uses_explicit_capability_and_stays_non_executable(self):
        context = identity("tenant-a", "items.create", "/items")
        proposal = self.gateway.propose(
            "catalog", "create_item",
            {"name": "Desk lamp", "idempotency_key": "idem-1"},
            context,
        )
        self.assertEqual(proposal.effect_mode, "write")
        self.assertEqual(proposal.required_capability, "items.create")
        validation = self.gateway.validate(proposal, context)
        plan = self.gateway.plan(proposal, validation, context)
        self.assertTrue(plan.no_apply)
        self.assertFalse(plan.apply_endpoint_exposed)

    def test_gateway_resolves_a_second_service_without_service_specific_code(self):
        context = identity("tenant-a", "stock.read", "/stock")
        proposal = self.gateway.propose(
            "inventory", "list_stock", {"warehouse_id": "WH-1"}, context
        )
        self.assertEqual(proposal.effect_mode, "read")
        self.assertEqual(proposal.resource, "/stock")
        self.assertEqual(self.gateway.validate(proposal, context).service_id, "inventory")

    def test_proposal_rejects_non_host_request_context(self):
        with self.assertRaises(GatewayError) as caught:
            self.gateway.propose("catalog", "get_item", {"id": ITEM_ID}, None)
        self.assertEqual(caught.exception.code, "INVALID_REQUEST_CONTEXT")

    def test_missing_capability_is_denied(self):
        context = RequestContext("agent-1", "tenant-a", NOW, grants=())
        with self.assertRaises(GatewayError) as caught:
            self.gateway.propose("catalog", "get_item", {"id": ITEM_ID}, context)
        self.assertEqual(caught.exception.code, "MISSING_CAPABILITY")

    def test_cross_tenant_grant_is_denied(self):
        context = identity("tenant-b", "items.read", "/items")
        foreign_grant = Grant("agent-1", "tenant-a", "items.read", resource_prefix="/items")
        context = RequestContext("agent-1", "tenant-b", NOW, grants=(foreign_grant,))
        with self.assertRaises(GatewayError) as caught:
            self.gateway.propose("catalog", "get_item", {"id": ITEM_ID}, context)
        self.assertEqual(caught.exception.code, "TENANT_MISMATCH")

    def test_unsupported_effect_is_rejected_during_validation(self):
        context = identity("tenant-a", "items.read", "/items")
        proposal = self.gateway.propose("catalog", "get_item", {"id": ITEM_ID}, context)
        forged = replace(proposal, effects=("filesystem.delete",))
        with self.assertRaises(GatewayError) as caught:
            self.gateway.validate(forged, context)
        self.assertEqual(caught.exception.code, "UNSUPPORTED_EFFECT")

    def test_service_identity_mismatch_is_rejected(self):
        context = identity("tenant-a", "items.read", "/items")
        proposal = self.gateway.propose("catalog", "get_item", {"id": ITEM_ID}, context)
        forged = replace(proposal, service_name="Inventory")
        with self.assertRaises(GatewayError) as caught:
            self.gateway.validate(forged, context)
        self.assertEqual(caught.exception.code, "SERVICE_IDENTITY_MISMATCH")

    def test_tampered_candidate_hash_is_rejected(self):
        context = identity("tenant-a", "items.read", "/items")
        proposal = self.gateway.propose("catalog", "get_item", {"id": ITEM_ID}, context)
        forged = replace(proposal, candidate_sha256="0" * 64)
        with self.assertRaises(GatewayError) as caught:
            self.gateway.validate(forged, context)
        self.assertEqual(caught.exception.code, "PROPOSAL_HASH_MISMATCH")

    def test_input_schema_is_checked_before_authorization(self):
        context = identity("tenant-a", "items.read", "/items")
        with self.assertRaises(GatewayError) as caught:
            self.gateway.propose("catalog", "get_item", {"id": "not-a-uuid"}, context)
        self.assertEqual(caught.exception.code, "INVALID_INPUT")

    def test_ir_non_empty_validation_rules_are_enforced_for_proposals(self):
        context = identity("tenant-a", "items.create", "/items")
        with self.assertRaises(GatewayError) as caught:
            self.gateway.propose(
                "catalog", "create_item",
                {"name": "   ", "idempotency_key": "idem-1"},
                context,
            )
        self.assertEqual(caught.exception.code, "INVALID_INPUT")

    def test_stale_validation_cannot_be_used_to_plan_another_proposal(self):
        context = identity("tenant-a", "items.read", "/items")
        first = self.gateway.propose("catalog", "get_item", {"id": ITEM_ID}, context)
        validation = self.gateway.validate(first, context)
        second = self.gateway.propose(
            "inventory", "list_stock", {"warehouse_id": "WH-1"},
            identity("tenant-a", "stock.read", "/stock"),
        )
        with self.assertRaises(GatewayError) as caught:
            self.gateway.plan(second, validation, identity("tenant-a", "stock.read", "/stock"))
        self.assertEqual(caught.exception.code, "VALIDATION_STALE")

    def test_plan_rejects_forged_validation_metadata(self):
        context = identity("tenant-a", "items.read", "/items")
        proposal = self.gateway.propose("catalog", "get_item", {"id": ITEM_ID}, context)
        validation = self.gateway.validate(proposal, context)
        forged = replace(validation, required_capability="admin.root")

        with self.assertRaises(GatewayError) as caught:
            self.gateway.plan(proposal, forged, context)
        self.assertEqual(caught.exception.code, "VALIDATION_STALE")

    def test_plan_does_not_retain_mutable_effect_lists(self):
        context = identity("tenant-a", "items.read", "/items")
        proposal = self.gateway.propose("catalog", "get_item", {"id": ITEM_ID}, context)
        mutable_effects = list(proposal.effects)
        forged = replace(proposal, effects=mutable_effects)
        validation = self.gateway.validate(forged, context)
        plan = self.gateway.plan(forged, validation, context)

        mutable_effects.append("repository.write")
        self.assertEqual(plan.effects, ("repository.read",))
        self.assertIsInstance(plan.effects, tuple)

    def test_proposal_payload_freezing_is_recursive(self):
        source = {"nested": {"items": [{"name": "original"}]}}
        frozen = _freeze_json(source)

        with self.assertRaises(TypeError):
            frozen["nested"]["new"] = "value"
        with self.assertRaises(TypeError):
            frozen["nested"]["items"][0]["name"] = "tampered"
        with self.assertRaises(AttributeError):
            frozen["nested"]["items"].append({"name": "extra"})

        self.assertEqual(_thaw_json(frozen), source)

    def test_canonical_hash_rejects_non_finite_json_numbers(self):
        with self.assertRaises(CoreGatewayError) as caught:
            _canonical_hash({"nested": {"value": float("nan")}})
        self.assertEqual(caught.exception.code, "NON_CANONICAL_INPUT")

    def test_unknown_effects_fail_closed(self):
        with self.assertRaises(ValueError):
            classify_effects(["filesystem.delete"])


if __name__ == "__main__":
    unittest.main()
