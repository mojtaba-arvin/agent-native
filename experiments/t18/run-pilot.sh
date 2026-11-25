#!/usr/bin/env bash
set -Eeuo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"

if [[ "${1:-}" != "--acceptance" || $# -ne 1 ]]; then
  echo "usage: $0 --acceptance" >&2
  exit 2
fi
command -v docker >/dev/null || { echo "Docker Engine is required for T18" >&2; exit 2; }
docker compose version >/dev/null

export T18_POSTGRES_PASSWORD="$(python3 -c 'import secrets; print(secrets.token_hex(32))')"
export T18_TOKEN_SIGNING_KEY_HEX="$(python3 -c 'import secrets; print(secrets.token_hex(32))')"
export T18_HTTP_PORT="${T18_HTTP_PORT:-$(python3 - <<'PY'
import socket
with socket.socket() as sock:
    sock.bind(("127.0.0.1", 0))
    print(sock.getsockname()[1])
PY
)}"
export T18_COMPOSE_PROJECT="agent-native-t18-${GITHUB_RUN_ID:-local}-$$"
export T18_COMPOSE_FILE="$ROOT/experiments/t18/compose.yaml"
export T18_BASE_URL="http://127.0.0.1:$T18_HTTP_PORT"
export T18_TOKEN_SIGNING_KEY_HEX
export PYTHONPATH="$ROOT/src${PYTHONPATH:+:$PYTHONPATH}"

EVIDENCE_DIR="${T18_EVIDENCE_DIR:-$(mktemp -d "${RUNNER_TEMP:-/tmp}/agent-native-t18.XXXXXX")}"
mkdir -p "$EVIDENCE_DIR"
chmod 700 "$EVIDENCE_DIR"
export T18_EVIDENCE_DIR="$EVIDENCE_DIR"
STARTED_AT="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
COMPOSE=(docker compose --project-name "$T18_COMPOSE_PROJECT" --file "$T18_COMPOSE_FILE")

cleanup() {
  status=$?
  trap - EXIT
  if [[ $status -ne 0 ]]; then
    "${COMPOSE[@]}" logs --no-color app > "$EVIDENCE_DIR/app.log" 2>&1 || true
    T15_EVIDENCE_DIR="${RUNNER_TEMP:-/tmp}/t15-container-output"
    if [[ -d "$T15_EVIDENCE_DIR" ]]; then
      mkdir -p "$EVIDENCE_DIR/t15" || true
      for file in build-evidence.json sbom.spdx.json cli-help.txt; do
        [[ ! -f "$T15_EVIDENCE_DIR/$file" ]] || \
          cp "$T15_EVIDENCE_DIR/$file" "$EVIDENCE_DIR/t15/" || true
      done
    fi
    SOURCE_SHA="$(git rev-parse HEAD 2>/dev/null || echo unknown)"
    python3 - "$EVIDENCE_DIR/acceptance.json" "$status" "$SOURCE_SHA" <<'PY' || true
import json, sys
from pathlib import Path
Path(sys.argv[1]).write_text(json.dumps({
    "schema_version": 1, "task": "T18", "status": "failed",
    "exit_code": int(sys.argv[2]), "source_sha": sys.argv[3]
}, sort_keys=True, indent=2) + "\n", encoding="utf-8")
PY
  fi
  "${COMPOSE[@]}" down --volumes --remove-orphans >/dev/null 2>&1 || true
  exit "$status"
}
trap cleanup EXIT

echo "Building and verifying the canonical reproducible T15 production image."
export RUNNER_TEMP="${RUNNER_TEMP:-$(mktemp -d)}"
bash acceptance/T15.sh
docker tag agent-native:repro-a agent-native:t15
T15_EVIDENCE_DIR="$RUNNER_TEMP/t15-container-output"
mkdir -p "$EVIDENCE_DIR/t15"
cp "$T15_EVIDENCE_DIR/build-evidence.json" "$T15_EVIDENCE_DIR/sbom.spdx.json" \
  "$T15_EVIDENCE_DIR/cli-help.txt" "$EVIDENCE_DIR/t15/"
