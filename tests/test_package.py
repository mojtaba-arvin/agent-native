from __future__ import annotations

import unittest

import agent_native


SERVICE = """
service health {
    version: "1.0";
    operation check {
        method: GET;
        path: "/health";
        input {
        }
        output: String;
        errors: [Unauthorized];
        validation: [];
        effects: [];
        capability: "health.read";
    }
}
"""


class PackageSurfaceTests(unittest.TestCase):
    def test_public_imports_are_exposed(self):
        self.assertEqual(agent_native.__version__, "0.1.0.dev0")
        self.assertIs(agent_native.Parser, __import__("agent_native.ir", fromlist=["Parser"]).Parser)
        self.assertTrue(callable(agent_native.validate_ir))
        self.assertTrue(callable(agent_native.lex))

    def test_packaged_parser_builds_canonical_ir(self):
        ir = agent_native.Parser(SERVICE).parse()
        self.assertEqual(ir["service"], {"name": "health", "version": "1.0"})
        self.assertEqual(ir["operations"][0]["name"], "check")

    def test_invalid_source_has_stable_diagnostic(self):
        with self.assertRaises(agent_native.Diagnostic) as raised:
            agent_native.Parser('service broken { version: "1"; }').parse()
        self.assertEqual(raised.exception.code, "AN007")


if __name__ == "__main__":
    unittest.main()
