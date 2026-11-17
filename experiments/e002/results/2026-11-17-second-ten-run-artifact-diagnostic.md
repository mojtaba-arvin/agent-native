# E-002 second ten-run diagnostic and deployable-payload measurement — 17 November 2026

**Workflow:** [44124537511](https://github.com/mojtaba-arvin/agent-native/actions/runs/44124537511)  
**Source revision:** `f32425acacbec79b442db4293286bafb263dcba0`  
**Artifact:** [e002-ten-repetition-diagnostic-matrix, ID 14347795200](https://github.com/mojtaba-arvin/agent-native/actions/runs/44124537511/artifacts/14347795200) (2,505,489 bytes; 14-day retention)  
**Runner:** GitHub-hosted `ubuntu-latest`, Linux x86_64; shared-host diagnostic only  
**Protocol:** seed 20261116; randomized candidate order; 10 repetitions/candidate; 5,000 measured requests/repetition; concurrency 32; warm-up 250  
**Pinned toolchains:** Go 1.23.12; Rust toolchain action 1.100.0; Elixir 1.20.5 / OTP 29.1.2; Wasmtime 50.0.1.

## Runtime-measurement distributions

Values are mean ± sample standard deviation; brackets are bootstrap 95% intervals for the run-level mean. The workload remains the trivial in-memory HTTP endpoint.

| Candidate | Throughput req/s | p99 ms | CPU s / 5k | Peak RSS MiB | Startup s | Functional runs |
|---|---:|---:|---:|---:|---:|---:|
| Rust / Tokio + Hyper | 2,922.541 ± 71.602 [2,876.419, 2,958.417] | 24.182 ± 0.766 [23.744, 24.650] | 0.704 ± 0.020 [0.693, 0.716] | 4.118 ± 0.080 | 0.0090 ± 0.0003 | 10/10 |
| Go / net/http | 2,749.050 ± 11.385 [2,742.527, 2,755.828] | 26.468 ± 1.047 [25.853, 27.079] | 1.126 ± 0.016 [1.116, 1.135] | 13.343 ± 0.241 | 0.0101 ± 0.0003 | 10/10 |
| Elixir / BEAM | 2,762.620 ± 34.413 [2,740.312, 2,778.378] | 26.043 ± 0.770 [25.651, 26.535] | 1.957 ± 0.072 [1.911, 1.998] | 93.211 ± 4.754 | 0.5456 ± 0.0599 | 10/10 |
| WASI P2 / Wasmtime 50.0.1 | 2,502.748 ± 57.687 [2,464.463, 2,528.944] | 28.639 ± 1.552 [27.805, 29.602] | 1.977 ± 0.038 [1.953, 1.995] | 30.670 ± 7.828 | 0.1259 ± 0.0306 | 10/10 |

All four candidates again completed 10/10 functional repetitions, and all four again exceeded the registered 0.5 CPU-seconds/5,000-request screen. This is a second diagnostic cohort on a GitHub-hosted runner, not a controlled-host confirmation or a product SLO result.

## Additional deployable-payload size measurement

The same workflow built each deployable package and emitted `artifact-sizes.json`. Totals are uncompressed bytes on the Linux x86_64 runner and include the candidate payload plus resolved external ELF shared dependencies discovered by `ldd`.

| Candidate | Application/runtime payload | External shared dependencies | Estimated deployable payload |
|---|---:|---:|---:|
| Go / net/http | 7,554,550 B | 2,457,760 B | **10,012,310 B (9.55 MiB)** |
| Rust / Tokio + Hyper | 1,430,704 B | 3,560,616 B | **4,991,320 B (4.76 MiB)** |
| WASI P2 + Wasmtime 50.0.1 | 68,357,954 B (393,690 B component + 67,964,264 B Wasmtime) | 3,589,432 B | **71,947,386 B (68.61 MiB)** |
| BEAM / Elixir OTP | 68,197,850 B production Mix release (663 files, including ERTS) | 6,658,776 B | **74,856,626 B (71.39 MiB)** |

The measurement manifest includes per-file byte counts and SHA-256 hashes. Files are deduplicated by device/inode so a shared library already included in a release is not added again as an external dependency.

**Comparison caveat:** the packaging models are not equivalent. Go/Rust use native executable plus dynamic ELF dependencies; WASI includes the separate Wasmtime host runtime; BEAM includes a self-contained production release with ERTS. This is a Linux-specific, uncompressed deployment-payload estimate. It excludes the OS/kernel, base container image, OS configuration, CA roots, service manager, compressed download size, and runtime memory. It should not be interpreted as a portable package-size ranking.

All four payloads are below the provisional 100 MiB screening ceiling under this exact packaging rule. That is a descriptive size-gate observation, not a final score or runtime choice.

## Updated evidence boundary

**Now measured in two diagnostic runs:** functional HTTP completion, throughput, p99, CPU, sampled process-tree RSS, startup, and one host-specific deployable-payload size manifest.

**Still not measured:** ecosystem/operability scores and the comparable injected-failure semantics suite (deadline, overload/backpressure, cancellation, worker crash/reclaim, retry exhaustion, idempotent replay, outbox duplicate delivery, inbox deduplication, and tenant/data-integrity assertions).

**Still unresolved:** the 0.5 CPU-seconds/5,000-request threshold remains pre-registered but is not derived from a documented product capacity or cost requirement. All four candidates fail it in both ten-run diagnostic cohorts. Do not change the threshold retrospectively; derive any revised gate from a product capacity/cost model before a new workload run.

**Decision:** no complete weighted score and no runtime selection. These shared-host results remain diagnostic only.
