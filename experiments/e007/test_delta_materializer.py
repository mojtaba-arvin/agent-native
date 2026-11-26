from __future__ import annotations

import json
import random
import sys
import unittest
from copy import deepcopy
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "experiments" / "e007"))
sys.path.insert(0, str(ROOT / "experiments" / "e009"))
from delta_materializer import (  # noqa: E402
    DeltaMaterializationError,
    digest,
    materialize_add_operation,
    parse_delta_request,
)
from kernel import load_service_ir  # noqa: E402


class DeltaMaterializerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.base = load_service_ir((ROOT / "experiments/e009/catalog.an").read_text(encoding="utf-8"))
        cls.operation = {
            "name": "get_item_by_normalized_name",
            "method": "GET",
            "path": "/items/by-normalized-name/{name}",
            "input": [{"name": "name", "source": "path", "type": "String"}],
            "output": "Item",
            "errors": ["InvalidInput", "NotFound", "Unauthorized"],
            "validation": ["name.non_empty"],
            "effects": ["repository.read"],
            "capability": "items.read",
        }
        cls.trusted_effects = {
            "repository.read", "repository.write", "queue.submit", "queue.read", "queue.cancel"
        }
        cls.trusted_capabilities = {
            "items.read", "items.create", "items.rebuild", "jobs.read", "jobs.cancel"
        }

    def request(self, **overrides):
        value = {
            "service_id": "catalog",
            "base_revision": digest(self.base),
            "changes": [{"kind": "add_operation", "operation": deepcopy(self.operation)}],
        }
        value.update(overrides)
        return value

    def materialize(self, request=None, **kwargs):
        return materialize_add_operation(
            json.dumps(self.request() if request is None else request, separators=(",", ":")),
            service_id="catalog",
            current_service=self.base,
            trusted_effects=self.trusted_effects,
            trusted_capabilities=self.trusted_capabilities,
            **kwargs,
        )

    def assert_code(self, code, request):
        with self.assertRaises(DeltaMaterializationError) as caught:
            self.materialize(request)
        self.assertEqual(caught.exception.code, code)

    def test_valid_delta_materializes_complete_snapshot_and_preserves_base(self):
        result = self.materialize()
        self.assertEqual(result["ir"]["service"], self.base["service"])
        self.assertEqual(result["ir"]["types"], self.base["types"])
        self.assertEqual(result["ir"]["operations"][:-1], self.base["operations"])
        self.assertEqual(result["ir"]["operations"][-1], self.operation)
        self.assertEqual(result["base_revision"], digest(self.base))
        self.assertEqual(result["change_set_id"], digest({
            "service_id": "catalog",
            "base_revision": digest(self.base),
            "ir": result["ir"],
        }))
        self.assertEqual(len(result["intent_digest"]), 64)
        self.assertEqual(result["materialized_ir_digest"], digest(result["ir"]))

    def test_materialization_is_deterministic(self):
        self.assertEqual(self.materialize()["change_set_id"], self.materialize()["change_set_id"])
        self.assertEqual(self.materialize()["intent_digest"], self.materialize()["intent_digest"])

    def test_stale_base_revision_is_rejected(self):
        request = self.request(base_revision="0" * 64)
        self.assert_code("stale_base_revision", request)

    def test_duplicate_operation_name_is_rejected(self):
        operation = deepcopy(self.operation)
        operation["name"] = self.base["operations"][0]["name"]
        request = self.request(changes=[{"kind": "add_operation", "operation": operation}])
        self.assert_code("duplicate_operation_name", request)

    def test_multiple_changes_are_rejected(self):
        request = self.request(changes=[
            {"kind": "add_operation", "operation": deepcopy(self.operation)},
            {"kind": "add_operation", "operation": deepcopy(self.operation)},
        ])
        self.assert_code("exactly_one_change_required", request)

    def test_replace_delete_and_reorder_are_not_supported(self):
        for kind in ("replace_operation", "delete_operation", "reorder_operation", "patch_service"):
            request = self.request(changes=[{"kind": kind, "operation": deepcopy(self.operation)}])
            self.assert_code("unsupported_change_kind", request)

    def test_unknown_fields_are_rejected_at_every_delta_level(self):
        request = self.request(untrusted_extra=True)
        self.assert_code("delta_request_fields_invalid", request)
        request = self.request(changes=[{
            "kind": "add_operation", "operation": deepcopy(self.operation), "replace": True,
        }])
        self.assert_code("change_fields_invalid", request)
        operation = deepcopy(self.operation)
        operation["description"] = "extra"
        request = self.request(changes=[{"kind": "add_operation", "operation": operation}])
        self.assert_code("operation_fields_invalid", request)

    def test_malformed_nested_input_declaration_is_rejected(self):
        operation = deepcopy(self.operation)
        operation["input"] = [{"name": "name", "type": "String"}]
        request = self.request(changes=[{"kind": "add_operation", "operation": operation}])
        self.assert_code("input_declaration_fields_invalid", request)
        operation["input"] = {"name": "name", "source": "path", "type": "String"}
        request = self.request(changes=[{"kind": "add_operation", "operation": operation}])
        self.assert_code("operation_input_must_be_array", request)

    def test_untrusted_effect_and_capability_are_rejected(self):
        operation = deepcopy(self.operation)
        operation["effects"] = ["production.deploy"]
        request = self.request(changes=[{"kind": "add_operation", "operation": operation}])
        self.assert_code("untrusted_effect", request)
        operation = deepcopy(self.operation)
        operation["capability"] = "admin.root"
        request = self.request(changes=[{"kind": "add_operation", "operation": operation}])
        self.assert_code("untrusted_capability", request)

    def test_service_id_mismatch_is_rejected(self):
        self.assert_code("service_id_mismatch", self.request(service_id="other"))

    def test_non_canonical_operation_is_rejected_by_kernel_validator(self):
        operation = deepcopy(self.operation)
        operation["method"] = "NOT-A-METHOD"
        request = self.request(changes=[{"kind": "add_operation", "operation": operation}])
        self.assert_code("materialized_ir_invalid", request)


    def test_generated_valid_base_services_preserve_every_existing_contract(self):
        rng = random.Random(20261118)
        for base_size in range(1, 13):
            with self.subTest(base_size=base_size):
                generated_base = deepcopy(self.base)
                for index in range(base_size):
                    existing = deepcopy(self.operation)
                    existing["name"] = f"generated_existing_{index}"
                    existing["path"] = f"/generated/{index}/{{name}}"
                    generated_base["operations"].append(existing)
                rng.shuffle(generated_base["operations"])
                new_operation = deepcopy(self.operation)
                new_operation["name"] = "generated_delta_operation"
                new_operation["path"] = f"/generated/new/{base_size}/{{name}}"
                revision = digest(generated_base)
                request = {
                    "service_id": "catalog",
                    "base_revision": revision,
                    "changes": [{"kind": "add_operation", "operation": new_operation}],
                }
                raw = json.dumps(request, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
                first = materialize_add_operation(
                    raw, service_id="catalog", current_service=generated_base,
                    trusted_effects=self.trusted_effects,
                    trusted_capabilities=self.trusted_capabilities,
                )
                second = materialize_add_operation(
                    raw, service_id="catalog", current_service=generated_base,
                    trusted_effects=self.trusted_effects,
                    trusted_capabilities=self.trusted_capabilities,
                )
                self.assertEqual(first["ir"]["operations"][:-1], generated_base["operations"])
                self.assertEqual(first["ir"]["operations"][-1], new_operation)
                self.assertEqual(first["ir"]["service"], generated_base["service"])
                self.assertEqual(first["ir"]["types"], generated_base["types"])
                self.assertEqual(first["change_set_id"], second["change_set_id"])
                self.assertEqual(first["intent_digest"], second["intent_digest"])
                self.assertEqual(first["change_set_id"], digest({
                    "service_id": "catalog", "base_revision": revision, "ir": first["ir"],
                }))

    def test_duplicate_keys_non_finite_values_invalid_utf8_and_size_are_rejected(self):
        with self.assertRaisesRegex(DeltaMaterializationError, "duplicate_json_key"):
            parse_delta_request(b'{"service_id":"catalog","service_id":"other"}')
        with self.assertRaisesRegex(DeltaMaterializationError, "non_finite_json_number"):
            parse_delta_request(b'{"value":NaN}')
        with self.assertRaisesRegex(DeltaMaterializationError, "invalid_utf8"):
            parse_delta_request(b"\xff")
        with self.assertRaisesRegex(DeltaMaterializationError, "delta_payload_too_large"):
            parse_delta_request(b" " * 65537)


if __name__ == "__main__":
    unittest.main()
