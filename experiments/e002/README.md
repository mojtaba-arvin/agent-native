# E-002 runtime substrate experiment — first native arms

This is the first executable transport/runtime slice for E-002. It compares four independent execution substrates without using an existing backend framework:

- Go standard library `net/http`;
- Rust `tokio` + `hyper` directly;
- WASI Preview 2 component using `wstd` and Wasmtime 50.0.1;
- Elixir/OTP on BEAM using raw `:gen_tcp` and processes.

Neither language is selected for Agent Native. These are disposable baseline implementations. They are not Agent Native's product runtime and do not define its final service model.

## Workload contract v0

- `GET /health`: readiness response.
- `GET /work?ms=N`: bounded concurrent work; the raw query must be exactly `ms=` followed by ASCII decimal digits (no extra/duplicate parameters, percent encoding, or sign); reject overload with 503; return 504 when the fixed 750 ms operation deadline expires.
- `GET /stream`: return three ordered body frames.
- Go, Rust, and BEAM candidates enforce an application-level limit of 64 active connections/work handlers. WASI P2 uses a host-owned listener; its admission limit is host policy and is not equivalent to a guest-owned limit.
- Server binds to `127.0.0.1:8080`.

The first pass checks semantic parity and buildability. The black-box suite now checks malformed, reordered, duplicate, encoded, signed, and empty query forms to prevent parser differences across candidates. It is **not** a performance benchmark. A later stage must add an independent load generator, warm-up, repetitions, latency percentiles, throughput, CPU/RSS, startup, and failure injection. Cancellation and client-disconnect semantics are not yet considered equivalent.

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

`benchmark.py` starts one candidate binary, waits for readiness, performs warm-up requests, then sends a fixed number of concurrent `/work?ms=0` requests. It writes request-level JSONL and a summary JSON containing latency percentiles, throughput, status counts, process CPU time, and peak RSS (Linux `/proc` sampling). A run is marked functionally unsuccessful and exits non-zero if any measured response is not exactly HTTP 200 with `completed:0`, if a transport error occurs, or if the candidate exits during load. The matrix runner therefore cannot silently compare broken candidates as fast results.

Example from the repository root:

```sh
python experiments/e002/benchmark.py \
  --command /tmp/e002-go \
  --cwd experiments/e002/go \
  --requests 5000 --concurrency 64 --warmup 250 \
  --label go-net-http --output results/e002/go
```

Repeat with the Rust binary and randomized candidate order. Keep machine and runner identical. The script is an initial measurement harness, not yet a complete benchmark protocol: it does not isolate background noise, pin CPU frequency, measure startup distributions, or capture host/guest memory separately. Do not treat one run as a performance conclusion.


## BEAM/OTP arm\n\nA raw Elixir/OTP server uses the BEAM process model and `:atomics` for a bounded in-flight connection count. It deliberately avoids Phoenix, Plug, Bandit, and other web frameworks. The implementation is a transport/runtime probe, not a production HTTP server; it closes each connection after one request and does not yet implement graceful draining or cancellation propagation on client disconnect.\n\n## WASI Component Model arm

A WASI Preview 2 HTTP component is now included at `wasi-p2/`, using `wstd` 0.6.8 and the standard `wasi:http/proxy` world. It implements the same health, bounded-duration work response, deadline status, and streaming body contract. The component build and shared black-box conformance suite pass on Wasmtime 50.0.1. The first host run exposed a missing `wasi:cli/environment` import; explicitly enabling the CLI and HTTP WASI interfaces resolved it.

Important comparison boundary: `wasmtime serve` is a development/test host, not a production server. It owns the socket and HTTP admission path; the guest component does not own the listener. Guest-global concurrency state cannot be assumed to persist across requests, so concurrency limits and isolation overhead must be measured at the host boundary. The WASI arm is not semantically equivalent for every E-002 dimension yet.