IMAGE_ID="$(docker image inspect --format '{{.Id}}' agent-native:t15)"
SOURCE_SHA="$(git rev-parse HEAD)"
IMAGE_REVISION="$(docker image inspect --format '{{ index .Config.Labels "org.opencontainers.image.revision" }}' agent-native:t15)"
if [[ "$IMAGE_REVISION" != "$SOURCE_SHA" ]]; then
  echo "T15 image revision mismatch: $IMAGE_REVISION != $SOURCE_SHA" >&2
  exit 1
fi
POSTGRES_IMAGE="postgres:16.4@sha256:e62fbf9d3e2b49816a32c400ed2dba83e3b361e6833e624024309c35d334b412"

python3 - "$EVIDENCE_DIR/deployment.json" "$SOURCE_SHA" "$IMAGE_ID" "$POSTGRES_IMAGE" "$T18_HTTP_PORT" "$STARTED_AT" <<'PY'
import json, sys
from pathlib import Path
path, source_sha, image_id, postgres_image, port, started_at = sys.argv[1:]
Path(path).write_text(json.dumps({
    "schema_version": 1,
    "task": "T18",
    "source_sha": source_sha,
    "image_revision": source_sha,
    "application_image": "agent-native:t15",
    "application_image_id": image_id,
    "postgres_image": postgres_image,
    "host_binding": "127.0.0.1",
    "host_port": int(port),
    "database_host_port_published": False,
    "application_uid": 65532,
    "postgres_health_gated_startup": True,
    "services_mount_read_only": True,
    "secrets_recorded": False,
    "started_at": started_at
}, sort_keys=True, indent=2) + "\n", encoding="utf-8")
PY

"${COMPOSE[@]}" up -d --wait
"${COMPOSE[@]}" ps --format json > "$EVIDENCE_DIR/compose-ps.json"
python3 -m unittest discover -s experiments/t18 -p 'test_pilot.py' -v 2>&1 | tee "$EVIDENCE_DIR/acceptance.log"
"${COMPOSE[@]}" logs --no-color app > "$EVIDENCE_DIR/app.log" 2>&1

FINISHED_AT="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
python3 - "$EVIDENCE_DIR/acceptance.json" "$SOURCE_SHA" "$IMAGE_ID" "$POSTGRES_IMAGE" "$STARTED_AT" "$FINISHED_AT" <<'PY'
import json, sys
from pathlib import Path
path, source_sha, image_id, postgres_image, started_at, finished_at = sys.argv[1:]
Path(path).write_text(json.dumps({
    "schema_version": 1,
    "task": "T18",
    "status": "passed",
    "source_sha": source_sha,
    "application_image_id": image_id,
    "postgres_image": postgres_image,
    "suite": "experiments/t18/test_pilot.py",
    "started_at": started_at,
    "finished_at": finished_at
}, sort_keys=True, indent=2) + "\n", encoding="utf-8")
PY
cat > "$EVIDENCE_DIR/findings.md" <<'EOF'
# T18 operational findings

- The T15 image loaded the Catalog and Inventory service manifests; black-box CRUD and persistence checks exercised Catalog through the bounded operational HTTP ingress.
- PostgreSQL readiness gated application startup; application data, idempotency, audit, and outbox state were checked through the live service.
- The application ran as UID 65532 with a read-only root filesystem, dropped capabilities, and a read-only service-manifest mount.
- The PostgreSQL service was reachable only on the Compose network; only the application port was published to host loopback.
- This is a disposable single-node pilot. It does not establish HA, backup/restore, failover, production secret management, or a production capacity envelope.
EOF
if [[ -n "${GITHUB_STEP_SUMMARY:-}" ]]; then
  {
    echo "## T18 PostgreSQL container pilot"
    echo
    echo "- Source: `$SOURCE_SHA`"
    echo "- Application image ID: `$IMAGE_ID`"
    echo "- PostgreSQL image: `$POSTGRES_IMAGE`"
    echo "- Evidence directory: `$EVIDENCE_DIR`"
  } >> "$GITHUB_STEP_SUMMARY"
fi
echo "T18 pilot passed; sanitized evidence written to $EVIDENCE_DIR"
