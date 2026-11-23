from __future__ import annotations

import unittest
from pathlib import Path

from agent_native import (
    AuthenticationError,
    CapabilityTokenAuthority,
    Grant,
    OperationContract,
    PolicyEngine,
    RequestContext,
    RuntimeAdapters,
    ServiceHost,
    built_in_handler_registry,
)

ROOT = Path(__file__).resolve().parents[1]
ITEM_ID = "00000000-0000-4000-8000-000000000001"


class RecordingRepository:
    def __init__(self):
        self.calls = []

    def read(self, resource, key, *, tenant_id):
        self.calls.append((resource, key, tenant_id))
        if resource != "items":
            return None
        return {"id": str(key), "name": "Desk lamp"}


class AuthenticationBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.now = 100
        self.key = b"t12-test-signing-key-must-be-at-least-32-bytes"
        self.authority = CapabilityTokenAuthority(
            self.key, clock=lambda: self.now, max_ttl_seconds=900
        )
        self.repository = RecordingRepository()
        self.host = ServiceHost(
            ROOT / "services",
            handlers=built_in_handler_registry(),
            adapters=RuntimeAdapters(
                repository=self.repository,
                jobs=object(),
                events=object(),
            ),
            clock=lambda: self.now,
            authenticator=self.authority,
        )

    def token(self, grants=(), *, ttl=300, authority=None, principal="user-1", tenant="tenant-a"):
        issuer = authority or self.authority
        return issuer.issue_token(principal, tenant, tuple(grants), ttl_seconds=ttl)

    def grant(self, capability="items.read", prefix="/items", *, tenant="tenant-a", expiry=None):
        return Grant(
            principal_id="user-1",
            tenant_id=tenant,
            capability=capability,
            resource_prefix=prefix,
            expires_at=expiry,
        )

    def dispatch(self, authorization, *, host=None, target="/items/" + ITEM_ID, body=None):
        return (host or self.host).dispatch_authenticated(
            "catalog",
            "GET",
            target,
            body or {},
            authorization=authorization,
        )

    def test_missing_authorization_is_unauthenticated(self):
        response = self.dispatch(None)
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.body["error"]["code"], "UNAUTHENTICATED")
        self.assertEqual(self.repository.calls, [])

    def test_tampered_token_is_unauthenticated(self):
        token = self.token((self.grant(),))
        parts = token.split(".")
        parts[1] = parts[1][:-1] + ("A" if parts[1][-1] != "A" else "B")
        response = self.dispatch("Bearer " + ".".join(parts))
        self.assertEqual(response.status_code, 401)
        self.assertEqual(self.repository.calls, [])

    def test_expired_token_is_unauthenticated(self):
        token = self.token((self.grant(),), ttl=5)
        self.now = 105
        response = self.dispatch("Bearer " + token)
        self.assertEqual(response.status_code, 401)
        self.assertEqual(self.repository.calls, [])

    def test_future_token_is_unauthenticated(self):
        future_issuer = CapabilityTokenAuthority(
            self.key, clock=lambda: 200, max_ttl_seconds=900
        )
        token = self.token((self.grant(),), authority=future_issuer)
        response = self.dispatch("Bearer " + token)
        self.assertEqual(response.status_code, 401)
        self.assertEqual(self.repository.calls, [])

    def test_valid_token_dispatches(self):
        token = self.token((self.grant(),))
        response = self.dispatch("Bearer " + token)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.body["data"], {"id": ITEM_ID, "name": "Desk lamp"})
        self.assertEqual(self.repository.calls, [("items", ITEM_ID, "tenant-a")])

    def test_missing_capability_is_forbidden(self):
        token = self.token(())
        response = self.dispatch("Bearer " + token)
        self.assertEqual(response.status_code, 403)
        self.assertEqual(self.repository.calls, [])

    def test_wrong_tenant_is_forbidden(self):
        operation = OperationContract("get_item", "items.read", frozenset({"repository.read"}))
        context = RequestContext(
            principal_id="user-1",
            tenant_id="tenant-a",
            now=self.now,
            grants=(self.grant(tenant="tenant-b"),),
        )
        decision = PolicyEngine().authorize(
            operation,
            resource="/items/" + ITEM_ID,
            requested_effects={"repository.read"},
            context=context,
        )
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.reason_code, "TENANT_MISMATCH")

    def test_resource_scope_is_enforced(self):
        token = self.token((self.grant(prefix="/items/another"),))
        response = self.dispatch("Bearer " + token)
        self.assertEqual(response.status_code, 403)
        self.assertEqual(self.repository.calls, [])

    def test_expired_grant_is_forbidden(self):
        token = self.token((self.grant(expiry=100),))
        response = self.dispatch("Bearer " + token)
        self.assertEqual(response.status_code, 403)
        self.assertEqual(self.repository.calls, [])

    def test_host_without_authenticator_fails_closed(self):
        unconfigured = ServiceHost(
            ROOT / "services",
            handlers=built_in_handler_registry(),
            adapters=RuntimeAdapters(self.repository, object(), object()),
            clock=lambda: self.now,
        )
        response = self.dispatch("Bearer ignored", host=unconfigured)
        self.assertEqual(response.status_code, 401)
        self.assertEqual(self.repository.calls, [])

    def test_non_bearer_authorization_is_rejected(self):
        with self.assertRaises(AuthenticationError):
            self.authority.authenticate("Basic dXNlcjpwYXNz")

    def test_short_signing_key_is_rejected(self):
        with self.assertRaises(ValueError):
            CapabilityTokenAuthority(b"too-short")

    def test_token_cannot_carry_another_principals_grant(self):
        grant = Grant("another-user", "tenant-a", "items.read", "/items")
        with self.assertRaises(ValueError):
            self.authority.issue_token("user-1", "tenant-a", (grant,))


    def test_expired_grant_is_denied_by_policy_engine_directly(self):
        operation = OperationContract("get_item", "items.read", frozenset({"repository.read"}))
        context = RequestContext(
            principal_id="user-1",
            tenant_id="tenant-a",
            now=self.now,
            grants=(self.grant(expiry=self.now),),
        )
        decision = PolicyEngine().authorize(
            operation,
            resource="/items/" + ITEM_ID,
            requested_effects={"repository.read"},
            context=context,
        )
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.reason_code, "EXPIRED_GRANT")

    def test_canonical_signature_mismatch_is_unauthenticated(self):
        import base64

        token = self.token((self.grant(),))
        header, claims, signature = token.split(".")
        decoded = base64.urlsafe_b64decode(signature + "=" * (-len(signature) % 4))
        tampered = bytes([decoded[0] ^ 1]) + decoded[1:]
        changed_signature = base64.urlsafe_b64encode(tampered).rstrip(b"=").decode("ascii")
        response = self.dispatch("Bearer " + ".".join((header, claims, changed_signature)))
        self.assertEqual(response.status_code, 401)
        self.assertEqual(self.repository.calls, [])

    def test_resource_prefix_requires_segment_boundary(self):
        operation = OperationContract("get_item", "items.read", frozenset({"repository.read"}))
        context = RequestContext(
            principal_id="user-1",
            tenant_id="tenant-a",
            now=self.now,
            grants=(self.grant(prefix="/items"),),
        )
        decision = PolicyEngine().authorize(
            operation,
            resource="/items-admin/" + ITEM_ID,
            requested_effects={"repository.read"},
            context=context,
        )
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.reason_code, "RESOURCE_SCOPE")


if __name__ == "__main__":
    unittest.main()
