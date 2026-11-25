from __future__ import annotations

import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from agent_native.cli import _safe_server_error
from agent_native.server import _required_environment, _signing_key, run_server


class ServerEnvironmentTests(unittest.TestCase):
    def test_startup_diagnostics_redact_database_and_signing_secrets(self):
        dsn = "postgresql://agent_native:top-secret@postgres:5432/agent_native"
        key = "ab" * 32
        error = RuntimeError(
            f"connection failed for {dsn} password=top-secret "
            f"token_signing_key_hex={key}"
        )
        with patch.dict(
            os.environ,
            {
                "AGENT_NATIVE_POSTGRES_DSN": dsn,
                "AGENT_NATIVE_TOKEN_SIGNING_KEY_HEX": key,
            },
            clear=True,
        ):
            detail = _safe_server_error(error)
        self.assertNotIn("top-secret", detail)
        self.assertNotIn(key, detail)
        self.assertIn("<redacted>", detail)

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

    def test_server_requires_token_key_before_opening_database(self):
        args = SimpleNamespace(
            shutdown_timeout_seconds=10.0,
            services_root="/not-opened",
            host="127.0.0.1",
            port=8080,
            max_concurrency=32,
            max_request_body_bytes=16_384,
            request_timeout_seconds=10.0,
            allow_non_loopback=False,
        )
        with patch.dict(
            os.environ,
            {"AGENT_NATIVE_POSTGRES_DSN": "postgresql://invalid/unused"},
            clear=True,
        ):
            with self.assertRaisesRegex(
                ValueError, "required_environment_missing:AGENT_NATIVE_TOKEN_SIGNING_KEY_HEX"
            ):
                run_server(args)

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
