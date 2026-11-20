#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT_DIR="${1:-$ROOT/dist/container}"
SOURCE_REVISION="${2:-$(git -C "$ROOT" rev-parse HEAD)}"
cd "$ROOT"

source "$ROOT/container/build-toolchain.lock"
command -v docker >/dev/null || { echo "docker is required" >&2; exit 2; }
BUILDX_INFO="$(docker buildx version)"
grep -F "$BUILDX_VERSION" <<< "$BUILDX_INFO" >/dev/null || { echo "Buildx $BUILDX_VERSION is required" >&2; exit 2; }
command -v syft >/dev/null || { echo "Syft is required; see container/README.md" >&2; exit 2; }
SYFT_INFO="$(syft version)"
grep -F "${SYFT_VERSION#v}" <<< "$SYFT_INFO" >/dev/null || { echo "Syft $SYFT_VERSION is required" >&2; exit 2; }
git cat-file -e "${SOURCE_REVISION}^{commit}"
SOURCE_DATE_EPOCH="$(git show -s --format=%ct "$SOURCE_REVISION")"
mkdir -p "$OUT_DIR"

IMAGE_A="agent-native:repro-a"
IMAGE_B="agent-native:repro-b"
BASE_IMAGE="$(sed -n 's/^PYTHON_BASE=//p' container/base-image.lock)"
[[ "$BASE_IMAGE" == *@sha256:* ]] || { echo "base image must be digest-pinned" >&2; exit 2; }

build_once() {
  local tag="$1"
  docker buildx build \
    --no-cache \
    --platform linux/amd64 \
    --output "type=docker,rewrite-timestamp=true" \
    --build-arg "PYTHON_BASE=$BASE_IMAGE" \
    --build-arg "SOURCE_DATE_EPOCH=$SOURCE_DATE_EPOCH" \
    --build-arg "SOURCE_REVISION=$SOURCE_REVISION" \
    --tag "$tag" \
    --file Dockerfile .
}

echo "Building identical source twice with SOURCE_DATE_EPOCH=$SOURCE_DATE_EPOCH"
build_once "$IMAGE_A"
build_once "$IMAGE_B"
IMAGE_A_ID="$(docker image inspect --format '{{.Id}}' "$IMAGE_A")"
IMAGE_B_ID="$(docker image inspect --format '{{.Id}}' "$IMAGE_B")"
if [[ "$IMAGE_A_ID" != "$IMAGE_B_ID" ]]; then
  echo "Non-reproducible image IDs: $IMAGE_A_ID != $IMAGE_B_ID" >&2
  exit 1
fi

docker run --rm --network none --read-only \
  --tmpfs /tmp:rw,noexec,nosuid,size=16m \
  --cap-drop ALL --security-opt no-new-privileges \
  --user 65532:65532 "$IMAGE_A" --help > "$OUT_DIR/cli-help.txt"

syft "$IMAGE_A" -o spdx-json > "$OUT_DIR/sbom.spdx.json"
python container/verify_sbom.py "$OUT_DIR/sbom.spdx.json"
docker save --output "$OUT_DIR/agent-native-image.tar" "$IMAGE_A"
(
  cd "$OUT_DIR"
  sha256sum agent-native-image.tar sbom.spdx.json cli-help.txt > SHA256SUMS
)
python - "$OUT_DIR/build-evidence.json" "$SOURCE_REVISION" "$SOURCE_DATE_EPOCH" "$IMAGE_A_ID" "$BASE_IMAGE" "$BUILDX_VERSION" "$BUILDKIT_IMAGE" "$SYFT_VERSION" <<'PY'
import json
import sys
from pathlib import Path

path, revision, epoch, image_id, base, buildx, buildkit, syft_version = sys.argv[1:]
Path(path).write_text(json.dumps({
    "schema_version": 1,
    "source_revision": revision,
    "source_date_epoch": int(epoch),
    "platform": "linux/amd64",
    "base_image": base,
    "buildx_version": buildx,
    "buildkit_image": buildkit,
    "syft_version": syft_version,
    "image_id_first_build": image_id,
    "image_id_second_build": image_id,
    "reproducible": True,
    "sbom": "sbom.spdx.json",
    "image_archive": "agent-native-image.tar",
}, sort_keys=True, indent=2) + "\n", encoding="utf-8")
PY
echo "Reproducible image verified: $IMAGE_A_ID"
echo "SBOM: $OUT_DIR/sbom.spdx.json"
