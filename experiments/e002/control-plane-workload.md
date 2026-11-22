# E-002 — Product-representative control-plane workload v1

**Status:** Python reference workload implemented; not yet benchmarked or ported to candidate runtimes.  
**Decision boundary:** defines comparable behavior before choosing storage adapters, runtime, protocol, or deployment architecture.  
**Product scenario:** authenticated Agent/tool-execution control plane.  
**Inference:** explicitly excluded from the runtime benchmark.

## 1. Why the existing benchmark is insufficient

The current Go, Rust, WASI P2, and BEAM candidates implement a narrow HTTP probe (/health, /work, /stream). They do not yet exercise authenticated principal resolution, tenant isolation, contract validation, capability authorization, durable audit, idempotent admission, or recovery after ambiguous outcomes. Their results are useful for buildability and trivial HTTP behavior only.

The next benchmark must measure the product request lifecycle, not simply a language's HTTP listener. The existing candidate implementations remain probes; no candidate is selected or promoted by this design.

## 2. Workload envelope

The current product-capacity hypothesis is:

- one replica / one vCPU;
- 100 completed control-plane requests per second at concurrency 32;
- p99 no greater than 100 ms, excluding model inference and external provider calls;
- sustained CPU no greater than 50% of one vCPU;
- zero authorization, tenant-isolation, audit-ordering, or data-integrity violations.

At 100 completed requests/s and 0.5 CPU-seconds available per second, the implied budget is 0.005 CPU-seconds/request, or **25 CPU-seconds per 5,000 completed requests**.

This is a capacity hypothesis, not a production SLO. It must be preregistered with the final request mix, storage adapter, host configuration, and fault policy before a confirmatory measurement.

### Request mix

A deterministic seed generates the following mix over the measured cohort:

| Share | Operation class | Expected behavior |
|---:|---|---|
| 60% | Authorized read | Authenticate, resolve tenant, validate contract, authorize read capability, fetch a fixed seeded record, durably audit outcome |
| 20% | Validate / plan | Authenticate, resolve tenant, validate a bounded operation contract, evaluate a non-mutating plan, durably audit outcome |
| 10% | Job admission | Authenticate, validate request and idempotency key, authorize submission, atomically persist job + outbox + audit event, return accepted result |
| 10% | Expected denial | Reject missing/insufficient capability or tenant mismatch, persist a deny audit event, perform no business mutation |

An expected 4xx denial is a correctly completed request for throughput accounting, not a server failure. Transport errors, unexpected 5xx, timeouts, malformed responses, duplicate effects, and data-integrity violations are failures.

The exact fixture identities, capability grants, tenant partitions, records, contract versions, and idempotency-key schedule must be committed as deterministic workload data before implementation. Idempotency is scoped by authenticated tenant and operation: the same key plus the same canonical request hash returns the original logical outcome; the same key with a different hash returns a conflict and never creates a second effect. Attempt/request IDs remain distinct from the idempotency key.

## 3. Framework-owned request lifecycle

Every request must traverse the same observable stages:

1. Parse a bounded HTTP request and strict JSON payload. Reject duplicate keys, invalid UTF-8, non-finite numbers, oversized bodies, and unknown contract fields according to the registered schema.
2. Authenticate using a deterministic benchmark credential fixture. Resolve principal, tenant, and grants from trusted server-side configuration. A caller-supplied tenant field is a scope assertion to verify, never an authority source.
3. Pin and validate the service/operation contract version.
4. Evaluate default-deny capability authorization for the requested operation and resource.
5. Execute only the declared operation handler. No arbitrary shell, filesystem, network, or model tool is available to the handler.
6. Persist the audit outcome before returning the response. Audit records contain request ID, authenticated principal, resolved tenant, operation, contract version, requested effect, decision, and stable reason code. Never persist bearer credentials.
7. For job admission, atomically persist the job record, outbox record, idempotency result, and audit outcome. The benchmark measures admission, not background job execution or model inference.
8. Return a bounded, versioned response with a stable request ID and error envelope.

The benchmark measures the runtime's implementation of these semantics plus the explicitly selected storage adapter. It must not allow one candidate to skip a stage or move work outside the measured boundary.

## 4. Persistence and adapter fairness

Durable audit and atomic job/outbox admission are part of the product path; an in-memory list or a log message is not a durable substitute.

However, persistence substrate is a separate experimental factor and must not be accidentally confounded with runtime:

- First implement a shared storage contract and its conformance suite: append-only audit, atomic job/outbox/audit commit, uniqueness of idempotency keys, reopen/recovery, and injected commit failures.
- Compare candidate adapters only when they provide the same durability and transaction guarantees. Record database engine, version, sync mode, filesystem, and transaction settings.
- Do not claim parity if a candidate uses durable SQLite while another uses memory, buffered file writes, or a host callback with weaker guarantees.
- Keep a no-persistence control-plane microbenchmark as a separate diagnostic tier. It can isolate parsing/auth/dispatch overhead but cannot validate the 25-second product capacity envelope.
- WASI P2 must be measured as component + explicit host adapter. Host-owned listener, filesystem, storage, and admission work are part of its deployment boundary and must be reported separately as well as end-to-end. Do not compare guest-only CPU with native end-to-end CPU.

Storage technology is intentionally not selected in this design. Candidate adapters and their guarantees require a separate evidence-backed decision.

## 5. Required fault-injection cases

The conformance suite must cover at least:

