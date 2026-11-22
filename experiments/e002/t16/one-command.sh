#!/usr/bin/env bash
set -Eeuo pipefail
# Never allow bash -x (including an invoking shell's xtrace) to expose credentials.
set +x

REPOSITORY="mojtaba-arvin/agent-native"
BRANCH="task/T16-image-digest-pipeline"
IMAGE="ghcr.io/mojtaba-arvin/agent-native-t16"
API="https://api.github.com"

: "${GH_TOKEN:?Export GH_TOKEN with public_repo and read:packages scopes.}"
command -v docker >/dev/null 2>&1 || { echo "Docker Engine/CLI is required." >&2; exit 2; }
command -v curl >/dev/null 2>&1 || { echo "curl is required." >&2; exit 2; }
docker info >/dev/null 2>&1 || { echo "Docker daemon is unavailable." >&2; exit 2; }
[[ -S /var/run/docker.sock ]] || { echo "A local Docker socket at /var/run/docker.sock is required." >&2; exit 2; }
DOCKER_ENDPOINT="$(docker context inspect "$(docker context show)" --format '{{(index .Endpoints "docker").Host}}')"
[[ "$DOCKER_ENDPOINT" == "unix:///var/run/docker.sock" ]] || {
  echo "The active Docker context must target unix:///var/run/docker.sock (got: $DOCKER_ENDPOINT)." >&2
  exit 2
}
[[ "$(uname -s)" == Linux && "$(uname -m)" == x86_64 ]] || { echo "T16 image currently supports Linux x86_64 only." >&2; exit 2; }
SECURITY_OPTIONS="$(docker info --format '{{json .SecurityOptions}}')"
[[ "$SECURITY_OPTIONS" != *rootless* ]] || { echo "A rootful Docker daemon is required." >&2; exit 2; }

GH_USERNAME="$(curl -fsSL -H "Authorization: Bearer $GH_TOKEN" -H "Accept: application/vnd.github+json" "$API/user" | sed -n '1s/^{"login":"\([^"]*\)".*/\1/p')"
[[ -n "$GH_USERNAME" ]] || { echo "Could not resolve the GitHub account for GHCR authentication." >&2; exit 2; }
DOCKER_CONFIG_DIR="$(mktemp -d)"
chmod 700 "$DOCKER_CONFIG_DIR"
trap 'rm -rf "$DOCKER_CONFIG_DIR"' EXIT
export DOCKER_CONFIG="$DOCKER_CONFIG_DIR"
printf '%s' "$GH_TOKEN" | docker login ghcr.io --username "$GH_USERNAME" --password-stdin >/dev/null

echo "Checking the latest T16 source revision..."
SOURCE_SHA="$(curl -fsSL -H "Authorization: Bearer $GH_TOKEN" -H "Accept: application/vnd.github+json" \
  "$API/repos/$REPOSITORY/commits?sha=$BRANCH&per_page=1" | sed -n '1s/^\[{"sha":"\([0-9a-f]\{40\}\)".*/\1/p')"
[[ "$SOURCE_SHA" =~ ^[0-9a-f]{40}$ ]] || { echo "Could not resolve the current T16 source SHA." >&2; exit 2; }

echo "Refreshing the T16 image manifest; already-cached layers will not be downloaded again..."
docker pull "$IMAGE:t16"

IMAGE_SHA="$(docker image inspect --format '{{ index .Config.Labels "org.opencontainers.image.revision" }}' "$IMAGE:t16")"
[[ "$IMAGE_SHA" == "$SOURCE_SHA" ]] || { echo "Published image is not ready for branch HEAD ($SOURCE_SHA); image revision is $IMAGE_SHA." >&2; exit 3; }
IMAGE_REF="$(docker image inspect --format '{{range .RepoDigests}}{{println .}}{{end}}' "$IMAGE:t16" | awk -v prefix="$IMAGE@" 'index($0, prefix) == 1 { print; exit }' | tr -d '\r')"
[[ "$IMAGE_REF" =~ ^ghcr\.io/mojtaba-arvin/agent-native-t16@sha256:[0-9a-f]{64}$ ]] || { echo "Could not resolve the pulled image's immutable RepoDigest." >&2; exit 3; }

echo "Launching the T16 controller from $IMAGE_REF"
docker run --rm --user 0:0 --privileged --pid=host --cgroupns=host --network=host \
  --volume /var/run/docker.sock:/var/run/docker.sock \
  --volume /sys/fs/cgroup:/sys/fs/cgroup \
  --volume /etc/machine-id:/host-machine-id:ro \
  --volume /tmp:/tmp \
  --volume "$DOCKER_CONFIG_DIR:/root/.docker:ro" \
  --env GH_TOKEN --env DOCKER_CONFIG=/root/.docker --env T16_SOURCE_SHA="$SOURCE_SHA" --env T16_IMAGE_REF="$IMAGE_REF" \
  --entrypoint python3 "$IMAGE_REF" /usr/local/bin/t16-one-command-runner.py
