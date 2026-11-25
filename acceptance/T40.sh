#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

GO_DIR="experiments/e002/go"
STORAGE_DIR="$GO_DIR/storage"
required=(
  "$STORAGE_DIR/adapter.go"
  "$STORAGE_DIR/postgres.go"
  "$STORAGE_DIR/postgres_test.go"
  "$STORAGE_DIR/conformance_test.go"
  "$STORAGE_DIR/fault_injection_test.go"
  "$GO_DIR/go.sum"
)
missing=()
for path in "${required[@]}"; do
  [[ -f "$path" ]] || missing+=("$path")
done
if (( ${#missing[@]} > 0 )); then
  printf 'E-002 Go PostgreSQL adapter is not implemented; missing: %s\n' "${missing[*]}" >&2
  exit 1
fi

grep -Eq 'github\.com/jackc/pgx/v5 v[0-9]' "$GO_DIR/go.mod" || {
  echo "Go adapter must use a pinned pgx/v5 driver" >&2
  exit 1
}
grep -Eq '^type Adapter interface' "$STORAGE_DIR/adapter.go" || {
  echo "shared durable storage Adapter interface is missing" >&2
  exit 1
}
if grep -R -n -E 'exec\.Command\([^\n]*psql|t16_handle|T16_' "$STORAGE_DIR"; then
  echo "E-002 adapter must not shell out to psql or reuse T16-specific stored procedures" >&2
  exit 1
fi

for test_name in \
  TestAppendAuditDurable \
  TestAtomicJobOutboxIdempotencyAuditCommit \
  TestRollbackAfterEachLogicalWrite \
  TestSameKeyReplayAndDifferentHashConflict \
  TestConcurrentSameKeyAdmissionIsLinearizable \
  TestAuditUnavailableFailsClosed \
  TestCrashAfterCommitBeforeResponseReconciles \
  TestOutboxLeaseExpiryAndOwnerFencing \
  TestConsumerDeduplicatesLocalEffect \
  TestRecoverCommittedState; do
  grep -R -q "func $test_name" "$STORAGE_DIR" || {
    echo "required Go storage conformance test is missing: $test_name" >&2
    exit 1
  }
done

(
  cd "$GO_DIR"
  go test ./...
  go vet ./...
)
echo "T40 Go PostgreSQL durable storage adapter acceptance passed"
