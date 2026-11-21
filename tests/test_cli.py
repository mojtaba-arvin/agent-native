from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
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
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.service = self.root / "catalog.an"
        self.service.write_text(SERVICE, encoding="utf-8")

    def tearDown(self):
        self.temporary.cleanup()

    def invoke(self, *arguments):
        return subprocess.run(
            [sys.executable, "-I", "-m", "agent_native.cli", *arguments],
            cwd=self.root,
            capture_output=True,
            text=True,
            timeout=10,
        )

    def test_help_exposes_all_five_commands(self):
        result = self.invoke("--help")
        self.assertEqual(result.returncode, 0)
        for command in ("check", "run", "inspect", "worker", "audit"):
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


if __name__ == "__main__":
    unittest.main()
