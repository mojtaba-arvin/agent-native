import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))
from agent_native import Diagnostic, Parser  # noqa: E402


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


if __name__ == "__main__":
    unittest.main()
