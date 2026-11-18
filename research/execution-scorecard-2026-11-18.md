# Execution scorecard — 2026-11-18

This scorecard separates implemented code, executed tests, measured product behavior, and open acceptance gates. A design artifact or green unrelated workflow is never counted as product completion.

## Measurement rules

- **Implemented:** code is committed on `research/reboot-core`.
- **Executed:** the relevant workflow/job completed and its logs show the command ran.
- **Measured:** raw output or an artifact contains the metric, workload, source revision, environment, and failure count.
- **Accepted:** every preregistered acceptance invariant passes. A successful smoke does not imply acceptance.
- Unknown values remain **not measured**; they are not imputed as zero or converted into speculative percentages.

## E-007 — real Agent lifecycle

| Metric | Current evidence | Acceptance gate |
|---|---|---|
| Matched factorial cells | A–D implemented and validated by deterministic dispatch tests | 4/4 cells produce complete, provenance-valid artifacts |
| Proposal → validate → plan continuity | No successful real-model lifecycle recorded yet | Exact same 64-character proposal hash in all three events for each accepted cell |
| Trusted base preservation | Independent verifier implemented; no accepted live-model artifact yet | 100% of pre-existing declarations preserved and exactly the requested addition present |
| Plan safety | No accepted live-model plan yet | Every accepted cell: `valid=true`, `will_mutate=false`, `will_deploy=false` |
| Apply | Disabled for this cohort | 0 `service.apply` calls |
| Budget | Existing manifest pinned: Qwen3 8B, one repetition/cell, 120,000 input tokens, 6,000 output tokens, 20 tool calls, 3,000 seconds/run | No ceiling increase; all four traces retained including failures |

A 4/4 single-repetition cohort is feasibility evidence only. It is not a powered comparison or an estimate of general Agent success probability.

**Dispatch recovery:** the workflow retains manual `workflow_dispatch` and now has a narrow push-to-dispatch proxy. Only the exact marker file `experiments/e007/dispatch-request.json` on `research/reboot-core`, combined with the exact commit message `experiment(e007): dispatch one bounded factorial cohort`, may start the expensive job. The workflow validates the marker before model installation. Ordinary pushes do not match its path filter. Marker commit: [49a178c](https://github.com/mojtaba-arvin/agent-native/commit/49a178ced8751e5f9a5edbf96054603a55497532). This commit is a dispatch request, not evidence that the workflow completed.

## E-002 — runtime and storage

| Metric | Current evidence | Acceptance gate |
|---|---|---|
| Candidate build/conformance | Latest inspected run [44299814251](https://github.com/mojtaba-arvin/agent-native/actions/runs/44299814251): Go, Rust, WASI P2, BEAM jobs all successful | All four pass the same semantic suite at pinned revisions |
| Durable adapter conformance | No shared E-002 adapter implemented | 100% mandatory atomicity, idempotency, audit, recovery and crash-injection cases pass |
| Product workload | Not yet implemented across all runtime candidates | 60% authorized reads, 20% validate/plan, 10% durable job admission, 10% expected denial |
| Capacity target | No controlled product result yet | 100 completed requests/s, concurrency 32, p99 ≤100 ms, CPU ≤50%, measured under dedicated cgroup v2 |
| Decision-grade repetitions | Benchmark matrix remains skipped | 10 randomized repetitions × 5,000 requests per candidate after conformance; publish raw JSONL and summaries |

The existing process-tree sampler is diagnostic only. It is not a substitute for dedicated cgroup v2 CPU accounting. No runtime or storage engine is selected.

## E-009 — integrated kernel, trust and performance

| Metric | Current evidence | Acceptance gate |
|---|---|---|
| Kernel tests | [Run 44299814465](https://github.com/mojtaba-arvin/agent-native/actions/runs/44299814465): 110 E-009 tests passed | Keep regression suite green |
| E-010 tests | Same run: 3 E-010 tests passed | Keep demo limitations explicit; no arbitrary callback isolation claim |
| Client identity injection | Trusted identity is constructed by host fixture; no production identity adapter | 100% of attempts to submit principal, tenant or grants from client input are rejected |
| Runtime publication | Defensive ownership implemented; publication race contract not implemented | No request may observe a mixed runtime revision under concurrent publication |
| Product-path performance | [Run 44303882187](https://github.com/mojtaba-arvin/agent-native/actions/runs/44303882187), [artifact 14426952929](https://github.com/mojtaba-arvin/agent-native/actions/runs/44303882187/artifacts/14426952929): 1,000 requests, client concurrency 32/server cap 64; 759.48 req/s; p50 6.10 ms, p95 132.78 ms, p99 1,068.81 ms; 0 unexpected statuses | **Harness passed; latency gate failed** (p99 target ≤100 ms). Five repetitions × 1,000 plus warm-up and slowest-operation capture are now wired for the next run; preserve SQLite FULL audit durability |
| Controlled capacity | Not measured | Dedicated host/cgroup, warm-up, 10 repetitions, source and environment pinned |

The E-009 smoke is a real HTTP/SQLite/worker/relay workload on a shared CI runner. The first sample had 12/1,000 503s and p99 1,231.72 ms; after separating server admission capacity from offered client concurrency, the next sample had 0/1,000 unexpected statuses but p99 remained 1,068.81 ms. Synchronous SQLite FULL audit writes are a plausible contributor to tail latency; durability was not weakened. Repeated measurements and per-operation tail attribution are next. This is not a controlled capacity claim, cross-runtime comparison, or isolated CPU/memory accounting.

## E-011 — inter-service semantics

| Metric | Current evidence | Acceptance gate |
|---|---|---|
| Deterministic model | [Run 44303882125](https://github.com/mojtaba-arvin/agent-native/actions/runs/44303882125): **11/11 tests passed**, including seeded 10,000-transition state-machine exercise and idempotency outcome defensive-copy regression | Continue property-based transition sequences; distributed semantics still not proved |
| Retry and unknown outcome | Same-key reconciliation is modelled | No timeout after dispatch may be treated as proof of non-execution |
| Idempotency | In-memory tenant/operation/key model | Across two processes and durable restart, 100 concurrent duplicate requests yield exactly one logical admission |
| Capability attenuation | Audience, operation, resource and expiry escalation rejected by deterministic tests | Property tests find zero accepted escalation cases |
| Two-process transport | Not implemented | Separate processes and stores; fault injection at commit, response loss, delivery and restart; no transport selected before semantic tests pass |

## Repository state

- Working branch: `research/reboot-core`.
- Latest verified E-009/E-011 code commit at scorecard update: `e3d86c96ce1bdc69caed18254992c6078dc77c52`; one-shot E-007 dispatch marker commit: `49a178ced8751e5f9a5edbf96054603a55497532`.
- `main` remains at `da3736c7ea4d239d1ea520d8b56025b4e3251b33`.
- PR #6 remains Open/Draft; no merge is authorized.
- The Actions connector exposes job/artifact inspection by run ID but not a list-workflow-runs or workflow-dispatch write action. Where a push-triggered run cannot be inspected through the available action surface, its status is explicitly unknown until an artifact/run reference is available.
