#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

RUST_DIR="experiments/e002/rust"
STORAGE_FILE="$RUST_DIR/src/storage.rs"
required=(
  "$RUST_DIR/Cargo.lock"
  "$STORAGE_FILE"
)
missing=()
for path in "${required[@]}"; do
  [[ -f "$path" ]] || missing+=("$path")
done
if (( ${#missing[@]} > 0 )); then
  printf 'E-002 Rust PostgreSQL adapter is not implemented; missing: %s\n' "${missing[*]}" >&2
  exit 1
fi

grep -Eq '^tokio-postgres = "=0\.7\.15"$' "$RUST_DIR/Cargo.toml" || {
  echo "Rust adapter must use pinned tokio-postgres" >&2
  exit 1
}
grep -Eq '^sha2 = "=0\.10\.9"$' "$RUST_DIR/Cargo.toml" || {
  echo "Rust adapter must pin SHA-256 implementation" >&2
  exit 1
}
grep -Eq '^uuid = \{ version = "=1\.18\.1", features = \["v4"\] \}$' "$RUST_DIR/Cargo.toml" || {
  echo "Rust adapter must pin UUID generation" >&2
  exit 1
}
grep -q 'pub mod storage;' "$RUST_DIR/src/lib.rs" || {
  echo "Rust E-002 storage module is not exported" >&2
  exit 1
}
grep -q 'name = "tokio-postgres"' "$RUST_DIR/Cargo.lock" || {
  echo "Cargo.lock does not pin tokio-postgres" >&2
  exit 1
}
if grep -n -E 'Command::new\([^\n]*psql|t16_handle|T16_' "$STORAGE_FILE"; then
  echo "E-002 Rust adapter must not shell out to psql or reuse T16-specific stored procedures" >&2
  exit 1
fi

for test_name in \
  test_append_audit_durable \
  test_atomic_job_outbox_idempotency_audit_commit \
  test_rollback_after_each_logical_write \
  test_same_key_replay_and_different_hash_conflict \
  test_concurrent_same_key_admission_is_linearizable \
  test_audit_unavailable_fails_closed \
  test_crash_after_commit_before_response_reconciles \
  test_outbox_lease_expiry_and_owner_fencing \
  test_consumer_deduplicates_local_effect \
  test_recover_committed_state; do
  grep -q "async fn $test_name" "$STORAGE_FILE" || {
    echo "required Rust storage conformance test is missing: $test_name" >&2
    exit 1
  }
done

cargo fmt --manifest-path "$RUST_DIR/Cargo.toml" -- --check
cargo test --manifest-path "$RUST_DIR/Cargo.toml" --locked
echo "T41 Rust PostgreSQL durable storage adapter acceptance passed"