WASI Preview 3 is a separate candidate, not silently substituted for Preview 2. Rust 1.100 now provides the `wasm32-wasip3` target, but the current `wasip3` bindings are still documented as a snapshot and Wasmtime's P3 HTTP host implementation is described as experimental/incomplete. Build/runtime compatibility must be established before treating it as a benchmark arm.


For the full four-candidate randomized matrix (after building `/tmp/e002-go` and the Rust release binary):

```sh
python experiments/e002/run_matrix.py \
  --go-command /tmp/e002-go \
  --rust-command ./target/release/agent-native-e002-rust \
  --wasi-command "wasmtime serve --addr=127.0.0.1:8080 -S cli=y -S http=y target/wasm32-wasip2/release/agent_native_e002_wasi_p2.wasm" \
  --beam-command "mix run -e AgentNativeE002Beam.Server.main()" \
  --requests 5000 --concurrency 64 --warmup 250 --repetitions 10 \
  --output results/e002
```

The matrix runner shuffles candidate order with a recorded seed, retains every run's raw JSONL and summary JSON, and reports descriptive medians only. It deliberately does not declare a winner or compute inferential statistics.


## BEAM/OTP arm

The Elixir/OTP implementation uses raw `:gen_tcp`, one BEAM process per accepted connection, and an atomic in-flight counter for the 64-connection cap. It intentionally avoids Phoenix, Plug, Bandit, or another HTTP framework. It is a runtime probe rather than a production HTTP server: it handles one request per connection and does not yet implement graceful draining or cancellation propagation when the client disconnects.

The matrix runner samples the benchmark process **and its descendants** so the BEAM VM spawned by `mix` is included in CPU/RSS measurements. The benchmark is still descriptive: process-tree RSS is summed and sampled, not a complete memory-isolation or per-tenant accounting model.


An initial 3-repetition, 1,000-request-per-candidate matrix is available as a CI smoke-data artifact when the benchmark workflow is explicitly triggered. GitHub-hosted runner results are noisy and are not suitable for selecting a runtime; use them only to validate the measurement pipeline. Decision-grade measurements require a controlled, dedicated machine and a larger repeated-run protocol.


## Pinned toolchains and dependencies

- Go: 1.23.12.
- Rust/Cargo: 1.100.0, pinned in root `rust-toolchain.toml`; Rust crates use committed lockfiles and CI `--locked` builds.
- WASI P2 guest: `wstd` 0.6.8 and locked transitive dependencies.
- Wasmtime host: 50.0.1.
- BEAM: Elixir 1.20.5 / OTP 29.1.2.
- Python measurement/conformance harness: 3.11.18.

When changing a Rust manifest, regenerate the corresponding lockfile with the pinned toolchain and commit the resulting lockfile. The lockfile-generation workflow publishes generated files as an artifact; it does not commit them automatically.


A second smoke matrix has completed with pinned Go/Rust/Elixir/OTP/Wasmtime toolchains and committed Rust lockfiles. Results and caveats: `results/pinned-ci-smoke/README.md`. It remains shared-runner smoke data, not a runtime-selection benchmark.

## Weighted decision matrix

`decision-matrix.md` registers provisional screening gates and weights for p99 latency (25), throughput (20), peak RSS (15), CPU (10), ecosystem/operability (10), failure semantics (10), startup (5), and deployable artifact size (5). Hard correctness/security/failure gates cannot be averaged away. The current three-repetition CI smoke measurements remain diagnostic and do not receive a composite score because the workload and evidence are incomplete.

The opt-in matrix workflow now supports ten randomized repetitions per candidate at 5,000 requests, concurrency 32, and warm-up 250. It records startup time and reports per-run distributions (mean, sample standard deviation, median, min/max, and bootstrap interval for the mean). Shared GitHub-hosted results remain diagnostic; a controlled machine and representative persistence, authorization, inter-service, and failure workloads are still required before any runtime decision.

Latest 10-run diagnostic results are recorded in [the 2026-11-17 report](results/2026-11-17-ten-run-diagnostic.md). All candidates passed functional HTTP checks but failed the provisional CPU gate; no weighted final score or runtime selection is made.
