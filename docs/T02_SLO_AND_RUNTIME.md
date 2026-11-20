# T02 — v0.1 SLO and Rust-versus-Go decision rule

**Decision status:** the product-capacity target and selection procedure are preregistered. **No runtime is selected by this decision.**  
**Scope:** the v0.1 single-service product boundary in [V1_PRODUCT.md](V1_PRODUCT.md), using the authenticated Agent/tool-execution control-plane workload.

## 1. Decision boundary

This record fixes the measurements and selection procedure that must be applied before the Rust and Go runtime experiments are used to choose a candidate. It does not select an implementation language or runtime, and it does not claim that the targets below have already been met.

The comparison is limited to:

- **Rust/Tokio + Hyper**
- **Go/net/http**

The candidates must implement the same framework-owned request lifecycle and use the same durable storage contract. Neither candidate may bypass service-contract validation, authenticated identity resolution, capability authorization, durable audit, or idempotent job admission.

Model inference and external provider calls are outside the measured runtime request path. They are not silently charged to one candidate or omitted from only one candidate.

## 2. Registered capacity envelope

The following is the v0.1 **capacity acceptance hypothesis** for one service replica. It becomes a production SLO only after the decision-grade controlled-host workload passes; the existing prototypes and CI smoke results do not establish that.

| Dimension | Registered target | Measurement boundary |
|---|---:|---|
| Service CPU allocation | **1 vCPU** | Candidate process and all descendants in one dedicated cgroup v2 |
| Service memory allocation | **1 GiB** | Candidate cgroup memory.max = 1073741824 bytes |
| Completed throughput | **100 completed requests/second** | Rate-controlled open-loop arrival; expected 4xx denials count as completed requests |
| Concurrency | **32** | Same in-flight request limit for both candidates |
| Tail latency | **p99 ≤ 100 ms** | End-to-end service request path; inference and external provider calls excluded |
| Sustained CPU budget | **≤ 50% of one vCPU** | cgroup v2 cpu.stat usage over the measured interval |
| CPU budget per standard repetition | **≤ 25 CPU-seconds per 5,000 completed requests** | Derived from 100 req/s at 0.5 CPU-seconds per second |
| Memory safety | **No OOM events; peak ≤ 1 GiB** | cgroup memory peak and memory.events |

The CPU bound is derived, not guessed:

0.5 CPU-seconds/second ÷ 100 completed requests/second = 0.005 CPU-seconds/request

0.005 × 5,000 = 25 CPU-seconds per 5,000 completed requests

The one-GiB service memory ceiling adopts the explicit resource-limited configuration already exercised by the E-009 capacity harness. It is a hard experiment boundary, not a claim that the eventual framework will require or consume one GiB.

The PostgreSQL instance is an identical, separately provisioned dependency for both candidates. Its version, configuration, durability settings, storage, and resource allocation must remain the same. Record its CPU, memory, and I/O separately; do not attribute database resource use to only one runtime or hide storage work from the end-to-end latency measurement.

## 3. Product-representative workload

The benchmark is the authenticated Agent/tool-execution control plane, not the historical trivial GET /work?ms=0 probe.

The deterministic measured request mix is:

| Share | Operation class | Required behavior |
|---:|---|---|
| 60% | Authorized read | Authenticate, resolve tenant, validate contract, authorize read capability, fetch the seeded record, and durably audit the outcome |
| 20% | Validate / plan | Authenticate, resolve tenant, validate a bounded operation contract, produce a non-mutating plan, and durably audit the outcome |
| 10% | Job admission | Authenticate, validate request and idempotency key, authorize submission, atomically persist job + outbox + audit + idempotency result |
| 10% | Expected denial | Reject missing/insufficient capability or tenant mismatch, persist a deny audit event, and perform no business mutation |

Expected 4xx denials are valid completed requests for throughput accounting. Unexpected 5xx responses, timeouts, malformed responses, transport failures, duplicate effects, authorization violations, and data-integrity failures are not successful completions.

Every candidate must execute the same observable stages: bounded request parsing, trusted principal/tenant resolution, contract validation, default-deny authorization, declared handler execution, durable audit before response, and atomic durable job/outbox/idempotency/audit admission. A candidate that substitutes in-memory audit, skips authorization, weakens durability, or moves work outside the measured request boundary is not comparable.

