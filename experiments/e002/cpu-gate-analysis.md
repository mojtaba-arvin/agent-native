# E-002 CPU gate provenance and interpretation

**Snapshot:** 17 November 2026  
**Evidence:** [ten-repetition diagnostic](./results/2026-11-17-ten-run-diagnostic.md), workflow [44087449181](https://github.com/mojtaba-arvin/agent-native/actions/runs/44087449181)  
**Decision:** no runtime selected; do not change the registered threshold retrospectively.

## What the registered threshold means

The decision matrix registered a screening threshold of **0.5 CPU seconds per 5,000 measured requests** before the ten-run matrix was executed. This translates to:

- at most 0.1 milliseconds of CPU time per request;
- at least 10,000 requests per CPU-second on the measured process tree.

The repository's decision matrix explicitly labels its limits as research screening thresholds, not production SLOs. The available rationale does **not** tie 0.5 seconds to a product requirement, target requests per vCPU, tenant density, deployment cost, instance budget, or a measured production workload. The value is therefore traceable as a pre-registered experimental screen, but **not as a validated service requirement**. The commit and report trail does not establish a stronger origin.

## Observed data

| Candidate | Mean CPU s / 5,000 | CPU ms / request | Requests / CPU-second | Gate result |
|---|---:|---:|---:|---|
| Rust / Tokio + Hyper | 0.687 | 0.1374 | 7,278 | Fail |
| Go / net/http | 1.092 | 0.2184 | 4,579 | Fail |
| Elixir / BEAM | 1.917 | 0.3834 | 2,608 | Fail |
| WASI P2 / Wasmtime 50.0.1 | 1.949 | 0.3898 | 2,565 | Fail |

These are means across ten randomized repetitions on one GitHub-hosted shared runner using the trivial in-memory `GET /work?ms=0` path. The 0.5-second threshold is stricter than each observed mean; Rust is closest, at 1.374 times the threshold, while WASI is 3.898 times it. This is descriptive workload-specific evidence, not proof that a language/runtime is intrinsically inefficient.

## Measurement limitations

`benchmark.py` records process-tree CPU by reading `/proc` at the beginning and end of the measured batch and subtracting the two snapshots. The 20 ms monitor samples are used to estimate peak RSS; CPU is not integrated from those periodic samples. A short-lived descendant that exists and exits between the two CPU snapshots could be absent from both snapshots. The current reports do not demonstrate that this occurred, but the method leaves it as a measurement risk. The shared hosted runner and the trivial endpoint also limit external validity.

## Interpretation and next decision

1. **Do not declare the 0.5-second limit a product hard requirement.** No production capacity or cost envelope currently supports that interpretation.
2. **Do not relax it after seeing these results.** That would be a post-hoc change and would make this registered comparison invalid.
3. **Do not start optimizing all four implementations against it yet.** First establish the product-side requirement: expected request mix, target throughput per vCPU, acceptable CPU utilization/headroom, deployment shape, and cost/replica budget.
4. Before a new comparison, register a replacement or reaffirmed gate from that capacity model, then repeat the same workload on a controlled host. Improve CPU accounting by sampling cumulative process-tree CPU frequently and accounting for child-process exit/reparenting, or use a suitable OS accounting interface. Preserve per-run raw values.
5. Keep ecosystem/operability, injected failure semantics, and comparable deployable artifact size as **not measured** until evidence exists. The current matrix remains diagnostic and cannot yield a final weighted score.

**Current decision:** the four candidates passed the shared functional checks and the measured latency, throughput, RSS, and startup screens, but all failed the provisional CPU screen. No runtime is selected, eliminated, or assigned an optimization mandate from this result alone.
