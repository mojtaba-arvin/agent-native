# E-002 CPU gate provenance and interpretation

**Historical evidence snapshot:** 17 November 2026  
**Product-scenario decision addendum:** 18 November 2026  
**Evidence:** [first ten-repetition diagnostic](./results/2026-11-17-ten-run-diagnostic.md), workflow [44087449181](https://github.com/mojtaba-arvin/agent-native/actions/runs/44087449181); [second cohort and payload measurement](./results/2026-11-17-second-ten-run-artifact-diagnostic.md), workflow [44124537511](https://github.com/mojtaba-arvin/agent-native/actions/runs/44124537511)  
**Runtime decision:** none selected.

## Historical registered threshold (17 November)

The decision matrix registered a screening threshold of **0.5 CPU seconds per 5,000 measured requests** before the ten-run matrix was executed. This translates to:

- at most 0.1 milliseconds of CPU time per request;
- at least 10,000 requests per CPU-second on the measured process tree.

The value was a pre-registered research screen, not a product requirement. Its original rationale did **not** tie it to target requests per vCPU, tenant density, deployment cost, instance budget, or a measured production workload. It must remain unchanged when interpreting the historical cohorts.

## Historical observed data

| Candidate | First cohort mean CPU s / 5,000 | Second cohort mean CPU s / 5,000 | Historical 0.5 s screen |
|---|---:|---:|---|
| Rust / Tokio + Hyper | 0.687 | 0.704 | Fail |
| Go / net/http | 1.092 | 1.126 | Fail |
| Elixir / BEAM | 1.917 | 1.957 | Fail |
| WASI P2 / Wasmtime 50.0.1 | 1.949 | 1.977 | Fail |

Both cohorts used ten randomized repetitions on the same class of GitHub-hosted shared runner and the trivial in-memory `GET /work?ms=0` path. The ordering was reproduced, but this is workload-specific diagnostic evidence, not proof that a language/runtime is intrinsically inefficient or unsuitable for the product.

## Measurement limitations

**Historical method:** the two November cohorts used the then-current `benchmark.py`, which measured process-tree CPU from `/proc` snapshots at the beginning and end of each batch. The 20 ms monitor samples estimated peak RSS; CPU was not integrated from those samples. A short-lived descendant could therefore be absent from both CPU snapshots. The raw reports remain valid records of what that version measured, with this limitation. The shared hosted runner and trivial endpoint also limit external validity.

**Prospective harness correction:** the current `benchmark.py` now samples the visible process tree every 5 ms, parses `/proc/<pid>/stat` without assuming the command name contains no spaces, identifies processes by `(PID, start-time ticks)`, and retains each process's maximum observed cumulative CPU so a child that exits between later samples is not dropped from the accumulated total. RSS remains the peak sum of visible process-tree RSS samples. This improves accounting for short-lived descendants but is still not cgroup accounting: a child that starts and exits entirely between samples, or is reparented before discovery, can still be missed. These new measurements must be labelled with the new method and must not be pooled with historical cohorts.

## Product-scenario addendum — 18 November 2026

The product-side scenario has now been made explicit in [the E-002 decision matrix](./decision-matrix.md): an **agent/tool-execution control plane**, comprising authenticated HTTP requests, Gateway dispatch, schema/contract checks, authorization, durable audit persistence, and bounded work submission. Model inference and external provider latency are excluded from the runtime request path.

The provisional capacity envelope is a hypothesis, not a measured SLO:

- one replica with 1 vCPU;
- 100 successful control-plane requests/second sustained at concurrency 32;
- p99 at or below 100 ms, excluding inference and external provider calls;
- sustained CPU at or below 50% of one vCPU, leaving headroom;
- zero authorization, tenant-isolation, audit-ordering, and data-integrity violations, plus complete pass of registered deadline, overload, cancellation, retry, and idempotency assertions.

The CPU bound follows directly from this envelope:

`0.5 CPU-seconds/second ÷ 100 requests/second = 0.005 CPU-seconds/request`.

For a 5,000-request batch, that is **25 CPU-seconds**, not 0.5 seconds.

### Gate treatment

- The old **0.5 CPU-seconds/5,000** threshold remains the historical, pre-registered screen for the old trivial workload. Historical results are not rewritten or rescored.
- The old threshold is **retired as a hard eligibility gate for future product-representative comparisons** because it has no product-capacity provenance. This is a dated prospective decision, not a post-hoc relaxation of the completed historical cohorts.
- The derived **25 CPU-seconds/5,000** value is the provisional product-capacity bound for the next measurement cycle. It is not yet a production SLO and must not be treated as validated until measured on the actual control-plane request mix and a controlled host.
- The existing trivial-endpoint cohorts cannot establish whether any candidate meets the new product envelope. Do not apply the new bound retroactively to them or infer a winner from them.

## Next decision-grade measurement

1. Implement an equivalent authenticated control-plane workload for all four candidates: request parsing/serialization, contract validation, authorization, durable audit, bounded job admission, and the relevant storage/outbox path.
2. Preserve identical externally observable semantics and black-box conformance assertions. Model inference remains outside the measured runtime.
3. Run on a controlled, documented host before making a capacity claim; hosted-runner results remain diagnostic.
4. Improve process-tree CPU accounting so short-lived child processes are not silently missed. Prefer a reliable cumulative accounting interface or frequent sampling with explicit child-exit/reparenting handling; preserve raw per-run measurements.
5. Measure p50/p95/p99, successful throughput, CPU, peak RSS, startup, artifact size, and behavior under deadline, cancellation, overload, retry, worker-crash, and duplicate-delivery injection.
6. Complete the evidence-based ecosystem/operability rubric and comparable failure-semantics suite. Missing evidence remains **not measured**, never zero.
7. Re-register the complete workload, host, thresholds, weights, and analysis before collecting the new cohort. Report raw values and uncertainty; do not calculate a weighted winner while hard gates or required dimensions are missing.

**Current decision:** no runtime is selected, eliminated, or given an optimization mandate. The historical cohorts are diagnostic only. The next valid comparison must use the product-representative control-plane workload and the prospective capacity envelope above.