- invalid, expired, or unknown credentials;
- a caller-supplied tenant that conflicts with the authenticated principal;
- missing capability and resource-scope mismatch;
- unsupported contract version, duplicate JSON keys, oversized payload, and invalid field types;
- audit-store unavailable before commit;
- queue capacity exhausted before admission;
- process termination before transaction commit;
- process termination after commit but before response delivery;
- duplicate submission with the same idempotency key;
- same payload with a different idempotency key;
- outbox publish-before-ack duplicate delivery and consumer deduplication; a consumer applies its local effect and records the event ID atomically;
- deadline expiry and client disconnect;
- worker crash and lease recovery;
- restart and recovery of committed audit/job/outbox state.

Expected denial must be distinguishable from infrastructure failure. A timeout after a commit is an unknown client outcome, not proof that the operation failed; the client must reconcile by idempotency key or status lookup rather than create a second logical effect.

## 6. Measurement protocol

Before a decision-grade run:

1. Pin source SHA, compiler/runtime versions, dependency lockfiles, host kernel, storage engine/version, filesystem, and configuration.
2. Register fixture corpus, operation mix, random seed, concurrency, arrival-rate model, warm-up, duration, and all thresholds.
3. Verify 100% black-box conformance and zero security/data-integrity violations before measuring performance.
4. Use an open-loop or rate-controlled generator to sustain the registered 100 completed requests/s; a closed-loop generator alone can hide overload by reducing offered load as latency rises. Record offered, admitted, completed, rejected, and timed-out rates separately.
5. Run 10 randomized repetitions per candidate, 5,000 requests per repetition, concurrency 32, with the same request sequence and storage settings. Preserve raw request-level traces and per-run summaries.
6. Report p50/p95/p99/max latency, offered/completed rate, expected-denial rate, 5xx/timeouts, CPU seconds, CPU throttling, memory peak, queue depth, audit commit latency, storage I/O, and idempotency/retry outcomes.
7. Use a controlled one-vCPU host for capacity claims. Shared GitHub-hosted runner results remain diagnostic.
8. Do not calculate a weighted winner while any hard gate or required metric is missing. Missing evidence is **not measured**, never zero.

### CPU accounting

Preferred controlled-host measurement: place exactly one candidate and its descendants in a dedicated cgroup v2 and record cpu.stat before and after the run. The Linux kernel documents usage_usec, user_usec, and system_usec as accounting for processes in the cgroup and descendant cgroups. Also record cpu.max, effective CPU quota, and throttling counters. Do not include the load generator in the candidate cgroup.

The current 5 ms /proc sampler is an improved diagnostic fallback, not equivalent to cgroup accounting. It can still miss a child that starts and exits entirely between samples or is reparented before discovery. If a dedicated cgroup cannot be established, mark the run diagnostic and do not claim a validated capacity result.

Reference: https://docs.kernel.org/admin-guide/cgroup-v2.html

## 7. Exit criteria

E-002 can make a product-runtime recommendation only when:

- all candidates implement the same request lifecycle and pass 100% of shared conformance assertions;
- no security, tenant, audit, idempotency, or data-integrity violations occur;
- all required fault-injection semantics are measured and pass;
- the product workload runs on a controlled one-vCPU host with dedicated CPU accounting;
- p99, throughput, CPU, memory, startup, artifact, ecosystem/operability, and failure-semantics evidence is complete;
- sensitivity analysis shows whether the weighted ordering is robust;
- the decision record separates guest/runtime performance, host-adapter overhead, storage cost, and deployment/operability.

## 8. Non-goals

- No model inference in the measured request path.
- No production runtime selection from the existing trivial /work endpoint.
- No implicit selection of SQLite, PostgreSQL, a broker, gRPC, Connect, WASI host APIs, or a service mesh.
- No exactly-once claim for arbitrary external effects.
- No extrapolation from shared hosted runners to production capacity.
- No candidate is disqualified merely because an adapter has not yet been implemented; mark it not measured until comparable evidence exists.


## 9. Reference workload implementation status

The E-009 Python reference host now exposes an isolated benchmark contract in `benchmark_catalog.an` when `AGENT_NATIVE_PRODUCT_WORKLOAD=1`. Its deterministic seeded schedule is implemented in `experiments/e002/product_workload.py` and preserves exact 60/20/10/10 shares in each ten-request block. The measured path is:

- 60% authenticated tenant-scoped item reads;
- 20% authenticated, revision-pinned non-mutating validate/plan requests at `POST /control/validate-plan`;
- 10% atomic durable job admission with job + outbox + idempotency + audit commit;
- 10% expected missing-capability denials, durably audited with no handler mutation.

The validate/plan benchmark operation is a read-only reference operation over the frozen base Catalog contract; it is not a claim that the full agent Gateway proposal lifecycle has been benchmarked. The HTTP host continues to use strict bounded JSON parsing, trusted in-memory identity fixtures, contract validation, default-deny authorization, durable audit, and versioned runtime responses. Integration tests verify valid/stale plan requests, missing-capability denial, and trace-to-audit correlation.

**Remaining E-002 gates:** shared storage adapter conformance across runtimes, all required fault-injection cases under the product mix, Go/Rust/WASI/BEAM workload parity, ten randomized 5,000-request repetitions, and controlled one-vCPU cgroup accounting. Until those gates pass, this is an executable reference workload—not a runtime comparison or capacity certification.
