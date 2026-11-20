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
  wasi-p2-wasmtime)
    exec /opt/candidates/wasmtime serve \
      --addr=127.0.0.1:8080 -S cli=y -S http=y \
      /opt/candidates/agent_native_e002_wasi_p2.wasm
    ;;
  beam-elixir-otp)
    exec /opt/candidates/beam-release/bin/agent_native_e002_beam start
    ;;
  *)
    echo "unknown E-002 candidate: $candidate" >&2
    exit 64
    ;;
esac
