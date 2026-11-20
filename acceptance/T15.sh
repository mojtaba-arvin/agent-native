#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

python3 - <<'PY'
from pathlib import Path
import sys

required = {
    "production multi-stage Dockerfile": Path("Dockerfile"),
    "digest-pinned base image lock": Path("container/base-image.lock"),
    "hash-pinned build requirements": Path("container/build-requirements.lock"),
    "reproducible build and image verification script": Path("container/build-reproducible.sh"),
    "SPDX SBOM validator": Path("container/verify_sbom.py"),
    "container CI and publication workflow": Path(".github/workflows/container.yml"),
    "container contract tests": Path("tests/test_container_contract.py"),
    "container build documentation": Path("container/README.md"),
}
missing = [label for label, path in required.items() if not path.is_file()]
if missing:
    print("T15 acceptance: missing container/SBOM/reproducibility outputs:")
    for label in missing:
        print(f"- {label}")
    sys.exit(1)

dockerfile = required["production multi-stage Dockerfile"].read_text(encoding="utf-8")
base = required["digest-pinned base image lock"].read_text(encoding="utf-8")
lock = required["hash-pinned build requirements"].read_text(encoding="utf-8")
builder = required["reproducible build and image verification script"].read_text(encoding="utf-8")
validator = required["SPDX SBOM validator"].read_text(encoding="utf-8")
workflow = required["container CI and publication workflow"].read_text(encoding="utf-8")
tests = required["container contract tests"].read_text(encoding="utf-8")
ignore = Path(".dockerignore").read_text(encoding="utf-8")

checks = {
    "base image is pinned by immutable OCI digest": "@sha256:" in base and "PYTHON_BASE=" in base,
    "build tools are exact-version and hash pinned": "setuptools==75.8.0" in lock and "wheel==0.45.1" in lock and lock.count("--hash=sha256:") == 2,
    "multi-stage runtime image is non-root": "AS builder" in dockerfile and "AS runtime" in dockerfile and "USER 65532:65532" in dockerfile,
    "runtime image installs the wheel offline without runtime dependencies": "pip install --no-index --no-deps" in dockerfile,
    "build is repeated and complete image IDs are compared": 'build_once "$IMAGE_A"' in builder and 'build_once "$IMAGE_B"' in builder and "IMAGE_A_ID" in builder and "IMAGE_B_ID" in builder,
    "build uses source epoch and pinned platform": "SOURCE_DATE_EPOCH" in builder and "--platform linux/amd64" in builder,
    "SBOM is generated and validated as SPDX-2.3": "syft" in builder and '"SPDX-2.3"' in validator and '"agent-native"' in validator,
    "container is smoke-tested under restricted runtime settings": "--network none --read-only" in builder and "--cap-drop ALL" in builder and "--user 65532:65532" in builder,
    "CI publishes only on protected branch push": "pull_request:" in workflow and "if: github.event_name == 'push'" in workflow and "packages: write" in workflow,
    "docker context excludes credentials and non-product material": all(marker in ignore for marker in (".env", "*.pem", "*.key", "experiments", "project-control", "tests")),
    "automated container contract tests exist": "class ContainerContractTests" in tests and "test_reproducibility_script_builds_twice" in tests,
}
failed = [label for label, passed in checks.items() if not passed]
if failed:
    print("T15 acceptance: container/SBOM/reproducible-build contract is incomplete:")
    for label in failed:
        print(f"- {label}")
    sys.exit(1)

print("T15 acceptance: digest-pinned production image, hash-pinned builder, repeated image verification, SPDX SBOM, and CI publication contracts are present.")
PY

python3 -m unittest tests.test_container_contract -v
