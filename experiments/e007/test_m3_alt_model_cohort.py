from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from m3_alt_model_cohort import model_manifest_path, observed_model


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
