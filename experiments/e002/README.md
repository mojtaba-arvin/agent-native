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


## Deployable artifact-size diagnostic

The optional ten-run matrix workflow also writes `artifact-sizes.json` using `measure_artifacts.py`. It measures one built payload per candidate on the same Linux x86_64 runner:

- Go and Rust: application executable plus all resolved shared ELF dependencies reported by `ldd`.
- WASI P2: the component plus the pinned Wasmtime host executable and its resolved shared ELF dependencies.
- BEAM: the production Mix release including bundled ERTS, plus resolved shared ELF dependencies for ELF files inside that release.

The report records each input file's byte size and SHA-256, the host platform, package components, and the uncompressed total. Files are deduplicated by device/inode; a shared library already bundled in a release is not counted twice.

This is a **Linux payload-size diagnostic**, not an apples-to-apples portable package or container image comparison. It excludes the kernel, base image, OS configuration, CA roots, and service manager. It does not measure compressed downloads, image layers, runtime memory, installation time, or operational complexity. BEAM and WASI have different packaging models from native binaries; record the breakdown and do not use size alone to rank or select a runtime.

The complete matrix (including this size measurement) was run as [workflow 44124537511](https://github.com/mojtaba-arvin/agent-native/actions/runs/44124537511), with [artifact-sizes.json in artifact 14347795200](https://github.com/mojtaba-arvin/agent-native/actions/runs/44124537511/artifacts/14347795200). The observed uncompressed payload totals were Go 10,012,310 B (9.55 MiB), Rust 4,991,320 B (4.76 MiB), WASI P2 + Wasmtime 71,947,386 B (68.61 MiB), and BEAM + ERTS 74,856,626 B (71.39 MiB). Details and package-component breakdowns are in [the second-pass diagnostic report](results/2026-11-17-second-ten-run-artifact-diagnostic.md). These are Linux x86_64 host-specific measurements, not directly comparable portable package/container sizes. They do not affect the conclusion that all candidates failed the provisional CPU gate; no runtime is selected.

## CPU accounting method — prospective harness revision

The current benchmark harness uses 5 ms `/proc` process-tree samples for CPU accounting. Each process is identified by `(PID, start-time ticks)` to distinguish ordinary PID reuse; because start time has finite clock-tick resolution, this is a practical guard rather than a mathematically unique process identifier. The parser isolates the parenthesized command name before indexing `/proc/<pid>/stat`, because command names may contain whitespace or parentheses. Per-process cumulative CPU maxima are retained across samples, so a child that exits after being observed remains included rather than disappearing from the final process-tree total.

The summary records the method, interval, and limitations. This is an improvement over the historical start/end process-tree snapshots, but it is **not cgroup accounting**: a descendant that starts and exits entirely between samples, or is reparented before discovery, may still be missed. Peak RSS remains the maximum sum of visible process-tree RSS samples and can double-count shared pages. The method is suitable for a better diagnostic, not a controlled-host capacity claim.

Historical November 2026 cohorts were collected with the earlier start/end CPU snapshot method. Keep those results unchanged and do not pool them with results from this revised sampler. The new method must be recorded in every future matrix artifact.


## Product-representative workload design

The next E-002 phase is specified in [control-plane-workload.md](control-plane-workload.md). It defines the authenticated Agent/tool-execution request lifecycle, deterministic operation mix, durable audit and idempotent job/outbox semantics, fault injection, and controlled-host measurement requirements. This is a design proposal only: the current four HTTP probes do not implement that workload, and no runtime or persistence substrate is selected. The 25 CPU-seconds/5,000-request capacity bound remains a hypothesis until the same semantics are implemented and measured on a controlled one-vCPU host.


## Process-tree CPU sampler integration smoke

The Go candidate's sampler smoke step passed in [E-002 workflow 44294049076](https://github.com/mojtaba-arvin/agent-native/actions/runs/44294049076): 100 measured requests, concurrency 8, warm-up 10; all 100 responses were HTTP 200. The revised sampler emitted the expected method metadata and reported 0.01 CPU seconds and 8,286,208 bytes peak summed RSS; observed p99 was 4.70 ms in this single short shared-runner smoke. This validates that the measurement path executes and emits plausible structured output. It is **not** a performance comparison, cgroup measurement, or product-capacity evidence.


## Cross-runtime process-tree sampler smoke

The Go sampler smoke passed in [workflow 44294049076](https://github.com/mojtaba-arvin/agent-native/actions/runs/44294049076). The BEAM sampler smoke passed in [workflow 44294310926](https://github.com/mojtaba-arvin/agent-native/actions/runs/44294310926): 100 requests, concurrency 8, warm-up 10, 100/100 HTTP 200, two observed processes, 0.04 CPU seconds, 93,364,224 bytes peak summed RSS, p99 6.66 ms, startup 0.613 s. Four BEAM tests and black-box conformance also passed. This is a short shared-runner instrumentation smoke, not a Go-vs-BEAM comparison or capacity result. The 2,453 requests/s value is especially unsuitable for comparison because the sample contains only 100 measured requests.

The shared durable storage semantics are now specified in [storage-conformance-contract.md](storage-conformance-contract.md). It is a design contract only: no adapter has been implemented or selected. Durable adapter comparison remains blocked on implementing and passing the same atomicity, idempotency, audit, recovery and fault-injection suite.


## T16 immutable benchmark image and evidence provenance

The T16 benchmark image is built from the committed `experiments/e002/t16/Dockerfile` by GitHub Actions and published to GHCR. The image contains both native candidate binaries and the Go open-loop load generator. CI resolves the Go, Rust, and PostgreSQL base-image tags to manifest digests and supplies those immutable references as build arguments. The build emits an `image-lock.json` artifact containing the full source SHA, immutable `image@sha256:digest` reference, source-SHA tag, base-image digests, Dockerfile path, and Actions build-run URL.

The controlled-host preflight requires `--image-ref` and `--build-run-url`. The runner pulls that exact digest, verifies the OCI source and revision labels and the registry RepoDigest, and rejects mutable tag-only references. It never builds candidate or load-generator artifacts locally; both candidates and the load generator execute from the same verified image. Image identity and build provenance are included in preregistration, protocol, every ledger record, and final results/report.

GitHub Actions shared runners are used for tests, image build, smoke tests, publication, SBOM, and provenance attestations only. They are not accepted as controlled-host benchmark evidence. Digest pinning identifies the produced artifact but does not by itself guarantee bit-for-bit reproducibility of every upstream build input. Set the GHCR package visibility to public after its first publication so controlled hosts can pull it without a personal token. Verify the registry attestation with:

```sh
gh attestation verify oci://ghcr.io/mojtaba-arvin/agent-native-t16@sha256:IMAGE_DIGEST \
  -R mojtaba-arvin/agent-native
```


### Controlled-host operator flow

Download the `t16-image-lock-<source-sha>` artifact from the successful image-publish Actions run. On the dedicated Linux host, verify the provenance attestation and derive all runtime identity values from that lock file rather than copying a mutable tag:

```sh
gh run download <BUILD_RUN_ID> \
  --repo mojtaba-arvin/agent-native \
  --name t16-image-lock-<SOURCE_SHA> \
  --dir t16-image-lock

SOURCE_SHA="$(jq -r .source_sha t16-image-lock/image-lock.json)"
IMAGE_REF="$(jq -r .image_ref t16-image-lock/image-lock.json)"
BUILD_RUN_URL="$(jq -r .build_run_url t16-image-lock/image-lock.json)"

gh attestation verify "oci://$IMAGE_REF" -R mojtaba-arvin/agent-native

export AGENT_NATIVE_E002_POSTGRES_DSN='postgresql://...'
python experiments/e002/t16/preflight.py \
  --attestation /secure/path/host-attestation.json \
  --source-sha "$SOURCE_SHA" \
  --image-ref "$IMAGE_REF" \
  --build-run-url "$BUILD_RUN_URL" \
  --command "python experiments/e002/t16/run.py --source-sha $SOURCE_SHA --image-ref $IMAGE_REF --build-run-url $BUILD_RUN_URL"

python experiments/e002/t16/run.py \
  --source-sha "$SOURCE_SHA" \
  --image-ref "$IMAGE_REF" \
  --build-run-url "$BUILD_RUN_URL"
```

The attestation file must explicitly identify the dedicated physical host, the host operator, and a timezone-qualified attestation timestamp. The PostgreSQL service must already be running in its own one-CPU cgroup on the preregistered physical core. Do not replace the digest with `:t16` or the source-SHA tag when launching a benchmark.


For a single-command operator path, keep the downloaded image lock and host-attestation JSON outside the Git checkout (the runner intentionally rejects unexpected untracked files), then use:

```sh
gh run download <BUILD_RUN_ID> \
  --repo mojtaba-arvin/agent-native \
  --name t16-image-lock-<SOURCE_SHA> \
  --dir /tmp/t16-image-lock

export AGENT_NATIVE_E002_POSTGRES_DSN='postgresql://...'
T16_IMAGE_LOCK=/tmp/t16-image-lock/image-lock.json \
T16_HOST_ATTESTATION=/secure/path/host-attestation.json \
  bash experiments/e002/t16/run-controlled-host.sh
```

The helper validates the lock against the checked-out source and Dockerfile, verifies the GitHub attestation, creates the preregistration/host/protocol manifests, and starts the benchmark with the exact digest. It requires `jq`, `gh`, Docker, PostgreSQL client tools, `taskset`, and Python 3.11+ on the controlled host.
