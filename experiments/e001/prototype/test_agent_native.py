import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))
from agent_native import Diagnostic, Parser, validate_ir  # noqa: E402


EXAMPLE = (ROOT / "examples" / "catalog.an").read_text(encoding="utf-8")


class ParserTests(unittest.TestCase):
    def test_example_compiles_to_stable_ir(self):
        ir = Parser(EXAMPLE).parse()
        self.assertEqual(ir["ir_version"], 1)
        self.assertEqual(ir["service"], {"name": "Catalog", "version": "1"})
        self.assertEqual(ir["types"], [{"name": "Item", "fields": [
            {"name": "id", "type": "UUID"}, {"name": "name", "type": "String"}
        ]}])
        create = next(item for item in ir["operations"] if item["name"] == "create_item")
        self.assertEqual(create["validation"], ["name.non_empty"])
        self.assertEqual(create["errors"], ["InvalidInput", "Unauthorized"])
        self.assertEqual(ir["operations"][0]["name"], "create_item")
        self.assertEqual(next(item for item in ir["operations"] if item["name"] == "get_item")["effects"], ["repository.read"])

    def test_text_and_structured_ir_fixtures_are_identical(self):
        structured = json.loads((ROOT / "structured" / "catalog.ir.json").read_text(encoding="utf-8"))
        self.assertEqual(Parser(EXAMPLE).parse(), structured)

    def test_unknown_type_reference_is_rejected(self):
        invalid = EXAMPLE.replace("output: Item;", "output: Unknown;")
        with self.assertRaises(Diagnostic) as caught:
            Parser(invalid).parse()
        self.assertEqual(caught.exception.code, "AN020")

    def test_structured_ir_rejects_unknown_properties(self):
        ir = Parser(EXAMPLE).parse()
        ir["operations"][0]["ambient_authority"] = True
        with self.assertRaises(Diagnostic) as caught:
            validate_ir(ir)
        self.assertEqual(caught.exception.code, "AN026")

    def test_structured_ir_rejects_traversal_routes(self):
        ir = Parser(EXAMPLE).parse()
        ir["operations"][0]["path"] = "/items/../secrets"
        with self.assertRaises(Diagnostic) as caught:
            validate_ir(ir)
        self.assertEqual(caught.exception.code, "AN027")

    def test_structured_ir_rejects_unbound_path_inputs(self):
        ir = Parser(EXAMPLE).parse()
        get_item = next(item for item in ir["operations"] if item["name"] == "get_item")
        get_item["input"] = []
        with self.assertRaises(Diagnostic) as caught:
            validate_ir(ir)
        self.assertEqual(caught.exception.code, "AN035")

    def test_structured_ir_rejects_unbound_validation_rules(self):
        ir = Parser(EXAMPLE).parse()
        create_item = next(item for item in ir["operations"] if item["name"] == "create_item")
        create_item["validation"] = ["unknown.non_empty"]
        with self.assertRaises(Diagnostic) as caught:
            validate_ir(ir)
        self.assertEqual(caught.exception.code, "AN036")

    def test_operation_order_is_canonical(self):
        source = EXAMPLE.replace(
            'operation get_item {', 'operation z_item {'
        ).replace(
            'operation create_item {', 'operation a_item {'
        )
        names = [item["name"] for item in Parser(source).parse()["operations"]]
        self.assertEqual(names, ["a_item", "z_item"])

    def test_duplicate_operation_is_rejected(self):
        duplicate = EXAMPLE.replace(
            '\n  operation create_item {', '\n  operation get_item {'
        )
        with self.assertRaises(Diagnostic) as caught:
            Parser(duplicate).parse()
        self.assertEqual(caught.exception.code, "AN005")

    def test_unknown_input_source_is_rejected(self):
        invalid = EXAMPLE.replace("from path;", "from cookie;")
        with self.assertRaises(Diagnostic) as caught:
            Parser(invalid).parse()
        self.assertEqual(caught.exception.code, "AN009")

    def test_non_absolute_path_is_rejected(self):
        invalid = EXAMPLE.replace('path: "/items/{id}";', 'path: "items/{id}";')
        with self.assertRaises(Diagnostic) as caught:
            Parser(invalid).parse()
        self.assertEqual(caught.exception.code, "AN011")

    def test_missing_operation_is_rejected(self):
        invalid = 'service Empty { version: "1"; }'
        with self.assertRaises(Diagnostic) as caught:
            Parser(invalid).parse()
        self.assertEqual(caught.exception.code, "AN007")

    def test_path_parameter_must_have_path_input(self):
        invalid = EXAMPLE.replace("id: UUID from path;", "id: UUID from query;")
        with self.assertRaises(Diagnostic) as caught:
            Parser(invalid).parse()
        self.assertEqual(caught.exception.code, "AN013")

    def test_duplicate_input_field_is_rejected(self):
        invalid = EXAMPLE.replace(
            "id: UUID from path;", "id: UUID from path;" + chr(10) + "      id: UUID from path;"
        )
        with self.assertRaises(Diagnostic) as caught:
            Parser(invalid).parse()
        self.assertEqual(caught.exception.code, "AN008")

    def test_duplicate_effect_is_rejected(self):
        invalid = EXAMPLE.replace(
            "effects: [repository.read];",
            "effects: [repository.read, repository.read];"
        )
        with self.assertRaises(Diagnostic) as caught:
            Parser(invalid).parse()
        self.assertEqual(caught.exception.code, "AN004")

    def test_duplicate_record_field_is_rejected(self):
        invalid = EXAMPLE.replace("type Item {", "type Item {" + chr(10) + "    name: String;")
        with self.assertRaises(Diagnostic) as caught:
            Parser(invalid).parse()
        self.assertEqual(caught.exception.code, "AN018")

    def test_empty_record_is_rejected(self):
        invalid = """service Empty {
  version: "1";
  type Item { }
  operation read {
    method: GET;
    path: "/";
    input { }
    output: Item;
    errors: [];
    validation: [];
    effects: [];
    capability: "items.read";
  }
}"""
        with self.assertRaises(Diagnostic) as caught:
            Parser(invalid).parse()
        self.assertEqual(caught.exception.code, "AN019")



    def test_parser_and_ir_validator_accept_every_declared_http_method(self):
        for method in ("GET", "POST", "PUT", "PATCH", "DELETE"):
            with self.subTest(method=method):
                Parser(EXAMPLE.replace("method: GET;", f"method: {method};")).parse()

    def test_header_input_is_supported_by_parser_and_ir_validator(self):
        source = EXAMPLE.replace(
            "id: UUID from path;",
            "id: UUID from path;" + chr(10) + "      trace_id: String from header;"
        )
        ir = Parser(source).parse()
        get_item = next(item for item in ir["operations"] if item["name"] == "get_item")
        self.assertIn({"name": "trace_id", "type": "String", "source": "header"}, get_item["input"])
        validate_ir(ir)

    def test_invalid_json_string_escape_has_stable_diagnostic(self):
        invalid = 'service Bad { version: "' + chr(92) + 'q"; operation read { method: GET; path: "/"; input { } output: String; errors: []; validation: []; effects: []; capability: "read"; } }'
        with self.assertRaises(Diagnostic) as caught:
            Parser(invalid).parse()
        self.assertEqual(caught.exception.code, "AN038")


    def test_boolean_ir_version_is_not_accepted_as_integer_version(self):
        ir = Parser(EXAMPLE).parse()
        ir["ir_version"] = True
        with self.assertRaises(Diagnostic) as caught:
            validate_ir(ir)
        self.assertEqual(caught.exception.code, "AN021")

    def test_encoded_backslash_and_noncanonical_routes_are_rejected(self):
        invalid_paths = (
            "/items/%2e%2e/secrets",
            "/items/" + chr(92) + "secrets",
            "/items/" + chr(0) + "secrets",
            "/items/cafe" + chr(0x301),
        )
        for path in invalid_paths:
            with self.subTest(path=repr(path)):
                ir = Parser(EXAMPLE).parse()
                ir["operations"][0]["path"] = path
                with self.assertRaises(Diagnostic) as caught:
                    validate_ir(ir)
                self.assertEqual(caught.exception.code, "AN027")


    def test_every_operation_must_declare_authorization_denial(self):
        invalid = EXAMPLE.replace(
            "errors: [InvalidInput, NotFound, Unauthorized];",
            "errors: [InvalidInput, NotFound];"
        )
        with self.assertRaises(Diagnostic) as caught:
            Parser(invalid).parse()
        self.assertEqual(caught.exception.code, "AN039")

    def test_operations_with_inputs_must_declare_invalid_input(self):
        invalid = EXAMPLE.replace(
            "errors: [InvalidInput, NotFound, Unauthorized];",
            "errors: [NotFound, Unauthorized];"
        )
        with self.assertRaises(Diagnostic) as caught:
            Parser(invalid).parse()
        self.assertEqual(caught.exception.code, "AN040")

if __name__ == "__main__":
    unittest.main()
