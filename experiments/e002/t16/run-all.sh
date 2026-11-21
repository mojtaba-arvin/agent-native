#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(git rev-parse --show-toplevel 2>/dev/null)" || {
  echo "run-all.sh must be invoked from inside a Git checkout." >&2
  exit 2
}
cd "$ROOT"

T16_DIR="experiments/e002/t16"
DOCKERFILE="$T16_DIR/Dockerfile"
ATTESTATION="$T16_DIR/attestation.json"
SOURCE_SHA="$(git rev-parse HEAD)"

fail() {
  echo "T16 orchestration: $*" >&2
  exit 2
}

[[ "$SOURCE_SHA" =~ ^[0-9a-f]{40}$ ]] || fail "could not resolve a full source SHA"
[[ -f "$ATTESTATION" ]] || fail "missing truthful operator attestation: $ATTESTATION"
[[ -n "${AGENT_NATIVE_E002_POSTGRES_DSN:-}" ]] || fail "AGENT_NATIVE_E002_POSTGRES_DSN must point to the separately CPU-pinned PostgreSQL service"
command -v python3 >/dev/null || fail "python3 is required"
command -v docker >/dev/null || fail "docker is required"
command -v psql >/dev/null || fail "psql is required"
command -v sha256sum >/dev/null || fail "sha256sum is required"

git diff --quiet || fail "tracked worktree has unstaged changes"
git diff --cached --quiet || fail "index has staged changes"
git cat-file -e "$SOURCE_SHA:$DOCKERFILE" 2>/dev/null || fail "Dockerfile is not present in the checked-out source commit"

committed_hash="$(git show "$SOURCE_SHA:$DOCKERFILE" | sha256sum | awk '{print $1}')"
working_hash="$(sha256sum "$DOCKERFILE" | awk '{print $1}')"
[[ "$committed_hash" == "$working_hash" ]] || fail "working Dockerfile differs from the Dockerfile committed at $SOURCE_SHA"
grep -Fq '"docker", "build", "--file", "experiments/e002/t16/Dockerfile"' "$T16_DIR/run.py" || fail "run.py no longer builds from the exact committed Dockerfile path"

# Require immutable digests on every FROM reference. ARG-based or mutable
# aliases are deliberately not accepted by this benchmark runner.
if grep -Eiq '^[[:space:]]*FROM[[:space:]].*(latest|\$\{)|^[[:space:]]*FROM[[:space:]]+[^[:space:]]+:[^@[:space:]]+([[:space:]]|$)' "$DOCKERFILE"; then
  fail "Dockerfile FROM references must be explicit image@sha256:digest references; mutable tags/ARG indirection are rejected"
fi
from_count="$(grep -Eic '^[[:space:]]*FROM[[:space:]]+[^[:space:]]+@sha256:[0-9a-f]{64}([[:space:]]|$)' "$DOCKERFILE" || true)"
[[ "$from_count" -ge 3 ]] || fail "expected digest-pinned Go, Rust, and PostgreSQL FROM references"

# Keep generated files outside Git history. The attestation itself is ignored,
# while the preflight and runner bind every output to this exact source SHA.
python3 "$T16_DIR/preflight.py" \
  --attestation "$ATTESTATION" \
  --source-sha "$SOURCE_SHA" \
  --command "python3 $T16_DIR/run.py --source-sha $SOURCE_SHA" \
  --postgres-dsn "$AGENT_NATIVE_E002_POSTGRES_DSN"

python3 "$T16_DIR/run.py" --source-sha "$SOURCE_SHA" --postgres-dsn "$AGENT_NATIVE_E002_POSTGRES_DSN"

bash acceptance/T16.sh

archive="$T16_DIR/t16-evidence.tar.gz"
[[ -s "$archive" ]] || fail "benchmark did not produce a non-empty evidence archive"
git check-ignore -q "$ATTESTATION" || fail "attestation.json is not ignored by Git"
git check-ignore -q "$archive" || fail "t16-evidence.tar.gz is not ignored by Git"
git check-ignore -q "$T16_DIR/ledger.jsonl" || fail "ledger.jsonl is not ignored by Git"

echo "T16 complete: acceptance passed for source $SOURCE_SHA"
echo "Evidence archive (Release asset only): $archive"
