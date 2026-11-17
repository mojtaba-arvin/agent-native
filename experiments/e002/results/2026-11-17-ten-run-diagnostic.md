# E-002 ten-repetition diagnostic result — 2026-11-17

**Workflow:** [44087449181](https://github.com/mojtaba-arvin/agent-native/actions/runs/44087449181)
**Source revision:** `a13faadb948826af63f34be21b6afed47eba7347`
**Artifact:** `e002-ten-repetition-diagnostic-matrix` (14-day retention; raw request JSONL and matrix manifest)
**Runner:** GitHub-hosted `ubuntu-latest`; shared-host diagnostic only
**Pinned toolchains:** Go 1.23.12; Rust toolchain action 1.100.0 (native and wasm32-wasip2); Elixir 1.20.5 / OTP 29.1.2; Wasmtime 50.0.1.
**Protocol:** seed 20261116; 10 randomized repetitions/candidate; 5,000 measured requests/repetition; concurrency 32; warm-up 250; all four candidates passed their functional HTTP measurement with zero failed responses.

## Run-level distributions

Values are mean ± sample standard deviation; bracketed values are the bootstrap 95% interval for the mean. RSS is MiB; startup and CPU are seconds; latency is milliseconds.

| Candidate | Throughput req/s | p99 ms | CPU s / 5k | Peak RSS MiB | Startup s | Functional runs |
|---|---:|---:|---:|---:|---:|---:|
| Rust / Tokio + Hyper | 2,988.245 ± 48.839 [2,957.241, 3,009.902] | 23.509 ± 0.609 [23.202, 23.918] | 0.687 ± 0.013 [0.679, 0.695] | 4.058 ± 0.067 [4.017, 4.096] | 0.009 ± 0.000 [0.0086, 0.0089] | 10/10 |
| Go / net/http | 2,753.888 ± 65.529 [2,712.661, 2,785.318] | 26.072 ± 0.973 [25.530, 26.659] | 1.092 ± 0.035 [1.069, 1.109] | 13.366 ± 0.311 [13.189, 13.554] | 0.010 ± 0.001 [0.0096, 0.0111] | 10/10 |
| Elixir / BEAM | 2,817.860 ± 14.514 [2,809.372, 2,825.265] | 24.988 ± 0.727 [24.544, 25.426] | 1.917 ± 0.063 [1.876, 1.946] | 92.124 ± 4.618 [90.170, 95.303] | 0.546 ± 0.060 [0.527, 0.584] | 10/10 |
| WASI P2 / Wasmtime 50.0.1 | 2,566.645 ± 17.863 [2,556.398, 2,576.629] | 28.028 ± 0.842 [27.564, 28.541] | 1.949 ± 0.021 [1.937, 1.961] | 30.788 ± 8.197 [28.159, 35.991] | 0.115 ± 0.047 [0.086, 0.146] | 10/10 |

## Registered gate results

| Gate | Threshold | Rust | Go | BEAM | WASI P2 |
|---|---:|---:|---:|---:|---:|
| Shared functional conformance | 100% | Pass | Pass | Pass | Pass |
| p99 latency | ≤ 50 ms | Pass | Pass | Pass | Pass |
| Throughput | ≥ 1,000 req/s | Pass | Pass | Pass | Pass |
| Peak RSS | ≤ 128 MiB | Pass | Pass | Pass | Pass |
| CPU / 5,000 requests | ≤ 0.5 s | **Fail** | **Fail** | **Fail** | **Fail** |
| Startup | ≤ 5 s | Pass | Pass | Pass | Pass |
| Ecosystem / operability | ≥ 3/5 | Not measured | Not measured | Not measured | Not measured |
| Failure semantics | 100% injected-failure assertions | Not measured | Not measured | Not measured | Not measured |
| Deployable artifact size | ≤ 100 MiB | Not measured | Not measured | Not measured | Not measured |

All candidates fail the pre-registered CPU gate. The threshold is intentionally not relaxed after observing the data. The next cycle may revise it only before a new run, with a documented rationale and a repeat of the same workload across all candidates.

## Second ten-run diagnostic and deployable payload sizes

A second independent matrix workflow completed later on 17 November: [workflow 44124537511](https://github.com/mojtaba-arvin/agent-native/actions/runs/44124537511), artifact [14347795200](https://github.com/mojtaba-arvin/agent-native/actions/runs/44124537511/artifacts/14347795200), source SHA `f32425acacbec79b442db4293286bafb263dcba0`. It repeated the 10 × 5,000-request protocol with the same pinned candidate/toolchain set. All four candidates again passed 10/10 functional runs and again exceeded the 0.5 CPU-second gate. The run-level details are in [the second-pass report](2026-11-17-second-ten-run-artifact-diagnostic.md).

The same workflow measured an uncompressed Linux x86_64 deployment payload, including candidate package and resolved shared ELF dependencies:

| Candidate | Application/runtime payload | External shared dependencies | Total payload |
|---|---:|---:|---:|
| Go / net-http | 7,554,550 B | 2,457,760 B | **10,012,310 B (9.55 MiB)** |
| Rust / Tokio + Hyper | 1,430,704 B | 3,560,616 B | **4,991,320 B (4.76 MiB)** |
| WASI P2 + Wasmtime 50.0.1 | 68,357,954 B | 3,589,432 B | **71,947,386 B (68.61 MiB)** |
| BEAM production release + ERTS | 68,197,850 B | 6,658,776 B | **74,856,626 B (71.39 MiB)** |

The manifest records per-file byte size and SHA-256 and avoids double-counting shared libraries already bundled in a release. The packaging definitions differ: native executable + shared libraries for Go/Rust, component + Wasmtime for WASI, and a self-contained Mix release + external shared libraries for BEAM. This is a host-specific uncompressed payload estimate, not a universal or compressed package/image comparison. All measured totals are below the provisional 100 MiB screen under this exact method, but this does not offset the CPU hard-gate failure.

**Updated coverage:** deployable payload size is now measured once per candidate on one Linux x86_64 shared runner. Ecosystem/operability scoring and comparable injected-failure semantics remain **not measured**. E-002 remains diagnostic; the CPU gate is still failed by every candidate, and no weighted ranking/runtime selection is justified.

## Partial score visibility (not a final ranking)

Only five weighted metrics were measured. Their provisional normalized contributions sum to 75 points: p99 25, throughput 20, RSS 15, CPU 10, startup 5. The other 25 points are now partially covered: ecosystem/operability (10) and failure semantics (10) remain not measured; deployable artifact size (5) has a single host-specific payload measurement per candidate in the second matrix run. In addition, every candidate misses the provisional CPU eligibility screen, so none is eligible for a final weighted score.

| Candidate | Partial weighted contribution / 75 | CPU normalized score | Final score / 100 |
|---|---:|---:|---|
| Rust / Tokio + Hyper | 72.28 | 0.728 | Not eligible — CPU gate failed; 25 points unmeasured |
| Go / net/http | 69.58 | 0.458 | Not eligible — CPU gate failed; 25 points unmeasured |
| Elixir / BEAM | 67.61 | 0.261 | Not eligible — CPU gate failed; 25 points unmeasured |
| WASI P2 / Wasmtime 50.0.1 | 67.57 | 0.257 | Not eligible — CPU gate failed; 25 points unmeasured |

These partial contributions are descriptive only. They do not establish a runtime ranking or selection.

## What this run proves / does not prove

**It proves:** the four pinned candidate implementations each completed 10 repetitions of the same trivial in-memory HTTP workload; the run-level measurements and raw response traces were retained; distributions and bootstrap intervals can be computed reproducibly from the matrix output; the pre-registered CPU screen was not met by any candidate.

**It does not prove:** comparative performance on persistence, authorization, serialization-heavy, inter-service, or failure workloads; production SLO compliance; ecosystem/maintenance superiority; ecosystem/failure semantics and controlled-host artifact-size suitability; distributed semantics; or that any candidate runtime should be selected. The runner is a shared GitHub-hosted machine and the workload is intentionally narrow.

**Decision:** no runtime selected. Retain this result as diagnostic evidence only.
