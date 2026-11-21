#!/usr/bin/env bash
set -Eeuo pipefail

REPOSITORY="mojtaba-arvin/agent-native"
BRANCH="task/T16-image-digest-pipeline"
IMAGE="ghcr.io/mojtaba-arvin/agent-native-t16"
API="https://api.github.com/repos/$REPOSITORY"

: "${GH_TOKEN:?Export GH_TOKEN with public_repo and read:packages scopes.}"
command -v docker >/dev/null 2>&1 || { echo "Docker Engine/CLI is required." >&2; exit 2; }
command -v curl >/dev/null 2>&1 || { echo "curl is required." >&2; exit 2; }
docker info >/dev/null 2>&1 || { echo "Docker daemon is unavailable." >&2; exit 2; }
[[ -S /var/run/docker.sock ]] || { echo "A local Docker socket at /var/run/docker.sock is required." >&2; exit 2; }
[[ "$(uname -s)" == Linux && "$(uname -m)" == x86_64 ]] || { echo "T16 image currently supports Linux x86_64 only." >&2; exit 2; }
SECURITY_OPTIONS="$(docker info --format '{{json .SecurityOptions}}')"
[[ "$SECURITY_OPTIONS" != *rootless* ]] || { echo "A rootful Docker daemon is required." >&2; exit 2; }

echo "Checking the latest T16 source revision..."
SOURCE_SHA="$(curl -fsSL -H "Authorization: Bearer $GH_TOKEN" -H "Accept: application/vnd.github+json" \
  "$API/commits?sha=$BRANCH&per_page=1" | grep -o '"sha":"[0-9a-f]\{40\}"' | head -n1 | cut -d '"' -f4)"
[[ "$SOURCE_SHA" =~ ^[0-9a-f]{40}$ ]] || { echo "Could not resolve the current T16 source SHA." >&2; exit 2; }

LOCAL_SHA="$(docker image inspect --format '{{ index .Config.Labels "org.opencontainers.image.revision" }}' "$IMAGE:t16" 2>/dev/null || true)"
if [[ "$LOCAL_SHA" == "$SOURCE_SHA" ]]; then
  echo "Reusing the locally cached T16 image for $SOURCE_SHA."
else
  echo "Pulling the single T16 image; unchanged layers remain cached..."
  docker pull "$IMAGE:t16"
fi

IMAGE_SHA="$(docker image inspect --format '{{ index .Config.Labels "org.opencontainers.image.revision" }}' "$IMAGE:t16")"
[[ "$IMAGE_SHA" == "$SOURCE_SHA" ]] || { echo "Published image is not ready for branch HEAD ($SOURCE_SHA); image revision is $IMAGE_SHA." >&2; exit 3; }
IMAGE_REF="$(docker image inspect --format '{{range .RepoDigests}}{{println .}}{{end}}' "$IMAGE:t16" | grep -F "$IMAGE@" | head -n1 | tr -d '\r')"
[[ "$IMAGE_REF" =~ ^ghcr\.io/mojtaba-arvin/agent-native-t16@sha256:[0-9a-f]{64}$ ]] || { echo "Could not resolve the pulled image's immutable RepoDigest." >&2; exit 3; }

echo "Launching the T16 controller from $IMAGE_REF"
docker run --rm --privileged --pid=host --cgroupns=host --network=host \
  --volume /var/run/docker.sock:/var/run/docker.sock \
  --volume /sys/fs/cgroup:/sys/fs/cgroup \
  --volume /etc/machine-id:/host-machine-id:ro \
  --volume /tmp:/tmp \
  --env GH_TOKEN --env T16_SOURCE_SHA="$SOURCE_SHA" --env T16_IMAGE_REF="$IMAGE_REF" \
  --entrypoint python3 "$IMAGE_REF" /usr/local/bin/t16-one-command-runner.py