## 4. Preregistered measurement protocol

Before the decision-grade cohort, pin and retain the source SHA, toolchains, lockfiles, host and kernel, PostgreSQL version/configuration, filesystem, service cgroup settings, workload fixtures, request sequence, and random seed.

For each candidate:

1. Pass 100% of the shared black-box conformance and fault-injection assertions before performance scoring.
2. Use a rate-controlled open-loop generator to sustain 100 completed requests/second; a closed-loop generator alone is not sufficient because it can conceal overload by reducing offered load as latency rises.
3. Run **10 randomized repetitions per candidate**, **5,000 measured requests per repetition**, concurrency 32, and 250 warm-up requests. Randomize candidate order and preserve the same deterministic request sequence and storage settings.
4. Retain raw request-level traces and per-run summaries. Report offered, admitted, completed, rejected, expected-denial, and timed-out rates separately.
5. Report p50/p95/p99/max latency, CPU seconds, CPU throttling, peak cgroup memory, OOM counters, queue depth, audit commit latency, storage I/O, and idempotency/retry outcomes for every repetition.
6. Measure candidate CPU from cgroup v2 cpu.stat (usage_usec, user_usec, system_usec) and record cpu.max and throttling counters. The candidate and its descendants belong in the service cgroup; the load generator does not.
7. Measure peak cgroup memory and memory.events; retain database resource/I/O measurements separately.
8. Use a controlled, documented one-vCPU host for capacity claims. Shared GitHub-hosted runner results are diagnostic only. The 5 ms /proc process-tree sampler is an explicitly limited fallback, not equivalent to cgroup accounting.
9. Keep every repetition. Report the run-level distribution and uncertainty; do not pool historical start/end-snapshot CPU cohorts with measurements from the newer sampler or cgroup accounting.

A candidate must meet each performance target in **all 10 repetitions**. An aggregate mean or median must not hide a repetition that missed throughput, p99, CPU, or memory limits.

## 5. Hard eligibility gates

A Rust or Go candidate is eligible for selection only when all of the following are true:

1. **Functional conformance:** 100% pass of the shared positive, negative, and failure-contract assertions.
2. **Security and integrity:** zero authorization, tenant-isolation, audit-ordering, idempotency, or data-integrity violations.
3. **Failure semantics:** 100% pass of every registered deadline, overload/backpressure, cancellation acknowledgement, worker-crash/lease-reclaim, retry-exhaustion, duplicate-delivery, inbox-deduplication, and recovery assertion.
4. **Request-path performance:** every repetition sustains at least 100 completed requests/second and p99 ≤ 100 ms.
5. **CPU:** every 5,000-completed-request repetition consumes no more than 25 cgroup CPU-seconds.
6. **Memory:** the service cgroup peak stays within 1 GiB and records no OOM/OOM-kill event.
7. **Comparison fairness:** the same contract, authorization, persistence durability, PostgreSQL configuration, host, request mix, and measurement boundary are used for Rust and Go.

A hard-gate failure cannot be offset by a better weighted score. An expected denial is not a failure; an unexpected 5xx, timeout, missing audit, duplicate effect, or security/data violation is. If required evidence is absent, record **not measured**; never substitute zero or count an unrun assertion as passed.

## 6. Rust-versus-Go selection rule

The existing E-002 decision matrix weights remain registered for the comparison. The failure-semantics and correctness requirements above remain hard gates, regardless of their weighted contribution.

| Criterion | Weight | Comparison input |
|---|---:|---|
| p99 latency | 25 | Median of the 10 run-level p99 values; lower is better |
| Completed throughput | 20 | Median completed requests/second; higher is better |
| Peak memory | 15 | Median peak service-cgroup memory; lower is better |
| CPU | 10 | Median cgroup CPU-seconds per 5,000 completed requests; lower is better |
| Ecosystem / operability | 10 | Evidence-based 0–5 rubric below |
| Failure semantics | 10 | 1.0 only after 100% of required assertions pass; also a hard gate |
| Startup time | 5 | Median process-start to first healthy response; lower is better |
| Deployable artifact size | 5 | Comparable complete Linux x86_64 deployable payload; lower is better |
| **Total** | **100** | |

