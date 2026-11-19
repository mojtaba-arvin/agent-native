from __future__ import annotations

import hashlib
import json
import re
import sys
import textwrap
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
E007 = ROOT / "experiments" / "e007"
E009 = ROOT / "experiments" / "e009"
sys.path.insert(0, str(E007))
sys.path.insert(0, str(E009))
sys.path.insert(0, str(E007 / "evaluator"))

from m3_model_smoke import candidate_sha256, tool_sequence, validate_ollama_server_config  # noqa: E402


class M3ModelFeasibilityTests(unittest.TestCase):
    def _valid_server_config(self):
        return {
            "user": "1001:1001",
            "network_mode": "none",
            "memory_bytes": 10 * 1024**3,
            "nano_cpus": 3_000_000_000,
            "pids_limit": 128,
            "readonly_rootfs": True,
            "cap_drop": ["ALL"],
            "security_opt": ["no-new-privileges"],
            "tmp_noexec": True,
            "model_mount_read_only": True,
        }

    def test_accepts_isolated_ollama_server_configuration(self):
        validate_ollama_server_config(self._valid_server_config())

    def test_rejects_networked_ollama_server(self):
        config = self._valid_server_config()
        config["network_mode"] = "bridge"
        with self.assertRaises(RuntimeError):
            validate_ollama_server_config(config)

    def test_rejects_root_ollama_server(self):
        config = self._valid_server_config()
        config["user"] = "0:0"
        with self.assertRaises(RuntimeError):
            validate_ollama_server_config(config)

    def test_rejects_writable_model_mount(self):
        config = self._valid_server_config()
        config["model_mount_read_only"] = False
        with self.assertRaises(RuntimeError):
            validate_ollama_server_config(config)

    def test_rejects_exec_enabled_server_tmpfs(self):
        config = self._valid_server_config()
        config["tmp_noexec"] = False
        with self.assertRaises(RuntimeError):
            validate_ollama_server_config(config)

    def test_model_candidates_are_provisional_and_zero_paid(self):
        candidates = json.loads((E007 / "model_candidates.json").read_text(encoding="utf-8"))
        self.assertEqual(candidates["status"], "provisional_manifest_pinned")
        self.assertEqual(candidates["cost"]["paid_api_usd_ceiling"], 0)
        self.assertFalse(candidates["cost"]["gpu_allowed"])
        self.assertFalse(candidates["oracle"]["hidden_oracle_enabled"])
        self.assertEqual(
            [item["tier"] for item in candidates["models"]],
            ["weak", "medium", "strong"],
        )
        self.assertEqual(
            [item["tag"] for item in candidates["models"]],
            [
                "ibm/granite4:350m-h-q4_K_M",
                "ibm/granite4:1b-h-q4_K_M",
                "ibm/granite4:3b-h",
            ],
        )
        lock = json.loads((E007 / "model_lock.json").read_text(encoding="utf-8"))
        self.assertEqual(lock["status"], "provisional_pinned_not_qualified")
        self.assertEqual(lock["runtime"]["version"], "0.40.15")
        self.assertEqual(lock["provenance"]["verification_run_id"], 44511342601)
        self.assertEqual(lock["provenance"]["verification_artifact_id"], 14524351767)
        locked = {item["tag"]: item for item in lock["models"]}
        self.assertEqual(set(locked), {item["tag"] for item in candidates["models"]})
        for item in candidates["models"]:
            pin = locked[item["tag"]]
            self.assertEqual(item["manifest_sha256"], pin["manifest_sha256"])
            self.assertEqual(item["config_digest"], pin["config_digest"])
            self.assertEqual(item["model_size_bytes"], pin["model_size_bytes"])
            self.assertEqual(item["quantization_expected"], pin["quantization_level"])
            self.assertTrue(item["manifest_sha256"])
            self.assertTrue(pin["layers"])
            self.assertTrue(item["tool_call_smoke"].startswith("progressive_failed_"))
            self.assertEqual(item["initial_bootstrap_run_id"], 44509769849)
            self.assertEqual(item["last_feasibility_run_id"], 44511342601)
            self.assertEqual(item["upfront_tool_call_smoke"], "pending")
            self.assertTrue(item["last_failure_code"])
        self.assertTrue(all(item["quantization_expected"] == "Q4_K_M" for item in candidates["models"]))

    def test_tool_sequence_reads_gateway_operations(self):
        with tempfile.TemporaryDirectory() as temp:
            run_dir = Path(temp)
            trace = [
                {"request": {"tool": "service.inspect"}},
                {"request": {"tool": "service.propose_delta"}},
                {"request": {"tool": "service.validate"}},
                {"request": {"tool": "service.plan"}},
            ]
            (run_dir / "tool-trace.jsonl").write_text(
                "".join(json.dumps(item) + "\n" for item in trace),
                encoding="utf-8",
            )
            self.assertEqual(
                tool_sequence(run_dir),
                ["service.inspect", "service.propose_delta", "service.validate", "service.plan"],
            )

    def test_candidate_hash_is_computed_from_exact_file_bytes(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "candidate.json"
            raw = b'{"change_set_id":"abc"}\n'
            path.write_bytes(raw)
            self.assertEqual(
                candidate_sha256({"candidate_path": str(path)}),
                hashlib.sha256(raw).hexdigest(),
            )

    def test_workflow_is_not_pr_or_schedule_triggered_and_inference_is_no_network(self):
        workflow = (ROOT / ".github" / "workflows" / "m3-model-feasibility.yml").read_text(encoding="utf-8")
        self.assertIn("workflow_dispatch:", workflow)
        self.assertIn("branches:", workflow)
        self.assertIn("research/reboot-core", workflow)
        self.assertIn("allowed=false", workflow)
        self.assertIn("needs.guard.outputs.allowed == 'true'", workflow)
        self.assertNotIn("pull_request:", workflow)
        self.assertNotIn("schedule:", workflow)
        self.assertIn("--network none", workflow)
        self.assertIn("--network container:ollama-smoke", workflow)
        self.assertIn("--read-only", workflow)
        self.assertIn("--cap-drop ALL", workflow)
        self.assertIn("--security-opt no-new-privileges", workflow)
        self.assertIn("/api/show", workflow)
        self.assertIn("runner-info.json", workflow)
        self.assertIn("manifest_sha256", workflow)
        self.assertIn("disk_after_pull", workflow)
        self.assertIn("model_lock.json", workflow)
        self.assertIn("model_lock_mismatch", workflow)
        self.assertIn("model_lock_sha256", workflow)

    def test_embedded_python_workflow_scripts_are_syntactically_valid(self):
        workflow = (ROOT / ".github" / "workflows" / "m3-model-feasibility.yml").read_text(encoding="utf-8")
        scripts = re.findall(r"(?ms)^[ \t]*python3\b[^\n]*<<'PY'[ \t]*\n(.*?)^[ \t]*PY[ \t]*$", workflow)
        self.assertGreaterEqual(len(scripts), 3, "expected all embedded Python heredocs to be discovered")
        for index, script in enumerate(scripts):
            with self.subTest(script=index):
                compile(textwrap.dedent(script), f"m3-model-feasibility-heredoc-{index}", "exec")

    def test_model_smoke_disables_apply_and_uses_existing_e009_agent(self):
        smoke = (E007 / "m3_model_smoke.py").read_text(encoding="utf-8")
        self.assertIn("local_agent.run(args)", smoke)
        self.assertIn("allow_sandbox_apply=False", smoke)
        self.assertIn('runtime_lock.get("version")', smoke)
        self.assertIn("model_lock_runtime_mismatch", smoke)
        self.assertIn("model_quantization_mismatch", smoke)
        self.assertIn("RUNNER_INFO", smoke)
        self.assertIn("model_store_disk_after_pull", smoke)
        self.assertIn('"service.apply" in sequence', smoke)
        self.assertIn('"hidden_oracle_used": False', smoke)
        self.assertIn('"paid_api_usd": 0', smoke)
        self.assertIn('MODEL_LOCK', smoke)
        self.assertIn('model_lock_sha256', smoke)
        self.assertIn('expected_lock_sha256', smoke)
        self.assertIn('for arm in ("progressive", "upfront")', smoke)
        self.assertIn('"tool_schema_arm": arm', smoke)
        self.assertIn('"tool_schema_arms": ["progressive", "upfront"]', smoke)


if __name__ == "__main__":
    unittest.main()
