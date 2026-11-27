from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from agent_native.security import (  # noqa: E402
    AuthenticationError,
    CapabilityTokenAuthority,
    Grant,
)


class CapabilityTokenAuthorityTests(unittest.TestCase):
    def setUp(self):
        self.now = 1_000
        self.authority = CapabilityTokenAuthority(
            b"k" * 32,
            issuer="issuer-a",
            audience="service-a",
            clock=lambda: self.now,
            max_ttl_seconds=600,
        )
        self.grant = Grant(
            principal_id="principal-a",
            tenant_id="tenant-a",
            capability="items.read",
            resource_prefix="/items",
            expires_at=1_400,
            delegation_depth=1,
        )

    def issue(self):
        return self.authority.issue_token(
            "principal-a", "tenant-a", [self.grant], ttl_seconds=300
        )

    def test_signed_grant_round_trip_binds_principal_tenant_and_scope(self):
        context = self.authority.authenticate("Bearer " + self.issue())
        self.assertEqual(context.principal_id, "principal-a")
        self.assertEqual(context.tenant_id, "tenant-a")
        self.assertEqual(len(context.grants), 1)
        self.assertEqual(context.grants[0].capability, "items.read")
        self.assertEqual(context.grants[0].resource_prefix, "/items")

    def test_tampered_signature_is_rejected(self):
        token = self.issue()
        header, claims, signature = token.split(".")
        replacement = ("A" if signature[0] != "A" else "B") + signature[1:]
        with self.assertRaisesRegex(AuthenticationError, "invalid_token_signature"):
            self.authority.authenticate("Bearer " + ".".join((header, claims, replacement)))

    def test_wrong_issuer_and_audience_are_rejected(self):
        token = self.issue()
        wrong_issuer = CapabilityTokenAuthority(
            b"k" * 32, issuer="issuer-b", audience="service-a",
            clock=lambda: self.now, max_ttl_seconds=600,
        )
        wrong_audience = CapabilityTokenAuthority(
            b"k" * 32, issuer="issuer-a", audience="service-b",
            clock=lambda: self.now, max_ttl_seconds=600,
        )
        for authority in (wrong_issuer, wrong_audience):
            with self.subTest(authority=authority):
                with self.assertRaisesRegex(AuthenticationError, "invalid_token_claims"):
                    authority.authenticate("Bearer " + token)

    def test_expired_bearer_token_is_rejected(self):
        token = self.issue()
        self.now = 1_300
        with self.assertRaisesRegex(AuthenticationError, "token_expired_or_outside_validity_window"):
            self.authority.authenticate("Bearer " + token)

    def test_expired_individual_grant_is_not_returned(self):
        token = self.issue()
        self.now = 1_401
        # The enclosing bearer token is also expired at this time; a token
        # with a longer envelope isolates the per-grant expiry behavior.
        authority = CapabilityTokenAuthority(
            b"k" * 32, issuer="issuer-a", audience="service-a",
            clock=lambda: self.now, max_ttl_seconds=600,
        )
        live_envelope = authority.issue_token(
            "principal-a", "tenant-a", [self.grant], ttl_seconds=300
        )
        context = authority.authenticate("Bearer " + live_envelope)
        self.assertEqual(context.grants, ())

    def test_issue_rejects_grant_for_another_principal_or_tenant(self):
        mismatched = Grant("principal-b", "tenant-a", "items.read")
        with self.assertRaisesRegex(ValueError, "token_grant_identity_mismatch"):
            self.authority.issue_token("principal-a", "tenant-a", [mismatched])

    def test_issue_rejects_unbounded_or_invalid_ttl(self):
        for ttl in (0, 601, True):
            with self.subTest(ttl=ttl):
                with self.assertRaisesRegex(ValueError, "invalid_token_ttl"):
                    self.authority.issue_token(
                        "principal-a", "tenant-a", [self.grant], ttl_seconds=ttl
                    )

    def test_missing_and_malformed_bearer_credentials_are_rejected(self):
        for credential in (None, "", "Basic abc", "Bearer a.b"):
            with self.subTest(credential=credential):
                with self.assertRaises(AuthenticationError):
                    self.authority.authenticate(credential)


if __name__ == "__main__":
    unittest.main()
