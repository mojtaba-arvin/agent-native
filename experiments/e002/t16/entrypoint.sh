#!/usr/bin/env sh
set -eu

candidate="${1:-}"
case "$candidate" in
  go-net-http)
    exec /opt/candidates/e002-go
    ;;
  rust-tokio-hyper)
    exec /opt/candidates/e002-rust
    ;;
  *)
    echo "unknown T16 candidate: $candidate" >&2
    exit 64
    ;;
esac
