# E-002 weighted runtime decision matrix

**Status:** criteria registered; current measurements remain diagnostic and no runtime is selected.
**Snapshot:** 17 November 2026
**Candidates:** Go/net-http, Rust/Tokio+Hyper, WASI P2/Wasmtime, Elixir/BEAM.

## Decision rule

The weighted score is a transparent comparison aid, not a substitute for hard correctness/security gates. A candidate that fails a hard gate is not eligible for ranking, regardless of its weighted score. The weights below are frozen for the next comparable measurement cycle; changing them requires a dated rationale and a sensitivity analysis.

| Criterion | Weight | Metric / scoring input | Provisional screening gate |
|---|---:|---|---|
| p99 latency | 25 | Run-level p99 milliseconds | ≤ 50 ms |
| Throughput | 20 | Successful requests/second | ≥ 1,000 req/s |
| Peak process-tree RSS | 15 | MiB | ≤ 128 MiB |
| CPU time | 10 | CPU seconds per 5,000-request measurement batch | ≤ 0.5 s |
| Ecosystem / operability | 10 | Evidence-based rubric, 0–5 | ≥ 3/5 |
| Failure semantics | 10 | Defined fault-injection assertions | 100% pass; also a hard gate |
| Startup time | 5 | Process start to first healthy response | ≤ 5 s |
| Deployable artifact size | 5 | Documented comparable package size | ≤ 100 MiB |
| **Total** | **100** | | |

These are research screening ceilings/floors for the next fixed HTTP workload, not production SLOs. They are intentionally broad enough to identify pathological candidates. They must be re-registered before any future workload intended to represent a production SLO.

### Hard gates

1. 100% shared black-box conformance for all candidates.
2. Zero security or data-integrity violations.
3. 100% pass on every deadline, overload, cancellation, and fault-injection assertion included in the comparison workload.
4. No candidate may bypass the framework-owned service contract, authorization, or effect semantics.
5. All required measurements must be present and collected under the same host/toolchain/request configuration. Missing data is **not measured**, never zero.

### Normalization and total score

For lower-is-better quantitative metrics, normalized score is min(1, gate / observed_value). For higher-is-better throughput it is min(1, observed_value / gate). The ecosystem rubric maps 0–5 to 0–1 by dividing by five. The failure-semantics score is the fraction of assertions passed, but any failure also trips the hard gate.

Weighted contribution is weight × normalized_score; total is the sum of contributions only for candidates that pass all hard gates and have complete measurements. Report raw values alongside normalized values. Vary each weight by ±20%, renormalize to 100, and show whether the ordering changes.

## Current raw observations — pinned CI smoke only

The existing three-repetition matrix used 1,000 measured requests per repetition, concurrency 32, warm-up 100, and the trivial in-memory GET /work?ms=0 endpoint. These are medians across only three repetitions.

| Candidate | Throughput (req/s) | p50 (ms) | p95 (ms) | p99 (ms) | CPU (s) | Peak RSS (MiB) |
|---|---:|---:|---:|---:|---:|---:|
| Rust / Tokio + Hyper | 4,009 | 7.271 | 13.344 | 16.035 | 0.10 | 3.92 |
| Elixir / BEAM | 3,751 | 7.880 | 14.374 | 17.307 | 0.29 | 91.89 |
| Go / net/http | 3,707 | 7.984 | 14.425 | 18.689 | 0.16 | 11.90 |
| WASI P2 / Wasmtime 50.0.1 | 3,319 | 8.919 | 16.576 | 19.880 | 0.30 | 28.02 |

The smoke workload's measured p99, throughput, RSS, and CPU values fall within the provisional screening limits, but that does not mean the candidates have passed the complete gates. Startup distribution, comparable deployable artifact size, ecosystem rubric, database/authorization workloads, failure semantics, and representative application behavior are not established by this run. The sampled CPU/RSS methodology is coarse, and a shared GitHub-hosted runner is noisy.

**Current weighted scores: not calculated.** Missing criteria and the non-representative workload make a composite score misleading. No runtime is selected.

## Next measurement protocol

- Use the existing pinned toolchains and four candidates.
- Run 10 randomized repetitions per candidate, 5,000 measured requests per repetition, concurrency 32, warm-up 250, same runner image and request semantics.
- Retain request-level JSONL, per-run summaries, matrix manifest, random seed, source revision, and toolchain versions.
- Report mean, sample standard deviation, median, min/max, and bootstrap 95% interval for run-level throughput, p99, CPU, RSS, and startup.
- Label results from shared GitHub-hosted runners **diagnostic only**. A runtime decision still requires a controlled dedicated machine, representative persistence/serialization/authorization/inter-service workloads, and fault injection.
- Do not select a runtime in this cycle.
