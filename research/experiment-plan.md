# First Comparative Experiment Plan

Status: proposed executable work. No candidate has won.

## E-001 — Service representation and agent cost

### Question
Does a compact purpose-built service representation improve agent task success and total cost over idiomatic Go and Rust service code?

### Candidate arms
- A: idiomatic Go service.
- B: idiomatic Rust service.
- C: purpose-built Agent Native textual DSL compiled to a canonical IR.
- D: canonical structured IR authored and edited through constrained tools.

The DSL and IR are prototypes only. They must not depend on an existing backend framework.

### Workload
A small service with:
- typed GET /items/{id} and POST /items;
- request/response validation;
- deterministic error mapping;
- in-memory repository for the first syntax experiment;
- explicit authorization effect;
- unit and contract tests;
- one follow-up change to add a field while preserving compatibility.

The first experiment intentionally excludes database and network runtime differences so it isolates representation and agent authoring cost.

### Agent task
Starting from a clean repository and a short task statement, implement the service and pass hidden acceptance tests. Agents use the same compiler/test/inspect tools and task budget in each arm.

### Measures
- success rate;
- tokens and inference cost;
- tool calls;
- wall-clock time;
- failed edits and repair cycles;
- code/IR size;
- diagnostic usefulness;
- follow-up change regression rate.

### Controls
- pin model, settings, prompt, tools, machine image, and dependency versions;
- randomize candidate order;
- run at least 10 repetitions per arm/model/task before interpreting results;
- preserve complete traces and failed trials;
- acceptance tests are not exposed to the agent;
- no candidate-specific extra hints.

### Exit condition
Do not select a service language based on one workload. A candidate advances only if it improves task success or total cost without failing expressiveness, safety, or follow-up-change gates.

## E-007 — Real-agent task and lifecycle acceptance

**Current status (18 November 2026):** the corrected matched factorial is implemented and deterministic CI is green, but no A–D real-model cohort has been dispatched. The workflow is deliberately manual-dispatch-only because it provisions Ollama and runs a potentially long Qwen3 job; do not convert it to ordinary push/PR CI.

The registered factorial isolates two factors while holding total information constant:
- proposal representation: complete Snapshot vs append-only Delta;
- inspection delivery: per-operation vs full-upfront.

Cells A–D are the 2×2 comparison. Minimal-disclosure Delta E is a separate exploratory treatment, not a factorial cell. The runner uses the pinned version-2 case manifest, exact case paths/IDs, fixed budgets, seeded order, independent evaluator, and no-apply policy. PR #53 adds a shared-infrastructure fail-fast guard while preserving matched comparisons after task-level failures.

**Acceptance remains strict:** a single proposal hash must be accepted, semantically validated, and planned; the evaluator must verify exact preservation of the trusted base and the requested change; the plan must be safe with no mutation/deployment; apply must never be invoked. Proposal-only success, budget exhaustion, provider failure, and deterministic mock tests are not lifecycle acceptance.

**Next action:** run the manual workflow on `research/reboot-core` after preflight and inspect the complete artifact before interpreting results. Keep Qwen3 settings and budgets unchanged unless a separate evidence-backed decision explicitly changes them. The current GitHub connector can inspect runs and artifacts but does not expose the workflow-dispatch action, so this particular manual launch cannot be performed from this session.

## E-010 — Sandbox apply boundary

The isolated demo proves a narrowly scoped temporary-SQLite apply path, runtime instance replacement, a smoke request, append-only audit, baseline tamper rejection, and replay idempotency. It does not prove production deployment, arbitrary callback isolation, or deep immutability of ServiceRuntime internals. The default E-009 Gateway remains apply-disabled. The E-010 evidence review is complete; E-011 implementation remains gated on E-007 real-agent acceptance.

## E-002 — Runtime substrate

Compare native Rust runtime, native Go runtime, Wasmtime/WASI Component Model, and BEAM runtime (Gleam or Erlang-targeted workload).

The existing four arms are trivial HTTP/runtime probes only; they do not yet implement the product control plane. The product-representative workload is specified in [E-002 control-plane workload v1](../experiments/e002/control-plane-workload.md), merged through PR #57. It defines authentication, tenant resolution, contract validation, capability authorization, durable audit, idempotent job/outbox admission, expected denials, and fault injection. Its 60/20/10/10 operation mix and 1-vCPU / 100-completed-requests-per-second / 50%-CPU envelope are registered as a hypothesis, not a validated SLO.

Keep the no-persistence control-plane tier separate from the durable product tier. Do not select a storage substrate or treat candidate-specific persistence guarantees as equivalent without a shared conformance suite. WASI must be evaluated as component plus explicit host adapter, with guest and host costs reported separately.

The historical 0.5 CPU-seconds/5,000 trivial-workload gate is retained only for its original cohorts. The prospective product envelope implies 25 CPU-seconds/5,000, but that bound has not been validated. PR #55 improved diagnostic process-tree sampling; a controlled capacity claim should use a dedicated cgroup v2 and record cpu.stat where the host permits it.

Record p50/p95/p99 latency, offered/admitted/completed throughput, expected-denial rate, CPU, throttling, peak memory, startup time, artifact size, storage/audit latency, host-adapter overhead, and tail behavior under injected dependency failures.

## E-003 — Concurrency and failure semantics

Implement the same fan-out/fan-in workflow with bounded concurrency, deadline propagation, cancellation, retries with idempotency, backpressure, worker crash and restart, and structured supervision.

Measure correctness under fault injection, latency, memory, and agent implementation/repair cost.

## Next integrated step

After the E-007 real-agent factorial pilot is accepted and E-010 sandbox-apply evidence is reviewed, the next bounded vertical slice is [E-011 — Inter-service invocation and distributed failure semantics](e011-interservice-communication-plan.md). It extends the existing contract, capability, tenant, and outbox/inbox semantics across two independent service processes; it does not preselect a transport or broker.

## Required artifacts per experiment

- task specification and hash;
- source code for each arm;
- pinned build/runtime environment;
- scripts to run each arm;
- raw result files;
- analysis script;
- failure corpus;
- decision record with confidence and limitations.
