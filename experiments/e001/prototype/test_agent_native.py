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


if __name__ == "__main__":
    unittest.main()
