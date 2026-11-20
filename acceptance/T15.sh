#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

python3 - <<'PY'
from pathlib import Path
import sys

required = {
    "production multi-stage Dockerfile": Path("Dockerfile"),
    "digest-pinned base image lock": Path("container/base-image.lock"),
    "pinned container toolchain lock": Path("container/build-toolchain.lock"),
    "hash-pinned build requirements": Path("container/build-requirements.lock"),
    "reproducible build and image verification script": Path("container/build-reproducible.sh"),
    "SPDX SBOM validator": Path("container/verify_sbom.py"),
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
toolchain = required["pinned container toolchain lock"].read_text(encoding="utf-8")
lock = required["hash-pinned build requirements"].read_text(encoding="utf-8")
builder = required["reproducible build and image verification script"].read_text(encoding="utf-8")
validator = required["SPDX SBOM validator"].read_text(encoding="utf-8")
tests = required["container contract tests"].read_text(encoding="utf-8")
ignore = Path(".dockerignore").read_text(encoding="utf-8")

checks = {
    "base image is pinned by immutable OCI digest": "@sha256:" in base and "PYTHON_BASE=" in base,
    "build toolchain versions and binary hashes are pinned": "BUILDX_VERSION=" in toolchain and "BUILDX_SHA256=" in toolchain and "BUILDKIT_IMAGE=" in toolchain and "SYFT_VERSION=" in toolchain and "SYFT_SHA256=" in toolchain,
    "build tools are exact-version and hash pinned": "setuptools==84.2.1" in lock and "wheel==0.48.0" in lock and lock.count("--hash=sha256:") == 2,
    "multi-stage runtime image is non-root": "AS builder" in dockerfile and "AS runtime" in dockerfile and "USER 65532:65532" in dockerfile,
    "runtime image installs the wheel offline without runtime dependencies": "pip install --no-index --no-deps" in dockerfile,
    "two independent uncached builds compare complete image IDs": 'build_once "$IMAGE_A"' in builder and 'build_once "$IMAGE_B"' in builder and "--no-cache" in builder and "IMAGE_A_ID" in builder and "IMAGE_B_ID" in builder,
    "build uses source epoch and normalized file timestamps": "SOURCE_DATE_EPOCH" in builder and "rewrite-timestamp=true" in builder,
    "SBOM is generated and validated as SPDX-2.3": "syft" in builder and '"SPDX-2.3"' in validator and '"agent-native"' in validator,
    "container is smoke-tested under restricted runtime settings": "--network none --read-only" in builder and "--cap-drop ALL" in builder and "--user 65532:65532" in builder,
    "docker context excludes credentials and non-product material": all(marker in ignore for marker in (".env", "*.pem", "*.key", "experiments", "project-control", "tests")),
    "automated container contract tests exist": "class ContainerContractTests" in tests and "test_reproducibility_script_builds_twice" in tests,
}
failed = [label for label, passed in checks.items() if not passed]
if failed:
    print("T15 acceptance: container/SBOM/reproducible-build contract is incomplete:")
    for label in failed:
        print(f"- {label}")
    sys.exit(1)

print("T15 acceptance: digest-pinned image, hash-pinned toolchain, independent reproducibility builds, and SPDX SBOM contracts are present.")
PY

bash -n container/build-reproducible.sh
python3 -m py_compile container/verify_sbom.py tests/test_container_contract.py
python3 -m unittest tests.test_container_contract -v

source container/build-toolchain.lock
command -v docker >/dev/null || { echo "Docker Engine is required for T15 acceptance" >&2; exit 2; }
RUNNER_TEMP="${RUNNER_TEMP:-$(mktemp -d)}"
mkdir -p "$RUNNER_TEMP/bin" "$HOME/.docker/cli-plugins"

buildx_archive="$RUNNER_TEMP/buildx-${BUILDX_VERSION}.linux-amd64"
curl --fail --silent --show-error --location \
  "https://github.com/docker/buildx/releases/download/${BUILDX_VERSION}/buildx-${BUILDX_VERSION}.linux-amd64" \
  -o "$buildx_archive"
printf '%s  %s\n' "$BUILDX_SHA256" "$buildx_archive" | sha256sum --check --status
install -m 0755 "$buildx_archive" "$HOME/.docker/cli-plugins/docker-buildx"
docker buildx version | grep -F "$BUILDX_VERSION"

syft_version="${SYFT_VERSION#v}"
syft_archive="$RUNNER_TEMP/syft_${syft_version}_linux_amd64.tar.gz"
curl --fail --silent --show-error --location \
  "https://github.com/anchore/syft/releases/download/${SYFT_VERSION}/syft_${syft_version}_linux_amd64.tar.gz" \
  -o "$syft_archive"
printf '%s  %s\n' "$SYFT_SHA256" "$syft_archive" | sha256sum --check --status
tar -xzf "$syft_archive" -C "$RUNNER_TEMP" syft
install -m 0755 "$RUNNER_TEMP/syft" "$RUNNER_TEMP/bin/syft"
export PATH="$RUNNER_TEMP/bin:$PATH"
syft version | grep -F "$SYFT_VERSION"

builder_name="agent-native-t15-${GITHUB_RUN_ID:-local}"
docker buildx create --name "$builder_name" --driver docker-container --driver-opt "image=$BUILDKIT_IMAGE" --use
cleanup() {
  docker buildx rm "$builder_name" >/dev/null 2>&1 || true
}
trap cleanup EXIT

out_dir="$RUNNER_TEMP/t15-container-output"
source_revision="$(git rev-parse HEAD)"
bash container/build-reproducible.sh "$out_dir" "$source_revision"
(cd "$out_dir" && sha256sum --check SHA256SUMS)

python3 - "$out_dir" "${GITHUB_STEP_SUMMARY:-}" <<'PY'
import hashlib
import json
import sys
from pathlib import Path

out = Path(sys.argv[1])
summary_path = sys.argv[2]
evidence = json.loads((out / "build-evidence.json").read_text(encoding="utf-8"))
sbom = json.loads((out / "sbom.spdx.json").read_text(encoding="utf-8"))
image_sha = hashlib.sha256((out / "agent-native-image.tar").read_bytes()).hexdigest()
sbom_sha = hashlib.sha256((out / "sbom.spdx.json").read_bytes()).hexdigest()
lines = [
    "## T15 reproducible container acceptance",
    "",
    f"- Source revision: `{evidence['source_revision']}`",
    f"- Image ID: `{evidence['image_id_first_build']}`",
    f"- Independent builds matched: `{evidence['reproducible']}`",
    f"- SPDX version: `{sbom['spdxVersion']}`",
    f"- SBOM package count: `{len(sbom['packages'])}`",
    f"- Image archive SHA-256: `{image_sha}`",
    f"- SBOM SHA-256: `{sbom_sha}`",
]
print("\n".join(lines))
if summary_path:
    with Path(summary_path).open("a", encoding="utf-8") as handle:
        handle.write("\n".join(lines) + "\n")
PY
