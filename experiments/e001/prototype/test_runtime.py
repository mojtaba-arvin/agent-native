import copy
import unittest
from pathlib import Path

from agent_native import Parser
from runtime import ReferenceRuntime, RuntimeFault
from security_model import Grant, RequestContext


ROOT = Path(__file__).resolve().parents[1]
SOURCE = (ROOT / "examples" / "catalog.an").read_text(encoding="utf-8")
TRUSTED_EFFECTS = {"repository.read", "repository.write"}


class ReferenceRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.runtime = ReferenceRuntime.from_source(
            SOURCE, trusted_effects=TRUSTED_EFFECTS
        )
        self.context = RequestContext(
            principal_id="user-1",
            tenant_id="tenant-a",
            now=100,
            grants=(
                Grant("user-1", "tenant-a", "items.read", "/items"),
                Grant("user-1", "tenant-a", "items.create", "/items"),
            ),
        )

    def test_textual_contract_executes_create_and_get(self):
        created = self.runtime.dispatch(
            "POST", "/items", {"name": "Desk lamp"}, self.context
        )
        fetched = self.runtime.dispatch(
            "GET", f"/items/{created['id']}", {}, self.context
        )
        self.assertEqual(fetched, created)
        self.assertEqual(created["name"], "Desk lamp")

    def test_unauthorized_operation_is_denied(self):
        context = RequestContext("user-2", "tenant-a", 100, ())
        with self.assertRaises(RuntimeFault) as caught:
            self.runtime.dispatch("POST", "/items", {"name": "Desk lamp"}, context)
        self.assertEqual(caught.exception.code, "Unauthorized")

    def test_validation_and_deterministic_errors(self):
        with self.assertRaises(RuntimeFault) as caught:
            self.runtime.dispatch("POST", "/items", {"name": "  "}, self.context)
        self.assertEqual(caught.exception.code, "InvalidInput")

        missing_id = "00000000-0000-0000-0000-000000000099"
        with self.assertRaises(RuntimeFault) as caught:
            self.runtime.dispatch("GET", f"/items/{missing_id}", {}, self.context)
        self.assertEqual(caught.exception.code, "NotFound")

    def test_method_and_route_are_derived_from_ir(self):
        with self.assertRaises(RuntimeFault) as caught:
            self.runtime.dispatch("DELETE", "/items", {}, self.context)
        self.assertEqual(caught.exception.code, "METHOD_NOT_ALLOWED")
        with self.assertRaises(RuntimeFault) as caught:
            self.runtime.dispatch("GET", "/unknown", {}, self.context)
        self.assertEqual(caught.exception.code, "ROUTE_NOT_FOUND")

    def test_untrusted_effect_in_ir_is_rejected_before_authorization(self):
        ir = Parser(SOURCE).parse()
        create = next(item for item in ir["operations"] if item["name"] == "create_item")
        create["effects"].append("network.egress")
        runtime = ReferenceRuntime(ir, trusted_effects=TRUSTED_EFFECTS)
        with self.assertRaises(RuntimeFault) as caught:
            runtime.dispatch("POST", "/items", {"name": "Desk lamp"}, self.context)
        self.assertEqual(caught.exception.code, "UNTRUSTED_EFFECT")



    def test_header_inputs_are_case_insensitive_and_required(self):
        source = SOURCE.replace(
            "id: UUID from path;",
            "id: UUID from path;" + chr(10) + "      trace_id: String from header;"
        ).replace(
            "errors: [NotFound, Unauthorized];",
            "errors: [InvalidInput, NotFound, Unauthorized];"
        )
        runtime = ReferenceRuntime.from_source(source, trusted_effects=TRUSTED_EFFECTS)
        created = runtime.dispatch("POST", "/items", {"name": "Desk lamp"}, self.context)
        fetched = runtime.dispatch(
            "GET", f"/items/{created['id']}", {}, self.context,
            headers={"TRACE_ID": "trace-123"}
        )
        self.assertEqual(fetched, created)
        with self.assertRaises(RuntimeFault) as caught:
            runtime.dispatch("GET", f"/items/{created['id']}", {}, self.context)
        self.assertEqual(caught.exception.code, "InvalidInput")

if __name__ == "__main__":
    unittest.main()
