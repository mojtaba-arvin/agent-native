from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from agent_native.server import _required_environment, _signing_key


class ServerEnvironmentTests(unittest.TestCase):
    def test_required_environment_rejects_missing_and_blank_values(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(ValueError, "required_environment_missing"):
                _required_environment("AGENT_NATIVE_POSTGRES_DSN")
        with patch.dict(os.environ, {"AGENT_NATIVE_POSTGRES_DSN": "  "}, clear=True):
            with self.assertRaisesRegex(ValueError, "required_environment_missing"):
                _required_environment("AGENT_NATIVE_POSTGRES_DSN")

    def test_signing_key_requires_at_least_32_bytes_of_hex(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(ValueError, "required_environment_missing"):
                _signing_key()
        with patch.dict(os.environ, {"AGENT_NATIVE_TOKEN_SIGNING_KEY_HEX": "zz" * 32}, clear=True):
            with self.assertRaisesRegex(ValueError, "invalid_token_signing_key_hex"):
                _signing_key()
        with patch.dict(os.environ, {"AGENT_NATIVE_TOKEN_SIGNING_KEY_HEX": "ab" * 31}, clear=True):
            with self.assertRaisesRegex(ValueError, "invalid_token_signing_key_hex"):
                _signing_key()

    def test_signing_key_accepts_32_byte_hex(self):
        expected = bytes(range(32))
        with patch.dict(
            os.environ,
            {"AGENT_NATIVE_TOKEN_SIGNING_KEY_HEX": expected.hex()},
            clear=True,
        ):
            self.assertEqual(_signing_key(), expected)


if __name__ == "__main__":
    unittest.main()
