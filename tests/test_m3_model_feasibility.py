from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
E007 = ROOT / "experiments" / "e007"
E009 = ROOT / "experiments" / "e009"
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
        self.assertEqual(candidates["status"], "provisional_bootstrap")
        self.assertEqual(candidates["cost"]["paid_api_usd_ceiling"], 0)
        self.assertFalse(candidates["cost"]["gpu_allowed"])
        self.assertFalse(candidates["oracle"]["hidden_oracle_enabled"])
        self.assertEqual(
            [item["tier"] for item in candidates["models"]],
            ["weak", "medium", "strong"],
        )
        self.assertTrue(all(item["manifest_sha256"] is None for item in candidates["models"]))
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
        self.assertNotIn("pull_request:", workflow)
        self.assertNotIn("schedule:", workflow)
        self.assertIn("--network none", workflow)
        self.assertIn("--network container:ollama-smoke", workflow)
        self.assertIn("--read-only", workflow)
        self.assertIn("--cap-drop ALL", workflow)
        self.assertIn("--security-opt no-new-privileges", workflow)
        self.assertIn("/api/show", workflow)
        self.assertIn("manifest_sha256", workflow)

    def test_model_smoke_disables_apply_and_uses_existing_e009_agent(self):
        smoke = (E007 / "m3_model_smoke.py").read_text(encoding="utf-8")
        self.assertIn("local_agent.run(args)", smoke)
        self.assertIn("allow_sandbox_apply=False", smoke)
        self.assertIn("ollama_runtime_version_not_pinned", smoke)
        self.assertIn("model_quantization_mismatch", smoke)
        self.assertIn('"service.apply" in sequence', smoke)
        self.assertIn('"hidden_oracle_used": False', smoke)
        self.assertIn('"paid_api_usd": 0', smoke)


if __name__ == "__main__":
    unittest.main()
