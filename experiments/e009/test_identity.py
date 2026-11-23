from __future__ import annotations

import unittest

from experiments.e009.identity import MemoryIdentityProvider
from security_model import Grant, RequestContext


TOKEN = "demo-token-abcdefghijklmnopqrstuvwxyz"


def make_context() -> RequestContext:
    return RequestContext(
        principal_id="operator",
        tenant_id="tenant-a",
        now=123,
        grants=(Grant("operator", "tenant-a", "items.read", "/items"),),
    )


class MemoryIdentityProviderTests(unittest.TestCase):
    def test_context_factory_runs_only_after_matching_bearer_authentication(self):
        calls = []
        provider = MemoryIdentityProvider({
            TOKEN: lambda: calls.append("created") or make_context(),
        })

        self.assertIsNone(provider.authenticate(None))
        self.assertIsNone(provider.authenticate("Basic " + TOKEN))
        self.assertIsNone(provider.authenticate("Bearer wrong-token"))
        self.assertEqual(calls, [])

        context = provider.authenticate("Bearer " + TOKEN)
        self.assertIsInstance(context, RequestContext)
        self.assertEqual(context.principal_id, "operator")
        self.assertEqual(context.tenant_id, "tenant-a")
        self.assertEqual(calls, ["created"])

    def test_context_factory_creates_a_fresh_request_context_per_authentication(self):
        provider = MemoryIdentityProvider({TOKEN: make_context})

        first = provider.authenticate("Bearer " + TOKEN)
        second = provider.authenticate("Bearer " + TOKEN)

        self.assertIsNot(first, second)
        self.assertEqual(first, second)

    def test_prebuilt_context_remains_supported_for_existing_fixtures(self):
        context = make_context()
        provider = MemoryIdentityProvider({TOKEN: context})

        self.assertIs(provider.authenticate("Bearer " + TOKEN), context)

    def test_factory_result_must_be_a_request_context(self):
        provider = MemoryIdentityProvider({TOKEN: lambda: {"principal_id": "forged"}})

        with self.assertRaisesRegex(TypeError, "must_return_request_context"):
            provider.authenticate("Bearer " + TOKEN)

    def test_invalid_identity_mapping_value_is_rejected_at_construction(self):
        with self.assertRaisesRegex(ValueError, "context_or_factory"):
            MemoryIdentityProvider({TOKEN: {"principal_id": "not trusted"}})


if __name__ == "__main__":
    unittest.main()
