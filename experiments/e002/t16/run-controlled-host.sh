#!/usr/bin/env bash
set -euo pipefail

REPOSITORY="mojtaba-arvin/agent-native"
ROOT="$(git rev-parse --show-toplevel)"
cd "$ROOT"

IMAGE_LOCK="${T16_IMAGE_LOCK:-experiments/e002/t16/image-lock.json}"
HOST_ATTESTATION="${T16_HOST_ATTESTATION:-}"
OUTPUT="${T16_OUTPUT:-experiments/e002/t16}"

if [[ -z "$HOST_ATTESTATION" ]]; then
  echo "T16_HOST_ATTESTATION must point to the operator's dedicated-host attestation JSON." >&2
  exit 2
fi
if [[ -z "${AGENT_NATIVE_E002_POSTGRES_DSN:-}" ]]; then
  echo "AGENT_NATIVE_E002_POSTGRES_DSN must point to the separately provisioned PostgreSQL service." >&2
  exit 2
fi
for tool in git jq gh docker psql taskset python3; do
  command -v "$tool" >/dev/null 2>&1 || {
    echo "Required controlled-host tool is missing: $tool" >&2
    exit 2
  }
done
[[ -f "$IMAGE_LOCK" ]] || { echo "Image lock not found: $IMAGE_LOCK" >&2; exit 2; }
[[ -f "$HOST_ATTESTATION" ]] || { echo "Host attestation not found: $HOST_ATTESTATION" >&2; exit 2; }

SOURCE_SHA="$(jq -er '.source_sha' "$IMAGE_LOCK")"
IMAGE_NAME="$(jq -er '.image_name' "$IMAGE_LOCK")"
IMAGE_TAG="$(jq -er '.image_tag' "$IMAGE_LOCK")"
IMAGE_DIGEST="$(jq -er '.image_digest' "$IMAGE_LOCK")"
IMAGE_REF="$(jq -er '.image_ref' "$IMAGE_LOCK")"
BUILD_RUN_URL="$(jq -er '.build_run_url' "$IMAGE_LOCK")"
SOURCE_URL="$(jq -er '.source_url' "$IMAGE_LOCK")"
DOCKERFILE_PATH="$(jq -er '.dockerfile_path' "$IMAGE_LOCK")"

[[ "$SOURCE_URL" == "https://github.com/$REPOSITORY" ]] || {
  echo "Image lock source URL does not identify $REPOSITORY." >&2
  exit 2
}
[[ "$DOCKERFILE_PATH" == "experiments/e002/t16/Dockerfile" ]] || {
  echo "Unexpected Dockerfile path in image lock: $DOCKERFILE_PATH" >&2
  exit 2
}
[[ "$IMAGE_TAG" == "$SOURCE_SHA" ]] || {
  echo "Image lock tag is not the full source SHA." >&2
  exit 2
}
[[ "$IMAGE_REF" == "$IMAGE_NAME@$IMAGE_DIGEST" ]] || {
  echo "Image lock image_ref does not match image_name and image_digest." >&2
  exit 2
}
[[ "$(git rev-parse HEAD)" == "$SOURCE_SHA" ]] || {
  echo "Checked-out source does not match image-lock source SHA $SOURCE_SHA." >&2
  exit 2
}

echo "Verifying GitHub build provenance for $IMAGE_REF"
gh attestation verify "oci://$IMAGE_REF" -R "$REPOSITORY"

RUN_COMMAND=(
  python3 experiments/e002/t16/run.py
  --output "$OUTPUT"
  --source-sha "$SOURCE_SHA"
  --image-ref "$IMAGE_REF"
  --build-run-url "$BUILD_RUN_URL"
)
printf -v PREREGISTERED_COMMAND '%q ' "${RUN_COMMAND[@]}"

python3 experiments/e002/t16/preflight.py \
  --attestation "$HOST_ATTESTATION" \
  --output "$OUTPUT" \
  --source-sha "$SOURCE_SHA" \
  --image-ref "$IMAGE_REF" \
  --image-tag "$IMAGE_TAG" \
  --build-run-url "$BUILD_RUN_URL" \
  --command "$PREREGISTERED_COMMAND"

exec "${RUN_COMMAND[@]}"
