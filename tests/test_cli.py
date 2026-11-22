from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
import venv
from pathlib import Path


SERVICE = """
service catalog {
    version: "1.0";
    operation get_item {
        method: GET;
        path: "/items/{id}";
        input {
            id: String from path;
        }
        output: String;
        errors: [InvalidInput, Unauthorized];
        validation: [];
        effects: [repository.read];
        capability: "items.read";
    }
}
"""


class UnifiedCLITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.install_root = tempfile.TemporaryDirectory(prefix="agent-native-cli-venv-")
        cls.environment = Path(cls.install_root.name) / "venv"
        venv.EnvBuilder(with_pip=True, clear=True).create(cls.environment)
        cls.cli_python = cls.environment / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
        subprocess.run(
            [str(cls.cli_python), "-m", "pip", "install", "--no-deps", str(Path(__file__).resolve().parents[1])],
            cwd=Path(__file__).resolve().parents[1],
            check=True,
            capture_output=True,
            text=True,
            timeout=180,
        )

    @classmethod
    def tearDownClass(cls):
        cls.install_root.cleanup()

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.service = self.root / "catalog.an"
        self.service.write_text(SERVICE, encoding="utf-8")

    def tearDown(self):
        self.temporary.cleanup()

    def invoke(self, *arguments):
        return subprocess.run(
            [str(self.cli_python), "-I", "-m", "agent_native.cli", *arguments],
            cwd=self.root,
            capture_output=True,
            text=True,
            timeout=10,
        )

    def test_help_exposes_all_seven_commands(self):
        result = self.invoke("--help")
        self.assertEqual(result.returncode, 0)
        for command in ("check", "run", "inspect", "worker", "audit", "diagnose", "schema"):
            self.assertIn(command, result.stdout)

    def test_check_and_inspect_use_explicit_service_path(self):
        checked = self.invoke("check", "--service", str(self.service))
        self.assertEqual(checked.returncode, 0, checked.stderr)
        self.assertEqual(json.loads(checked.stdout)["status"], "valid")
        self.assertEqual(json.loads(checked.stdout)["service_path"], str(self.service))
        inspected = self.invoke("inspect", "--service", str(self.service))
        self.assertEqual(inspected.returncode, 0)
        self.assertEqual(json.loads(inspected.stdout)["service"]["name"], "catalog")

    def test_run_is_dry_run_only_until_handlers_are_registered(self):
        planned = self.invoke("run", "--service", str(self.service), "--method", "GET", "--path", "/items/42", "--dry-run")
        self.assertEqual(planned.returncode, 0, planned.stderr)
        result = json.loads(planned.stdout)
        self.assertFalse(result["execution_started"])
        self.assertEqual(result["path_parameters"], {"id": "42"})
        blocked = self.invoke("run", "--service", str(self.service), "--method", "GET", "--path", "/items/42")
        self.assertEqual(blocked.returncode, 4)
        self.assertEqual(json.loads(blocked.stderr)["error"]["code"], "runtime_handlers_not_configured")

    def test_worker_inspects_only_the_explicit_queue(self):
        queue = self.root / "jobs.jsonl"
        queue.write_text(
            '{"task_id":"a","state":"queued"}\n{"task_id":"b","state":"complete"}\n',
            encoding="utf-8",
        )
        result = self.invoke("worker", "--service-id", "catalog", "--queue", str(queue))
        self.assertEqual(result.returncode, 0)
        payload = json.loads(result.stdout)
        self.assertFalse(payload["execution_started"])
        self.assertEqual(payload["queued_records"], 1)

    def test_audit_validates_and_summarizes_explicit_event_file(self):
        events = self.root / "audit.jsonl"
        events.write_text(
            '{"event_id":"1","decision":"allow","reason_code":"ALLOW"}\n'
            '{"event_id":"2","decision":"deny","reason_code":"MISSING_CAPABILITY"}\n',
            encoding="utf-8",
        )
        result = self.invoke("audit", "--events", str(events))
        self.assertEqual(result.returncode, 0)
        payload = json.loads(result.stdout)
        self.assertEqual((payload["events"], payload["allow"], payload["deny"]), (2, 1, 1))

    def test_missing_service_and_malformed_queue_return_machine_errors(self):
        missing = self.invoke("check", "--service", str(self.root / "missing.an"))
        self.assertEqual(missing.returncode, 3)
        self.assertEqual(json.loads(missing.stderr)["error"]["code"], "service_file_unreadable")
        queue = self.root / "bad.jsonl"
        queue.write_text("{not-json}", encoding="utf-8")
        malformed = self.invoke("worker", "--service-id", "catalog", "--queue", str(queue))
        self.assertEqual(malformed.returncode, 3)
        self.assertEqual(json.loads(malformed.stderr)["error"]["code"], "invalid_queue_json")

    def test_malformed_audit_event_returns_machine_error(self):
        events = self.root / "bad-audit.jsonl"
        events.write_text('{"event_id":"x","decision":"maybe","reason_code":"UNKNOWN"}', encoding="utf-8")
        result = self.invoke("audit", "--events", str(events))
        self.assertEqual(result.returncode, 3)
        self.assertEqual(json.loads(result.stderr)["error"]["code"], "invalid_audit_decision")

    def test_argument_errors_are_machine_readable(self):
        result = self.invoke("check")
        self.assertEqual(result.returncode, 2)
        self.assertEqual(json.loads(result.stderr)["error"]["code"], "invalid_arguments")


    def test_schema_discovery_lists_packaged_schemas_and_emits_exact_schema(self):
        listed = self.invoke("schema", "--list")
        self.assertEqual(listed.returncode, 0, listed.stderr)
        names = {item["name"] for item in json.loads(listed.stdout)["schemas"]}
        self.assertEqual(names, {
            "gateway-plan-v1", "gateway-proposal-v1", "gateway-validation-v1",
            "service-ir-v1", "service-manifest-v1", "service-manifest-v2",
        })
        selected = self.invoke("schema", "--name", "service-ir-v1")
        self.assertEqual(selected.returncode, 0, selected.stderr)
        schema = json.loads(selected.stdout)["schema"]
        self.assertEqual(schema["title"], "Agent Native Service IR v1")
        self.assertEqual(schema["$schema"], "https://json-schema.org/draft/2020-12/schema")

    def test_unknown_schema_returns_available_identifiers(self):
        result = self.invoke("schema", "--name", "not-a-schema")
        self.assertEqual(result.returncode, 3)
        error = json.loads(result.stderr)["error"]
        self.assertEqual(error["code"], "schema_not_found")
        self.assertIn("service-ir-v1", error["available_schemas"])

    def test_diagnose_returns_empty_diagnostics_for_valid_contract(self):
        result = self.invoke("diagnose", "--service", str(self.service))
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["status"], "valid")
        self.assertEqual(payload["diagnostics"], [])

    def test_parser_failure_includes_stable_code_location_and_fix_hint(self):
        invalid = self.root / "invalid.an"
        invalid.write_text(SERVICE.replace("id: String from path;", "id: MissingRecord from path;"), encoding="utf-8")
        result = self.invoke("diagnose", "--service", str(invalid))
        self.assertEqual(result.returncode, 3)
        error = json.loads(result.stderr)["error"]
        self.assertEqual(error["code"], "AN020")
        diagnostic = error["diagnostics"][0]
        self.assertEqual(diagnostic["code"], "AN020")
        self.assertGreater(diagnostic["source_span"]["line"], 0)
        self.assertGreater(diagnostic["source_span"]["column"], 0)
        self.assertIn("Declare the referenced record type", diagnostic["fix_hint"])

if __name__ == "__main__":
    unittest.main()
