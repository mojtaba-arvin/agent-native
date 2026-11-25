from __future__ import annotations

import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class ContainerContractTests(unittest.TestCase):
    def read(self, relative: str) -> str:
        return (ROOT / relative).read_text(encoding="utf-8")

    def test_base_image_and_build_tools_are_immutable(self):
        base = self.read("container/base-image.lock")
        self.assertRegex(base, r"(?m)^PYTHON_BASE=python:3\.11\.18-slim-bookworm@sha256:[0-9a-f]{64}$")
        self.assertIn("PLATFORM=linux/amd64", base)
        dockerfile = self.read("Dockerfile")
        self.assertIn(base.split("PYTHON_BASE=", 1)[1].splitlines()[0], dockerfile)
        lock = self.read("container/build-requirements.lock")
        self.assertRegex(lock, r"setuptools==84\.2\.1")
        self.assertRegex(lock, r"wheel==0\.48\.0")
        self.assertEqual(len(re.findall(r"--hash=sha256:[0-9a-f]{64}", lock)), 2)

    def test_image_is_minimal_non_root_and_uses_only_the_package(self):
        dockerfile = self.read("Dockerfile")
        self.assertIn("AS builder", dockerfile)
        self.assertIn("AS runtime", dockerfile)
        self.assertIn("pip wheel --no-build-isolation --no-cache-dir", dockerfile)
        self.assertIn("pip install --no-index --find-links=/tmp/wheelhouse", dockerfile)
        self.assertIn("psycopg[binary]==3.2.12", self.read("pyproject.toml"))
        self.assertIn("USER 65532:65532", dockerfile)
        self.assertIn('ENTRYPOINT ["agent-native"]', dockerfile)
        self.assertNotIn("COPY experiments", dockerfile)
        self.assertNotIn("COPY tests", dockerfile)
        self.assertNotIn("pip install -e", dockerfile)

    def test_reproducibility_script_builds_twice_and_compares_image_ids(self):
        script = self.read("container/build-reproducible.sh")
        self.assertIn('build_once "$IMAGE_A"', script)
        self.assertIn('build_once "$IMAGE_B"', script)
        self.assertIn("--no-cache", script)
        self.assertIn('IMAGE_A_ID', script)
        self.assertIn('IMAGE_B_ID', script)
        self.assertIn('SOURCE_DATE_EPOCH', script)
        self.assertIn('rewrite-timestamp=true', script)
        self.assertIn("BUILDX_VERSION", script)
        self.assertIn("SYFT_VERSION", script)
        self.assertIn("container/build-toolchain.lock", script)
        self.assertIn('syft "$IMAGE_A" -o spdx-json', script)
        self.assertIn("docker run --rm --network none --read-only", script)
        self.assertIn("docker save --output", script)

    def test_sbom_validator_requires_spdx_and_product_identity(self):
        validator = self.read("container/verify_sbom.py")
        self.assertIn('"SPDX-2.3"', validator)
        self.assertIn('"agent-native"', validator)
        self.assertIn('"packages"', validator)

    def test_build_toolchain_lock_pins_downloaded_binaries(self):
        lock = self.read("container/build-toolchain.lock")
        self.assertIn("BUILDX_VERSION=v0.39.1", lock)
        self.assertRegex(lock, r"BUILDX_SHA256=[0-9a-f]{64}")
        self.assertIn("BUILDKIT_IMAGE=moby/buildkit:v0.35.1", lock)
        self.assertIn("SYFT_VERSION=v1.57.2", lock)
        self.assertRegex(lock, r"SYFT_SHA256=[0-9a-f]{64}")

    def test_acceptance_script_installs_pinned_tools_and_runs_the_build(self):
        acceptance = self.read("acceptance/T15.sh")
        self.assertIn("BUILDX_SHA256", acceptance)
        self.assertIn("SYFT_SHA256", acceptance)
        self.assertIn("docker buildx create", acceptance)
        self.assertIn("bash container/build-reproducible.sh", acceptance)
        self.assertIn("GITHUB_STEP_SUMMARY", acceptance)

    def test_docker_context_excludes_secrets_and_research_material(self):
        ignore = self.read(".dockerignore")
        for entry in (".git", ".env", "*.pem", "*.key", "secrets", "tests", "experiments", "project-control"):
            self.assertIn(entry, ignore)


if __name__ == "__main__":
    unittest.main()
