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

## E-002 — Runtime substrate

Compare native Rust runtime, native Go runtime, Wasmtime/WASI Component Model, and BEAM runtime (Gleam or Erlang-targeted workload).

Use equivalent HTTP, concurrency, timeout, cancellation, and streaming workloads. Add database and durable messaging after a transport-only baseline.

Record p50/p95/p99 latency, throughput, CPU, peak RSS, startup time, artifact size, isolation overhead, and tail behavior under injected dependency failures.

## E-003 — Concurrency and failure semantics

Implement the same fan-out/fan-in workflow with bounded concurrency, deadline propagation, cancellation, retries with idempotency, backpressure, worker crash and restart, and structured supervision.

Measure correctness under fault injection, latency, memory, and agent implementation/repair cost.

## Required artifacts per experiment

- task specification and hash;
- source code for each arm;
- pinned build/runtime environment;
- scripts to run each arm;
- raw result files;
- analysis script;
- failure corpus;
- decision record with confidence and limitations.
