from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from measure_artifacts import (
    ArtifactMeasurementError,
    _unique_file_entries,
    elf_dependencies,
    measure_candidate,
    payload_files,
)


class ArtifactMeasurementTests(unittest.TestCase):
    def test_payload_manifest_records_size_and_sha256(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            payload = root / "server.bin"
            payload.write_bytes(b"agent-native")
            entries = _unique_file_entries([payload])
            self.assertEqual(entries[0]["bytes"], len(b"agent-native"))
            self.assertEqual(len(entries[0]["sha256"]), 64)

    def test_directory_payload_counts_nested_files(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "bin").mkdir()
            (root / "bin" / "server").write_bytes(b"1234")
            (root / "release.config").write_bytes(b"abc")
            files = payload_files(root)
            self.assertEqual(len(files), 2)
            measured = measure_candidate("fixture", "directory", [("release", root)])
            self.assertEqual(
                measured["application_and_runtime_payload_bytes"],
                7,
            )

    def test_missing_payload_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            missing = Path(temporary) / "absent"
            with self.assertRaisesRegex(ArtifactMeasurementError, "artifact_path_missing"):
                payload_files(missing)

    @unittest.skipUnless(Path("/bin/true").exists(), "Linux ELF fixture unavailable")
    def test_libraries_are_resolved_when_system_elf_is_dynamic(self):
        binary = Path("/bin/true")
        with binary.open("rb") as stream:
            self.assertEqual(stream.read(4), bytes((127,)) + b"ELF")
        dependencies = elf_dependencies(binary)
        self.assertIsInstance(dependencies, list)
        self.assertTrue(dependencies, "the Ubuntu ELF fixture should have dynamic dependencies")
        self.assertTrue(all(path.is_file() for path in dependencies))
        self.assertTrue(any(path.name.startswith("libc.so") for path in dependencies))



    def test_unique_bundle_size_does_not_count_resolved_bundled_libraries_twice(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            payload = root / "runtime"
            payload.mkdir()
            binary = payload / "program"
            binary.write_bytes(b"binary-payload")
            result = measure_candidate("fixture", "directory", [("release", payload)])
            self.assertEqual(result["application_and_runtime_payload_bytes"], len(b"binary-payload"))
            self.assertEqual(
                result["estimated_uncompressed_deployable_payload_bytes"],
                result["application_and_runtime_payload_bytes"]
                + result["external_shared_dependency_bytes"],
            )

if __name__ == "__main__":
    unittest.main()
