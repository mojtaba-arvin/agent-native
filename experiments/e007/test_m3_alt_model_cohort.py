from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from argparse import Namespace

from m3_alt_model_cohort import collect, model_manifest_path, observed_model, seal, verify


class AlternativeModelCohortTests(unittest.TestCase):
    def test_ollama_tag_paths_support_library_and_namespaced_models(self):
        root = Path("/models")
        self.assertEqual(
            model_manifest_path(root, "qwen3:1.7b"),
            root / "manifests/registry.ollama.ai/library/qwen3/1.7b",
        )
        self.assertEqual(
            model_manifest_path(root, "ibm/granite4:3b-h"),
            root / "manifests/registry.ollama.ai/ibm/granite4/3b-h",
        )

    def test_observed_model_records_actual_manifest_and_layer_digests(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            path = model_manifest_path(root, "qwen3:1.7b")
            path.parent.mkdir(parents=True)
            raw = json.dumps({
                "config": {"digest": "sha256:config"},
                "layers": [
                    {"digest": "sha256:model", "size": 1234, "mediaType": "application/vnd.ollama.image.model"},
                    {"digest": "sha256:template", "size": 55, "mediaType": "application/vnd.ollama.image.template"},
                ],
            }).encode()
            path.write_bytes(raw)
            result = observed_model(
                root,
                {"tier": "weak", "tag": "qwen3:1.7b", "quantization_expected": "Q4_K_M"},
                {"details": {"quantization_level": "Q4_K_M", "parameter_size": "1.8B", "format": "gguf", "family": "qwen3"}},
            )
            self.assertEqual(result["manifest_sha256"], hashlib.sha256(raw).hexdigest())
            self.assertEqual(result["config_digest"], "sha256:config")
            self.assertEqual(result["model_size_bytes"], 1234)
            self.assertEqual([item["digest"] for item in result["layers"]], ["sha256:model", "sha256:template"])


    def test_bootstrap_seal_and_offline_verification_bind_exact_digests(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            model_dir = root / "models"
            details_dir = root / "details"
            details_dir.mkdir()
            tag = "qwen3:1.7b"
            manifest_path = model_manifest_path(model_dir, tag)
            manifest_path.parent.mkdir(parents=True)
            manifest_path.write_text(json.dumps({
                "config": {"digest": "sha256:config"},
                "layers": [{"digest": "sha256:model", "size": 123, "mediaType": "application/vnd.ollama.image.model"}],
            }), encoding="utf-8")
            (details_dir / (hashlib.sha256(tag.encode()).hexdigest() + ".json")).write_text(
                json.dumps({"details": {"quantization_level": "Q4_K_M", "parameter_size": "1.8B", "format": "gguf", "family": "qwen3"}}),
                encoding="utf-8",
            )
            candidates = root / "candidates.json"
            candidates.write_text(json.dumps({
                "schema_version": 2, "cohort": "m3-007-test", "status": "bootstrap_pending",
                "runtime": {"version": "0.40.15", "image": "ollama@sha256:test"},
                "models": [{"tier": "weak", "tag": tag, "quantization_expected": "Q4_K_M"}],
                "policy": {"paid_api_usd_ceiling": 0, "gpu_allowed": False},
            }), encoding="utf-8")
            observation_path = root / "observation.json"
            collect(Namespace(candidates=candidates, model_dir=model_dir, details_dir=details_dir,
                              output=observation_path, source_sha="abc123", run_id="101",
                              observed_at="2026-11-26T00:00:00Z", ollama_version="ollama version 0.40.15"))
            observation = json.loads(observation_path.read_text())
            self.assertEqual(observation["models"][0]["manifest_sha256"],
                             hashlib.sha256(manifest_path.read_bytes()).hexdigest())
            sealed_candidates, lock_path = root / "sealed-candidates.json", root / "lock.json"
            seal(Namespace(candidates=candidates, observation=observation_path, source_sha="abc123",
                           candidates_output=sealed_candidates, lock_output=lock_path))
            self.assertEqual(json.loads(sealed_candidates.read_text())["status"], "manifest_locked_not_qualified")
            report_path = root / "verification.json"
            verify(Namespace(candidates=sealed_candidates, lock=lock_path, model_dir=model_dir,
                             details_dir=details_dir, output=report_path, source_sha="def456",
                             run_id="102", ollama_version="ollama version 0.40.15"))
            report = json.loads(report_path.read_text())
            self.assertEqual(report["status"], "verified")
            self.assertFalse(report["inference_executed"])
            self.assertEqual(report["models"][0]["manifest_sha256"], observation["models"][0]["manifest_sha256"])

    def test_quantization_mismatch_fails_closed(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            path = model_manifest_path(root, "qwen3:1.7b")
            path.parent.mkdir(parents=True)
            path.write_text(json.dumps({"config": {"digest": "sha256:c"}, "layers": [
                {"digest": "sha256:m", "size": 10, "mediaType": "application/vnd.ollama.image.model"}
            ]}))
            with self.assertRaisesRegex(ValueError, "quantization_mismatch"):
                observed_model(root, {"tier": "weak", "tag": "qwen3:1.7b", "quantization_expected": "Q4_K_M"},
                               {"details": {"quantization_level": "Q8_0"}})


if __name__ == "__main__":
    unittest.main()