The ecosystem/operability rubric awards one point per dimension, or 0.5 for partial evidence, only when supported by primary documentation or a reproducible operational demonstration:

1. Toolchain maturity, stable releases, reproducible builds, debugging and profiling.
2. Dependency maintenance, release cadence, compatibility policy and dependency risk.
3. Security response, advisories, patching and support lifecycle.
4. Diagnostics and observability: structured logs, metrics, traces, crash diagnostics and production debugging.
5. Deployment and operations: packaging, upgrade/rollback, health, resource limits, supervision and operational burden.

For each quantitative criterion, compare the two candidates using the same 10-run cohort: for lower-is-better metrics, normalized score is best observed value / candidate value; for higher-is-better throughput, it is candidate value / best observed value. The ecosystem score is rubric score / 5. Failure semantics scores 1.0 only for a candidate that passes every required assertion. Multiply each normalized value by its registered weight and sum to a score out of 100.

Do not calculate a final score when either candidate lacks a required, comparable metric or hard-gate evidence. In particular, missing startup, artifact, ecosystem, or failure-semantics evidence is not zero and does not permit a winner to be declared.

The selection outcome is determined as follows:

- If both candidates have complete evidence and only one passes every hard gate, select the sole eligible candidate; record the failed gates and supporting raw evidence for the other.
- If neither passes every hard gate, select neither.
- If both pass, select the higher weighted-score candidate only when its advantage is at least **5 points** out of 100, the paired **95% bootstrap confidence interval** for the score difference excludes zero, and the registered ±20% weight sensitivity analysis does not reverse the ordering.
- If the two candidates are within 5 points, the confidence interval includes zero, or the weight sensitivity analysis reverses the ordering, record **no winner** and collect additional paired evidence under the same preregistered protocol.
- If either candidate has incomplete evidence rather than a demonstrated hard-gate failure, record **no selection** until the comparison is complete.

A runtime recommendation is scoped to this workload and deployment envelope. It is not a claim that one language is universally superior, nor does it select the framework's service language, syntax, compiler, database, or execution substrate.

## 7. Historical evidence and current decision

The historical **0.5 CPU-seconds per 5,000 requests** threshold remains unchanged for interpreting the November 17 trivial in-memory GET /work?ms=0 cohorts. It is retired as a prospective product eligibility gate because it was not derived from a product capacity or cost requirement. Do not retroactively rescore those cohorts against the new target.

The second historical ten-run diagnostic measured mean CPU of 0.704 seconds/5,000 for Rust and 1.126 seconds/5,000 for Go, but it used the trivial endpoint on a shared GitHub-hosted runner. Those values are not evidence that either candidate meets the authenticated control-plane envelope and do not determine this selection.

The E-009 resource-limited capacity evidence used a one-vCPU/one-GiB cgroup and a 100 req/s workload, but its SQLite operation mix differs from the E-002 control-plane mix, and later repetitions showed p99 variance under storage/I/O pressure. It is useful provenance for the resource envelope, not proof that the product workload or either Rust/Go candidate passes.

**Current decision: no runtime selected.** The 1-vCPU / 1-GiB envelope, workload, hard gates, measurement protocol, weights, and Rust-versus-Go selection rule are now fixed prospectively. Selection remains pending comparable decision-grade results.

## 8. Evidence references

- [E-002 product-representative control-plane workload](../experiments/e002/control-plane-workload.md) — request lifecycle, operation mix, fault cases, and controlled-host protocol.
- [E-002 weighted runtime decision matrix](../experiments/e002/decision-matrix.md) — registered criterion weights and score normalization.
- [E-002 CPU gate provenance](../experiments/e002/cpu-gate-analysis.md) — why the historical 0.5-second screen was retired prospectively and how the 25-second budget is derived.
- [E-002 second ten-run diagnostic](../experiments/e002/results/2026-11-17-second-ten-run-artifact-diagnostic.md) — historical raw summary and limitations.
- [E-009 resource-limited performance evidence](../experiments/e009/performance-evidence-2026-11-18.md) — one-vCPU/one-GiB resource configuration and its repeatability limitations.
