import copy
import json
import tempfile
import unittest
from pathlib import Path

from surface import (
    SurfaceError,
    assert_fair_pair,
    build_surface,
    load_catalog,
    surface_size_bytes,
)


class SurfaceTests(unittest.TestCase):
    def setUp(self):
        self.catalog = load_catalog()
        self.progressive = build_surface("progressive")
        self.upfront = build_surface("upfront")

    def test_both_arms_have_identical_dispatch_contract_and_tool_identity(self):
        assert_fair_pair(self.progressive, self.upfront)
        self.assertEqual(
            self.progressive["dispatch"],
            self.upfront["dispatch"],
        )
        self.assertEqual(
            [item["name"] for item in self.progressive["tools"]],
            [item["name"] for item in self.upfront["tools"]],
        )

    def test_progressive_arm_exposes_only_discovery_schema(self):
        visible = {
            item["name"]
            for item in self.progressive["tools"]
            if "input_schema" in item
        }
        self.assertEqual(visible, {"interface.describe"})

    def test_schema_discovery_names_gateway_tools_not_target_operations(self):
        instruction = self.progressive["schema_discovery"]["instruction"]
        self.assertIn("exact exposed Gateway tool name", instruction)
        self.assertIn("service.inspect", instruction)
        self.assertIn("service.propose_delta", instruction)
        self.assertIn("never pass the operation being added", instruction)

    def test_upfront_arm_exposes_every_schema(self):
        self.assertTrue(all("input_schema" in item for item in self.upfront["tools"]))

    def test_discovery_schema_is_identical_in_both_arms(self):
        progressive = next(
            item for item in self.progressive["tools"]
            if item["name"] == "interface.describe"
        )
        upfront = next(
            item for item in self.upfront["tools"]
            if item["name"] == "interface.describe"
        )
        self.assertEqual(progressive["input_schema"], upfront["input_schema"])

    def test_progressive_surface_is_smaller_than_upfront_surface(self):
        self.assertLess(
            surface_size_bytes(self.progressive),
            surface_size_bytes(self.upfront),
        )

    def test_fair_pair_rejects_schema_leakage(self):
        tampered = copy.deepcopy(self.progressive)
        tampered["tools"][1]["input_schema"] = self.upfront["tools"][1]["input_schema"]
        with self.assertRaisesRegex(SurfaceError, "progressive_arm_leaks_detailed_schema"):
            assert_fair_pair(tampered, self.upfront)

    def test_fair_pair_rejects_dispatch_drift(self):
        tampered = copy.deepcopy(self.upfront)
        tampered["dispatch"]["input_schema"]["properties"]["tool"]["enum"].reverse()
        with self.assertRaisesRegex(SurfaceError, "dispatch_contract_mismatch"):
            assert_fair_pair(self.progressive, tampered)

    def test_unknown_arm_is_rejected(self):
        with self.assertRaisesRegex(SurfaceError, "unknown_disclosure_arm"):
            build_surface("hybrid")

    def test_duplicate_tool_names_are_rejected(self):
        catalog = copy.deepcopy(self.catalog)
        catalog["tools"].append(copy.deepcopy(catalog["tools"][0]))
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "tools.json"
            path.write_text(json.dumps(catalog), encoding="utf-8")
            with self.assertRaisesRegex(SurfaceError, "duplicate_tool_name"):
                load_catalog(path)

    def test_missing_discovery_tool_is_rejected(self):
        catalog = copy.deepcopy(self.catalog)
        catalog["tools"] = [
            item for item in catalog["tools"]
            if item["name"] != "interface.describe"
        ]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "tools.json"
            path.write_text(json.dumps(catalog), encoding="utf-8")
            with self.assertRaisesRegex(SurfaceError, "discovery_tool_missing"):
                load_catalog(path)


if __name__ == "__main__":
    unittest.main()
