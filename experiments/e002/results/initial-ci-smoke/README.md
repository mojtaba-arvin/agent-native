# E-002 initial CI smoke matrix (not a runtime decision)

<badge>Preliminary only</badge>

- Workflow: [run #43846465352](https://github.com/mojtaba-arvin/agent-native/actions/runs/43846465352)
- Raw request traces and per-run summaries: [download the workflow artifact](https://github.com/mojtaba-arvin/agent-native/actions/runs/43846465352)
- Source revision: `23d955b4b20b613debe694868e2104074c289386`
- Runner: GitHub-hosted `ubuntu-latest`
- Protocol: 3 randomized repetitions per candidate, 1,000 requests per repetition, concurrency 32, 100 warm-up requests, seed `20261116`
- Request: `GET /work?ms=0`; all 1,000 requests in every repetition returned HTTP 200.

## Median observations

| Candidate | Throughput (req/s) | p50 (ms) | p95 (ms) | p99 (ms) | Sampled CPU (s) | Sampled peak process-tree RSS (MiB) |
|---|---:|---:|---:|---:|---:|---:|
| Rust / Tokio + Hyper | 5,061 | 5.735 | 11.226 | 13.639 | 0.06 | 4.15 |
| Elixir / BEAM | 4,845 | 6.010 | 11.091 | 13.720 | 0.20 | 91.12 |
| Go / net/http | 4,501 | 6.427 | 12.412 | 15.785 | 0.12 | 11.70 |
| WASI P2 / Wasmtime 50.0.1 | 4,183 | 6.803 | 13.863 | 17.049 | 0.24 | 28.09 |

The full machine-readable median summary is in `summary.json`; the workflow artifact contains the request-level JSONL and each repetition's summary.

## What this does and does not say

This run validates that the measurement pipeline can exercise all four candidates and retain traces. It does **not** establish that Rust, BEAM, Go, or WASI is the better framework substrate.

The task is intentionally tiny: an in-memory endpoint with no database, meaningful serialization, authorization engine, service-to-service calls, or failure injection. There are only three repetitions on a shared hosted runner. CPU time uses coarse `/proc` tick counters; RSS is sampled every 20 ms and may miss peaks. The WASI measurement includes the Wasmtime CLI host, and the BEAM measurement includes the Mix/BEAM process tree. No confidence intervals, CPU pinning, frequency control, or dedicated-machine isolation were used.

**Decision: none.** The next experiment must use a controlled dedicated machine, more repetitions, richer representative workloads, and failure/cancellation tests before any runtime selection.
