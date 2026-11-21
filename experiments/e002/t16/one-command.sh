#!/usr/bin/env bash
set -Eeuo pipefail
REPOSITORY="mojtaba-arvin/agent-native"
BRANCH="task/T16-image-digest-pipeline"
RAW_BASE="https://raw.githubusercontent.com/$REPOSITORY/$BRANCH/experiments/e002/t16"
if [[ -z "${GH_TOKEN:-}" ]]; then
  echo "Export GH_TOKEN with a GitHub classic PAT (public_repo/repo and read:packages)." >&2
  exit 2
fi
command -v docker >/dev/null 2>&1 || { echo "Docker Engine/CLI is required." >&2; exit 2; }
command -v curl >/dev/null 2>&1 || { echo "curl is required." >&2; exit 2; }
docker info >/dev/null 2>&1 || { echo "Docker daemon is unavailable." >&2; exit 2; }
[[ -S /var/run/docker.sock ]] || { echo "T16 requires a local Docker socket at /var/run/docker.sock." >&2; exit 2; }
SECURITY_OPTIONS="$(docker info --format '{{json .SecurityOptions}}')"
if [[ "$SECURITY_OPTIONS" == *rootless* ]]; then
  echo "T16 requires a rootful Docker daemon with host PID and cgroup access." >&2
  exit 2
fi
echo "Starting T16 one-command bootstrap..."
docker run --rm --env GH_TOKEN --env T16_REPOSITORY="$REPOSITORY" --env T16_BRANCH="$BRANCH" \
  --env T16_RAW_BASE="$RAW_BASE" --volume /var/run/docker.sock:/var/run/docker.sock \
  --entrypoint sh docker:27.5.1-cli -ec '
    apk add --no-cache python3 py3-requests curl >/dev/null
    mkdir -p /tmp/t16-bootstrap
    curl --fail --silent --show-error --location "$T16_RAW_BASE/one-command.py" -o /tmp/t16-bootstrap/one-command.py
    curl --fail --silent --show-error --location "$T16_RAW_BASE/one_command_common.py" -o /tmp/t16-bootstrap/one_command_common.py
    PYTHONPATH=/tmp/t16-bootstrap exec python3 /tmp/t16-bootstrap/one-command.py
  '
