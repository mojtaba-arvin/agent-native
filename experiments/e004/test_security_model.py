import unittest

from security_model import (
    Grant,
    OperationContract,
    PolicyEngine,
    RequestContext,
    attenuate,
)


class PolicyEngineTests(unittest.TestCase):
    def setUp(self):
        self.engine = PolicyEngine()
        self.operation = OperationContract(
            name="get_item",
            required_capability="items.read",
            allowed_effects=frozenset({"repository.read"}),
        )
        self.grant = Grant(
            principal_id="user-1",
            tenant_id="tenant-a",
            capability="items.read",
            resource_prefix="/items",
            expires_at=500,
            delegation_depth=2,
        )

    def context(self, *, principal="user-1", tenant="tenant-a", now=100, grants=None):
        return RequestContext(
            principal_id=principal,
            tenant_id=tenant,
            now=now,
            grants=tuple([self.grant] if grants is None else grants),
        )

    def test_matching_grant_allows_declared_effect(self):
        decision = self.engine.authorize(
            self.operation,
            resource="/items/42",
            requested_effects={"repository.read"},
            context=self.context(),
        )
        self.assertTrue(decision.allowed)
        self.assertEqual(decision.reason_code, "ALLOW")
        self.assertEqual(decision.audit_event["decision"], "allow")

    def test_missing_capability_is_denied_by_default(self):
        decision = self.engine.authorize(
            self.operation,
            resource="/items/42",
            requested_effects={"repository.read"},
            context=self.context(grants=()),
        )
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.reason_code, "MISSING_CAPABILITY")

    def test_cross_tenant_grant_is_denied(self):
        decision = self.engine.authorize(
            self.operation,
            resource="/items/42",
            requested_effects={"repository.read"},
            context=self.context(tenant="tenant-b"),
        )
        self.assertEqual(decision.reason_code, "TENANT_MISMATCH")

    def test_expired_grant_is_denied(self):
        decision = self.engine.authorize(
            self.operation,
            resource="/items/42",
            requested_effects={"repository.read"},
            context=self.context(now=500),
        )
        self.assertEqual(decision.reason_code, "EXPIRED_GRANT")

    def test_resource_scope_uses_path_boundaries(self):
        decision = self.engine.authorize(
            self.operation,
            resource="/items-archive/42",
            requested_effects={"repository.read"},
            context=self.context(),
        )
        self.assertEqual(decision.reason_code, "RESOURCE_SCOPE")

    def test_undeclared_effect_is_denied_even_with_grant(self):
        decision = self.engine.authorize(
            self.operation,
            resource="/items/42",
            requested_effects={"repository.read", "network.egress"},
            context=self.context(),
        )
        self.assertEqual(decision.reason_code, "UNDECLARED_EFFECT")

    def test_missing_identity_is_denied(self):
        decision = self.engine.authorize(
            self.operation,
            resource="/items/42",
            requested_effects={"repository.read"},
            context=self.context(principal=None),
        )
        self.assertEqual(decision.reason_code, "MISSING_IDENTITY")

    def test_unsafe_resource_path_is_denied(self):
        decision = self.engine.authorize(
            self.operation,
            resource="/items/../secrets",
            requested_effects={"repository.read"},
            context=self.context(),
        )
        self.assertEqual(decision.reason_code, "INVALID_RESOURCE")

    def test_delegation_can_only_narrow_scope_and_expiry(self):
        delegated = attenuate(
            self.grant,
            delegate_principal_id="worker-1",
            resource_prefix="/items/42",
            expires_at=300,
        )
        self.assertEqual(delegated.tenant_id, "tenant-a")
        self.assertEqual(delegated.capability, "items.read")
        self.assertEqual(delegated.delegation_depth, 1)
        self.assertEqual(delegated.resource_prefix, "/items/42")
        self.assertEqual(delegated.expires_at, 300)

    def test_delegation_rejects_scope_widening_and_expiry_extension(self):
        with self.assertRaisesRegex(ValueError, "resource_scope_widening"):
            attenuate(
                self.grant,
                delegate_principal_id="worker-1",
                resource_prefix="/",
                expires_at=300,
            )
        with self.assertRaisesRegex(ValueError, "expiry_extension"):
            attenuate(
                self.grant,
                delegate_principal_id="worker-1",
                resource_prefix="/items/42",
                expires_at=600,
            )

    def test_delegation_must_reduce_at_least_one_authority_dimension(self):
        with self.assertRaisesRegex(ValueError, "no_authority_attenuation"):
            attenuate(
                self.grant,
                delegate_principal_id="worker-1",
                resource_prefix="/items",
                expires_at=500,
            )

    def test_invalid_grant_scope_is_rejected_at_construction(self):
        with self.assertRaisesRegex(ValueError, "invalid_grant_resource_prefix"):
            Grant(
                principal_id="user-1",
                tenant_id="tenant-a",
                capability="items.read",
                resource_prefix="/items/../secrets",
            )

    def test_delegation_depth_is_enforced(self):
        exhausted = Grant(
            principal_id="user-1",
            tenant_id="tenant-a",
            capability="items.read",
            delegation_depth=0,
        )
        with self.assertRaisesRegex(ValueError, "delegation_depth_exhausted"):
            attenuate(
                exhausted,
                delegate_principal_id="worker-1",
                resource_prefix="/items/42",
                expires_at=300,
            )



    def test_encoded_and_ambiguous_resource_paths_are_rejected(self):
        resources = (
            "/items/%2e%2e/secrets",
            "/items/%2Fsecrets",
            "/items/" + chr(92) + "secrets",
            "/items//secrets",
            "/items/./secrets",
            "/items/../secrets",
            "/items/" + chr(0) + "secrets",
        )
        for resource in resources:
            with self.subTest(resource=repr(resource)):
                decision = self.engine.authorize(
                    self.operation,
                    resource=resource,
                    requested_effects={"repository.read"},
                    context=self.context(),
                )
                self.assertEqual(decision.reason_code, "INVALID_RESOURCE")

    def test_noncanonical_unicode_resource_is_rejected(self):
        resource = "/items/cafe" + chr(0x301)
        decision = self.engine.authorize(
            self.operation,
            resource=resource,
            requested_effects={"repository.read"},
            context=self.context(),
        )
        self.assertEqual(decision.reason_code, "INVALID_RESOURCE")

    def test_boolean_expiry_and_delegation_depth_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "invalid_grant_expiry"):
            Grant("user-1", "tenant-a", "items.read", expires_at=True)
        with self.assertRaisesRegex(ValueError, "invalid_delegation_depth"):
            Grant("user-1", "tenant-a", "items.read", delegation_depth=True)

    def test_boolean_trusted_time_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "invalid_trusted_time"):
            RequestContext("user-1", "tenant-a", True, (self.grant,))


    def test_trailing_slash_normalization_cannot_fake_attenuation(self):
        grant = Grant(
            principal_id="user-1",
            tenant_id="tenant-a",
            capability="items.read",
            resource_prefix="/items",
            expires_at=500,
            delegation_depth=1,
        )
        with self.assertRaisesRegex(ValueError, "no_authority_attenuation"):
            attenuate(
                grant,
                delegate_principal_id="worker-1",
                resource_prefix="/items/",
                expires_at=500,
            )

    def test_invalid_delegated_resource_scope_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "invalid_delegated_resource_prefix"):
            attenuate(
                self.grant,
                delegate_principal_id="worker-1",
                resource_prefix="/items/%2e%2e/secrets",
                expires_at=300,
            )

    def test_mutable_effect_allowlists_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "invalid_operation_effects"):
            OperationContract("read", "items.read", {"repository.read"})

if __name__ == "__main__":
    unittest.main()
