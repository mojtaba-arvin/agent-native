from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from agent_native import Diagnostic, IR_VERSION, Parser, validate_ir

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = ROOT / "schemas" / "service-ir-v1.schema.json"
BUILTINS = {"String", "UUID", "Integer", "Boolean", "Bytes", "Float"}


def catalog_ir() -> dict:
    source = (ROOT / "services" / "catalog" / "service.an").read_text(encoding="utf-8")
    return Parser(source).parse()


def inventory_ir() -> dict:
    source = (ROOT / "services" / "inventory" / "service.an").read_text(encoding="utf-8")
    return Parser(source).parse()


class ServiceIRV1ContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.ir = catalog_ir()

    def assert_invalid(self, ir: object, code: str) -> None:
        with self.assertRaises(Diagnostic) as raised:
            validate_ir(ir)
        self.assertEqual(raised.exception.code, code)

    def test_schema_is_draft_2020_12_with_stable_v1_identifier(self) -> None:
        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        self.assertEqual(schema["$schema"], "https://json-schema.org/draft/2020-12/schema")
        self.assertEqual(schema["$id"], "https://agent-native.dev/schemas/service-ir-v1.schema.json")
        self.assertEqual(schema["properties"]["ir_version"], {"type": "integer", "const": 1})
        self.assertEqual(set(schema["required"]), {"ir_version", "service", "types", "operations"})

    def test_schema_closes_every_object_boundary(self) -> None:
        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        self.assertIs(schema["additionalProperties"], False)
        definitions = schema["$defs"]
        for name in ("service", "recordField", "typeDeclaration", "inputField", "operation"):
            with self.subTest(definition=name):
                self.assertIs(definitions[name]["additionalProperties"], False)

    def test_schema_expresses_required_operation_authority_errors(self) -> None:
        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        operation = schema["$defs"]["operation"]
        self.assertEqual(operation["properties"]["errors"]["contains"], {"const": "Unauthorized"})
        conditional = operation["allOf"][0]
        self.assertEqual(conditional["then"]["properties"]["errors"]["contains"], {"const": "InvalidInput"})

    def test_parser_emits_the_frozen_version_and_exact_root_shape(self) -> None:
        self.assertEqual(IR_VERSION, 1)
        self.assertEqual(self.ir["ir_version"], IR_VERSION)
        self.assertEqual(set(self.ir), {"ir_version", "service", "types", "operations"})
        validate_ir(self.ir)

    def test_real_catalog_and_inventory_services_are_valid_v1_ir(self) -> None:
        for ir in (catalog_ir(), inventory_ir()):
            with self.subTest(service=ir["service"]["name"]):
                self.assertEqual(ir["ir_version"], 1)
                validate_ir(ir)

    def test_unknown_or_unsupported_versions_fail_closed(self) -> None:
        for value in (True, 0, 2, 1.0, "1", None):
            candidate = copy.deepcopy(self.ir)
            candidate["ir_version"] = value
            with self.subTest(ir_version=value):
                self.assert_invalid(candidate, "AN021")

        candidate = copy.deepcopy(self.ir)
        del candidate["ir_version"]
        self.assert_invalid(candidate, "AN021")

    def test_unknown_root_and_service_properties_are_rejected(self) -> None:
        candidate = copy.deepcopy(self.ir)
        candidate["ambient_authority"] = True
        self.assert_invalid(candidate, "AN021")

        candidate = copy.deepcopy(self.ir)
        candidate["service"]["description"] = "not part of v1"
        self.assert_invalid(candidate, "AN022")

    def test_unknown_operation_and_input_properties_are_rejected(self) -> None:
        candidate = copy.deepcopy(self.ir)
        candidate["operations"][0]["ambient_authority"] = True
        self.assert_invalid(candidate, "AN026")

        candidate = copy.deepcopy(self.ir)
        candidate["operations"][0]["input"][0]["optional"] = True
        self.assert_invalid(candidate, "AN031")

    def test_service_identity_and_nonempty_operations_are_required(self) -> None:
        candidate = copy.deepcopy(self.ir)
        candidate["service"]["name"] = "not-valid"
        self.assert_invalid(candidate, "AN014")

        candidate = copy.deepcopy(self.ir)
        candidate["service"]["version"] = ""
        self.assert_invalid(candidate, "AN022")

        candidate = copy.deepcopy(self.ir)
        candidate["operations"] = []
        self.assert_invalid(candidate, "AN023")

    def test_duplicate_and_reserved_type_names_are_rejected(self) -> None:
        candidate = copy.deepcopy(self.ir)
        candidate["types"].append(copy.deepcopy(candidate["types"][0]))
        self.assert_invalid(candidate, "AN016")

        candidate = copy.deepcopy(self.ir)
        candidate["types"][0]["name"] = "String"
        self.assert_invalid(candidate, "AN016")

    def test_record_fields_must_be_nonempty_unique_and_resolve(self) -> None:
        candidate = copy.deepcopy(self.ir)
        candidate["types"][0]["fields"] = []
        self.assert_invalid(candidate, "AN019")

        candidate = copy.deepcopy(self.ir)
        candidate["types"][0]["fields"].append(copy.deepcopy(candidate["types"][0]["fields"][0]))
        self.assert_invalid(candidate, "AN018")

        candidate = copy.deepcopy(self.ir)
        candidate["types"][0]["fields"][0]["type"] = "UnknownRecord"
        self.assert_invalid(candidate, "AN020")

    def test_operation_names_routes_and_methods_must_be_unambiguous(self) -> None:
        candidate = copy.deepcopy(self.ir)
        candidate["operations"].append(copy.deepcopy(candidate["operations"][0]))
        self.assert_invalid(candidate, "AN005")

        candidate = copy.deepcopy(self.ir)
        duplicate = copy.deepcopy(candidate["operations"][0])
        duplicate["name"] = "different_operation"
        candidate["operations"].append(duplicate)
        self.assert_invalid(candidate, "AN028")

        candidate = copy.deepcopy(self.ir)
        candidate["operations"][0]["method"] = "TRACE"
        self.assert_invalid(candidate, "AN003")

    def test_unsafe_or_noncanonical_routes_are_rejected(self) -> None:
        invalid_paths = (
            "items",
            "/items?admin=true",
            "/items#fragment",
            "/items/%2e%2e/secrets",
            "/items/../secrets",
            "/items//secrets",
            "/items/" + chr(92) + "secrets",
            "/items/" + chr(0) + "secrets",
            "/items/cafe" + chr(0x301),
        )
        for path in invalid_paths:
            candidate = copy.deepcopy(self.ir)
            candidate["operations"][0]["path"] = path
            with self.subTest(path=repr(path)):
                self.assert_invalid(candidate, "AN027")

    def test_path_placeholders_must_match_path_inputs_exactly(self) -> None:
        candidate = copy.deepcopy(self.ir)
        get_item = next(op for op in candidate["operations"] if op["name"] == "get_item")
        get_item["input"] = []
        self.assert_invalid(candidate, "AN035")

        candidate = copy.deepcopy(self.ir)
        get_item = next(op for op in candidate["operations"] if op["name"] == "get_item")
        get_item["path"] = "/items/{id}/{id}"
        self.assert_invalid(candidate, "AN035")

    def test_get_operations_cannot_declare_body_inputs(self) -> None:
        candidate = copy.deepcopy(self.ir)
        operation = next(op for op in candidate["operations"] if op["method"] == "GET")
        operation["path"] = "/items"
        operation["input"] = [{"name": "name", "type": "String", "source": "body"}]
        operation["errors"] = sorted(set(operation["errors"]) | {"InvalidInput"})
        self.assert_invalid(candidate, "AN037")

    def test_operation_type_references_must_resolve(self) -> None:
        candidate = copy.deepcopy(self.ir)
        candidate["operations"][0]["output"] = "UnknownRecord"
        self.assert_invalid(candidate, "AN020")

        candidate = copy.deepcopy(self.ir)
        candidate["operations"][0]["output"] = "List<UnknownRecord>"
        self.assert_invalid(candidate, "AN020")

        candidate = copy.deepcopy(self.ir)
        candidate["operations"][0]["output"] = "List<Item>"
        validate_ir(candidate)

    def test_capability_and_authorization_errors_are_mandatory(self) -> None:
        candidate = copy.deepcopy(self.ir)
        candidate["operations"][0]["capability"] = ""
        self.assert_invalid(candidate, "AN029")

        candidate = copy.deepcopy(self.ir)
        candidate["operations"][0]["errors"].remove("Unauthorized")
        self.assert_invalid(candidate, "AN039")

    def test_operations_with_inputs_must_declare_invalid_input(self) -> None:
        candidate = copy.deepcopy(self.ir)
        operation = next(op for op in candidate["operations"] if op["input"])
        operation["errors"].remove("InvalidInput")
        self.assert_invalid(candidate, "AN040")

    def test_validation_rules_must_be_supported_and_bound_to_string_inputs(self) -> None:
        candidate = copy.deepcopy(self.ir)
        operation = next(op for op in candidate["operations"] if op["input"])
        operation["validation"] = ["missing_field.non_empty"]
        self.assert_invalid(candidate, "AN036")

        candidate = copy.deepcopy(self.ir)
        operation = next(op for op in candidate["operations"] if op["input"])
        field = operation["input"][0]
        field["type"] = "UUID"
        operation["validation"] = [field["name"] + ".non_empty"]
        self.assert_invalid(candidate, "AN036")

    def test_error_validation_and_effect_names_are_nonempty_and_unique(self) -> None:
        for key in ("errors", "validation", "effects"):
            candidate = copy.deepcopy(self.ir)
            operation = candidate["operations"][0]
            values = operation[key]
            if values:
                values.append(values[0])
            else:
                values.append("")
            with self.subTest(field=key):
                self.assert_invalid(candidate, "AN032" if "" in values else "AN004")


if __name__ == "__main__":
    unittest.main()
