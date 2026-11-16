# E-002 runtime substrate experiment — first native arms

This is the first executable transport/runtime slice for E-002. It compares two low-level native HTTP implementations without using an existing backend framework:

- Go standard library `net/http`;
- Rust `tokio` + `hyper` directly.

Neither language is selected for Agent Native. These are disposable baseline implementations. They are not Agent Native's product runtime and do not define its final service model.

## Workload contract v0

- `GET /health`: readiness response.
- `GET /work?ms=N`: bounded concurrent work; reject overload with 503; return 504 when the fixed 750 ms operation deadline expires.
- `GET /stream`: return three ordered body frames.
- The service admits at most 64 concurrent work operations.
- Server binds to `127.0.0.1:8080`.

The first pass checks semantic parity and buildability. It is **not** a performance benchmark. A later stage must add an independent load generator, warm-up, repetitions, latency percentiles, throughput, CPU/RSS, startup, and failure injection. Cancellation and client-disconnect semantics are not yet considered equivalent.

## Build and run

Go:

```sh
cd experiments/e002/go
go test ./...
go run .
```

Rust:

```sh
cd experiments/e002/rust
cargo test --locked
cargo run --release
```

## Fairness controls still required

- Pin compiler/runtime versions and dependency lockfiles.
- Use the same host, kernel, CPU limits, memory limits, and container constraints.
- Confirm identical response/status semantics before load testing.
- Run randomized candidate order with warm-up and repeated trials.
- Retain raw request-level measurements and process resource samples.
- Report both throughput and tail latency; do not collapse them into one score.

WASI Component Model and BEAM arms remain open. No runtime selection is made from this partial native comparison.


## Reproducible native benchmark runner

`benchmark.py` starts one candidate binary, waits for readiness, performs warm-up requests, then sends a fixed number of concurrent `/work?ms=0` requests. It writes request-level JSONL and a summary JSON containing latency percentiles, throughput, status counts, process CPU time, and peak RSS (Linux `/proc` sampling).

Example from the repository root:

```sh
python experiments/e002/benchmark.py \
  --command /tmp/e002-go \
  --cwd experiments/e002/go \
  --requests 5000 --concurrency 64 --warmup 250 \
  --label go-net-http --output results/e002/go
```

Repeat with the Rust binary and randomized candidate order. Keep machine and runner identical. The script is an initial measurement harness, not yet a complete benchmark protocol: it does not isolate background noise, pin CPU frequency, measure startup distributions, or capture host/guest memory separately. Do not treat one run as a performance conclusion.
