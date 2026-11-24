from __future__ import annotations

import hashlib
import json
import tarfile
import tempfile
import unittest
from pathlib import Path

from restore_evidence import restore_evidence


SOURCE_SHA = "a" * 40
IMAGE_REF = "ghcr.io/mojtaba-arvin/agent-native-t16@sha256:" + "b" * 64
RUN_ID = "20261124T053000Z-1234abcd"


def _write_bundle(root: Path) -> None:
    body = {
        "task": "T16",
        "source_sha": SOURCE_SHA,
        "repetitions_per_candidate": 10,
        "requests_per_repetition": 5000,
        "concurrency": 32,
        "warmup_requests": 250,
        "target_completed_rps": 100,
        "thresholds": {"p99_ms": 100},
    }
    canonical = json.dumps(body, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    prereg_hash = hashlib.sha256(canonical).hexdigest()
    files = {
        "prereg.json": {**body, "sha256": prereg_hash},
        "host.json": {"physical_host_isolation": "dedicated"},
        "protocol.json": {"source_sha": SOURCE_SHA},
        "ledger.jsonl": "{}\n",
        "results.json": {"source_sha": SOURCE_SHA, "prereg_hash": prereg_hash, "image_ref": IMAGE_REF},
        "report.md": "T16 controlled-host report",
        "execution.log": "controller started\n",
        "preflight.log": "preflight passed\n",
        "image-lock.json": {"source_sha": SOURCE_SHA, "image_ref": IMAGE_REF},
        "execution-metadata.json": {"source_sha": SOURCE_SHA, "run_id": RUN_ID},
        "checksums.sha256": "checksum manifest\n",
    }
    for name, value in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(value if isinstance(value, str) else json.dumps(value), encoding="utf-8")
    trace = root / "runs/go-net-http/rep-01.jsonl"
    trace.parent.mkdir(parents=True, exist_ok=True)
    trace.write_text('{"request_id":"one"}\n', encoding="utf-8")
    summary = root / "runs/go-net-http/rep-01.json"
    summary.write_text('{"completed_requests":5000}\n', encoding="utf-8")

    manifest_files = {
        str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(root.rglob("*")) if path.is_file()
    }
    manifest = {
        "schema_version": 1,
        "task": "T16",
        "run_id": RUN_ID,
        "source_sha": SOURCE_SHA,
        "image_ref": IMAGE_REF,
        "build_run_id": 123,
        "build_run_url": "https://github.com/mojtaba-arvin/agent-native/actions/runs/123",
        "prereg_hash": prereg_hash,
        "files": manifest_files,
    }
    (root / "evidence-manifest.json").write_text(
        json.dumps(manifest, sort_keys=True), encoding="utf-8"
    )


def _archive(root: Path, path: Path) -> None:
    with tarfile.open(path, "w:gz") as archive:
        archive.add(root, arcname="T16/" + RUN_ID)


class T16EvidenceRestoreTests(unittest.TestCase):
    def test_restores_nested_run_archive_and_verifies_source_binding(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            source = base / "source"
            source.mkdir()
            _write_bundle(source)
            archive = base / "evidence.tar.gz"
            _archive(source, archive)
            target = base / "restored"
            manifest = restore_evidence(archive, target, SOURCE_SHA)
            self.assertEqual(manifest["run_id"], RUN_ID)
            self.assertEqual((target / "prereg.json").is_file(), True)
            self.assertTrue((target / "runs/go-net-http/rep-01.jsonl").is_file())

    def test_rejects_evidence_bound_to_another_source_sha(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            source = base / "source"
            source.mkdir()
            _write_bundle(source)
            archive = base / "evidence.tar.gz"
            _archive(source, archive)
            with self.assertRaisesRegex(ValueError, "manifest_binding_mismatch"):
                restore_evidence(archive, base / "restored", "c" * 40)

    def test_rejects_archive_path_traversal(self):
        with tempfile.TemporaryDirectory() as directory:
            archive = Path(directory) / "evil.tar.gz"
            with tarfile.open(archive, "w:gz") as tar:
                info = tarfile.TarInfo("T16/" + RUN_ID + "/../../evil")
                data = b"owned"
                info.size = len(data)
                import io
                tar.addfile(info, io.BytesIO(data))
            with self.assertRaisesRegex(ValueError, "unsafe_path"):
                restore_evidence(archive, Path(directory) / "restored", SOURCE_SHA)

    def test_rejects_tampered_evidence_file(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            source = base / "source"
            source.mkdir()
            _write_bundle(source)
            (source / "report.md").write_text("tampered", encoding="utf-8")
            archive = base / "evidence.tar.gz"
            _archive(source, archive)
            with self.assertRaisesRegex(ValueError, "sha256_mismatch"):
                restore_evidence(archive, base / "restored", SOURCE_SHA)


if __name__ == "__main__":
    unittest.main()
