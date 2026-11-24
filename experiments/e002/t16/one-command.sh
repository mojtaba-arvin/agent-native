#!/usr/bin/env bash
set -Eeuo pipefail
# Never allow bash -x (including an invoking shell's xtrace) to expose credentials.
set +x

REPOSITORY="mojtaba-arvin/agent-native"
BRANCH="task/T16-image-digest-pipeline"
IMAGE="ghcr.io/mojtaba-arvin/agent-native-t16"
API="https://api.github.com"
RUN_STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
LOG_DIR="${T16_HOST_LOG_DIR:-/tmp/agent-native-t16-$RUN_STAMP}"
mkdir -p "$LOG_DIR"
chmod 700 "$LOG_DIR"
HOST_LOG="$LOG_DIR/launcher.log"
exec > >(tee -a "$HOST_LOG") 2>&1
log() { echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] $*"; }
fail() { code="$1"; shift; log "ERROR (exit $code): $*"; log "Host log directory: $LOG_DIR"; exit "$code"; }
log "T16 launcher started; host logs: $LOG_DIR"

# Prompt without echo when the operator has not exported a token; never put PATs in shell history.
if [[ -z "${GH_TOKEN:-}" ]]; then
  if [[ ! -r /dev/tty ]]; then
    fail 2 "GH_TOKEN is not exported. Export a classic PAT with public_repo and read:packages scopes before running this command."
  fi
  printf "GitHub classic PAT (public_repo, read:packages): " >/dev/tty
  IFS= read -r -s GH_TOKEN </dev/tty
  printf '\n' >/dev/tty
  export GH_TOKEN
fi
: "${GH_TOKEN:?GH_TOKEN must be exported in this shell (classic PAT: public_repo, read:packages).}"
log "Checking host prerequisites and exported GH_TOKEN."
command -v docker >/dev/null 2>&1 || fail 2 "Docker Engine/CLI is required."
command -v curl >/dev/null 2>&1 || fail 2 "curl is required."
docker info >/dev/null 2>&1 || fail 2 "Docker daemon is unavailable."
[[ -S /var/run/docker.sock ]] || fail 2 "A local Docker socket at /var/run/docker.sock is required."
DOCKER_ENDPOINT="$(docker context inspect "$(docker context show)" --format '{{(index .Endpoints "docker").Host}}')"
[[ "$DOCKER_ENDPOINT" == "unix:///var/run/docker.sock" ]] || {
  fail 2 "The active Docker context must target unix:///var/run/docker.sock (got: $DOCKER_ENDPOINT)."
}
[[ "$(uname -s)" == Linux && "$(uname -m)" == x86_64 ]] || fail 2 "T16 image currently supports Linux x86_64 only."
SECURITY_OPTIONS="$(docker info --format '{{json .SecurityOptions}}')"
[[ "$SECURITY_OPTIONS" != *rootless* ]] || fail 2 "A rootful Docker daemon is required."
log "Host prerequisites passed."

log "Authenticating to GitHub and GHCR; token values are never logged."
GH_USERNAME="$(curl -fsSL -H "Authorization: Bearer $GH_TOKEN" -H "Accept: application/vnd.github+json" "$API/user" | sed -n '1s/^{"login":"\([^"]*\)".*/\1/p')"
[[ -n "$GH_USERNAME" ]] || fail 2 "Could not resolve the GitHub account for GHCR authentication; verify token validity and scopes."
DOCKER_CONFIG_DIR="$(mktemp -d)"
chmod 700 "$DOCKER_CONFIG_DIR"
trap 'rm -rf "$DOCKER_CONFIG_DIR"' EXIT
export DOCKER_CONFIG="$DOCKER_CONFIG_DIR"
printf '%s' "$GH_TOKEN" | docker login ghcr.io --username "$GH_USERNAME" --password-stdin >/dev/null
log "GHCR authentication succeeded."

log "Resolving the latest T16 source revision from GitHub..."
SOURCE_SHA="$(curl -fsSL -H "Authorization: Bearer $GH_TOKEN" -H "Accept: application/vnd.github+json" \
  "$API/repos/$REPOSITORY/commits?sha=$BRANCH&per_page=1" | sed -n '1s/^\[{"sha":"\([0-9a-f]\{40\}\)".*/\1/p')"
[[ "$SOURCE_SHA" =~ ^[0-9a-f]{40}$ ]] || fail 2 "Could not resolve the current T16 source SHA."
log "Source revision: $SOURCE_SHA"

log "Refreshing the single T16 image manifest; cached layers will be reused."
docker pull "$IMAGE:t16"

IMAGE_SHA="$(docker image inspect --format '{{ index .Config.Labels "org.opencontainers.image.revision" }}' "$IMAGE:t16")"
[[ "$IMAGE_SHA" == "$SOURCE_SHA" ]] || fail 3 "Published image is not ready for branch HEAD ($SOURCE_SHA); image revision is $IMAGE_SHA."
IMAGE_REF="$(docker image inspect --format '{{range .RepoDigests}}{{println .}}{{end}}' "$IMAGE:t16" | awk -v prefix="$IMAGE@" 'index($0, prefix) == 1 { print; exit }' | tr -d '\r')"
[[ "$IMAGE_REF" =~ ^ghcr\.io/mojtaba-arvin/agent-native-t16@sha256:[0-9a-f]{64}$ ]] || { echo "Could not resolve the pulled image's immutable RepoDigest." >&2; exit 3; }

log "Image verified; launching controller from immutable digest $IMAGE_REF."
if docker run --rm --user 0:0 --privileged --pid=host --cgroupns=host --network=host \
  --volume /var/run/docker.sock:/var/run/docker.sock \
  --volume /sys/fs/cgroup:/sys/fs/cgroup \
  --volume /etc/machine-id:/host-machine-id:ro \
  --volume /tmp:/tmp \
  --volume "$LOG_DIR:/host-t16-logs:rw" \
  --volume "$DOCKER_CONFIG_DIR:/root/.docker:ro" \
  --env GH_TOKEN --env DOCKER_CONFIG=/root/.docker --env T16_SOURCE_SHA="$SOURCE_SHA" --env T16_IMAGE_REF="$IMAGE_REF" --env T16_LOG_DIR=/host-t16-logs \
  --entrypoint python3 "$IMAGE_REF" /usr/local/bin/t16-one-command-runner.py 2>&1 | tee -a "$LOG_DIR/controller.log"; then
  STATUS=0
else
  STATUS=$?
fi
log "Controller exited with status $STATUS."
log "Host logs and retained evidence: $LOG_DIR"
exit "$STATUS"
