# E-002 pinned CI smoke matrix (not a runtime decision)

> Preliminary only — this is a pipeline smoke test, not a runtime-selection benchmark.

- Workflow: [run #43850570600](https://github.com/mojtaba-arvin/agent-native/actions/runs/43850570600) (raw JSONL and per-repetition summaries are attached as artifact `e002-initial-runtime-matrix`)
- Source revision: `24b2d06d49ce2a2d0ae7628044f618992492faf9`
- Runner: GitHub-hosted `ubuntu-latest`
- Toolchains: Go 1.23.12; Rust 1.100.0; Wasmtime 50.0.1; Elixir 1.20.5 / OTP 29.1.2; Python 3.11.18
- Protocol: 3 randomized repetitions per candidate, 1,000 requests per repetition, concurrency 32, 100 warm-up requests, seed `20261116`
- Request: `GET /work?ms=0`; all 1,000 requests in every repetition returned HTTP 200.

## Median observations

| Candidate | Throughput (req/s) | p50 (ms) | p95 (ms) | p99 (ms) | Sampled CPU (s) | Sampled peak process-tree RSS (MiB) |
|---|---:|---:|---:|---:|---:|---:|
| Rust / Tokio + Hyper | 4,009 | 7.271 | 13.344 | 16.035 | 0.10 | 3.92 |
| Elixir / BEAM | 3,751 | 7.880 | 14.374 | 17.307 | 0.29 | 91.89 |
| Go / net/http | 3,707 | 7.984 | 14.425 | 18.689 | 0.16 | 11.90 |
| WASI P2 / Wasmtime 50.0.1 | 3,319 | 8.919 | 16.576 | 19.880 | 0.30 | 28.02 |

Machine-readable medians are in `summary.json`; the workflow artifact retains the raw request-level JSONL and each repetition's summary.

## Interpretation

This confirms that all four pinned builds can run through the same measurement pipeline and produce complete successful traces. It does **not** establish that one substrate is better.

The workload is a trivial in-memory endpoint without database access, meaningful serialization, authorization policy evaluation, inter-service calls, or failure injection. Three repetitions on a shared hosted runner are insufficient for a decision. CPU time uses coarse `/proc` tick counters; RSS is sampled every 20 ms and may miss peaks. WASI includes the Wasmtime CLI host; BEAM includes the Mix/BEAM process tree.

The earlier unpinned smoke run had materially different absolute throughput, which is additional evidence that hosted-runner noise dominates these tiny samples. Do not compare the two runs as a controlled before/after.

**Decision: none.** Use a dedicated, controlled machine, representative service workloads, more repetitions, confidence intervals, and fault-injection tests before selecting a runtime.
