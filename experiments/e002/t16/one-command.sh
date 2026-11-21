#!/usr/bin/env bash
set -Eeuo pipefail
REPOSITORY="mojtaba-arvin/agent-native"
BRANCH="task/T16-image-digest-pipeline"
RAW_BASE="https://raw.githubusercontent.com/$REPOSITORY/$BRANCH/experiments/e002/t16"
: "$GH_TOKEN"
command -v docker >/dev/null 2>&1 || { echo "Docker Engine/CLI is required." >&2; exit 2; }
command -v curl >/dev/null 2>&1 || { echo "curl is required." >&2; exit 2; }
docker info >/dev/null 2>&1 || { echo "Docker daemon is unavailable." >&2; exit 2; }
echo "Starting T16 one-command bootstrap..."
curl --fail --silent --show-error --location "$RAW_BASE/one-command.py" |
  docker run --rm -i --env GH_TOKEN --env T16_REPOSITORY="$REPOSITORY" --env T16_BRANCH="$BRANCH" \
    --volume /var/run/docker.sock:/var/run/docker.sock \
    --entrypoint sh docker:27.5.1-cli -ec 'apk add --no-cache python3 py3-requests >/dev/null; exec python3 -'
