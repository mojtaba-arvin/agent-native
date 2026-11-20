from __future__ import annotations

import hashlib
import io
import json
import tarfile
import tempfile
import unittest
from pathlib import Path

from restore_evidence import restore_evidence
from run import write_evidence_bundle


class T16EvidenceRestoreTests(unittest.TestCase):
    def _create_bundle(self, root: Path) -> tuple[Path, str]:
        source_sha = "a" * 40
        output = root / "source"
        runs = output / "runs" / "go-net-http"
        runs.mkdir(parents=True)
        prereg_body = {
            "task": "T16",
            "source_sha": source_sha,
            "repetitions_per_candidate": 10,
            "requests_per_repetition": 5000,
            "concurrency": 32,
            "warmup_requests": 250,
            "target_completed_rps": 100,
            "thresholds": {"p99_ms": 100},
        }
        canonical = json.dumps(prereg_body, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
        prereg_hash = hashlib.sha256(canonical).hexdigest()
        (output / "prereg.json").write_text(json.dumps({**prereg_body, "sha256": prereg_hash}), encoding="utf-8")
        (output / "host.json").write_text(json.dumps({"physical_host_isolation": "dedicated"}), encoding="utf-8")
        (output / "protocol.json").write_text(json.dumps({"source_sha": source_sha}), encoding="utf-8")
        (output / "ledger.jsonl").write_text(json.dumps({"sha": source_sha, "prereg_hash": prereg_hash}) + "\n", encoding="utf-8")
        (output / "results.json").write_text(json.dumps({"source_sha": source_sha, "prereg_hash": prereg_hash}), encoding="utf-8")
        (output / "report.md").write_text("T16 test report", encoding="utf-8")
        (runs / "rep-01.jsonl").write_text('{"request_id":"one"}\n', encoding="utf-8")
        archive = write_evidence_bundle(output, source_sha, prereg_hash)
        return archive, source_sha

    def test_valid_bundle_is_restored_and_bound_to_pr_head(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive, source_sha = self._create_bundle(root)
            target = root / "checkout/experiments/e002/t16"
            manifest = restore_evidence(archive, target, source_sha)
            self.assertEqual(manifest["source_sha"], source_sha)
            self.assertTrue((target / "runs/go-net-http/rep-01.jsonl").is_file())

    def test_wrong_pr_head_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive, _ = self._create_bundle(root)
            with self.assertRaisesRegex(ValueError, "not_bound_to_pr_head"):
                restore_evidence(archive, root / "target", "b" * 40)

    def test_modified_asset_content_fails_sha256_verification(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive, source_sha = self._create_bundle(root)
            tampered = root / "tampered.tar.gz"
            with tarfile.open(archive, "r:gz") as original, tarfile.open(tampered, "w:gz") as output:
                for member in original.getmembers():
                    source = original.extractfile(member)
                    data = source.read() if source else b""
                    if member.name == "report.md":
                        data = b"tampered"
                    info = tarfile.TarInfo(member.name)
                    info.size = len(data)
                    output.addfile(info, io.BytesIO(data))
            with self.assertRaisesRegex(ValueError, "sha256_mismatch"):
                restore_evidence(tampered, root / "target", source_sha)

    def test_path_traversal_member_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive = root / "unsafe.tar.gz"
            with tarfile.open(archive, "w:gz") as output:
                info = tarfile.TarInfo("../outside.txt")
                info.size = 1
                output.addfile(info, io.BytesIO(b"x"))
            with self.assertRaisesRegex(ValueError, "unsafe_path"):
                restore_evidence(archive, root / "target", "a" * 40)


if __name__ == "__main__":
    unittest.main()
