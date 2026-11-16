# Evaluation Protocol

## Objective

Select a programming model, implementation language, compiler strategy, and runtime for a new independent backend framework using reproducible evidence.

## Experimental units

Separate these questions to avoid confounding:
1. **Agent tool surface/protocol:** progressive-disclosure typed tools vs structured request/response protocol vs CLI vs MCP-compatible exposure.
2. **Service representation:** text DSL vs structured IR vs hybrid.
3. **Service language:** existing language vs purpose-built syntax.
4. **Runtime implementation language:** candidate systems languages.
5. **Execution substrate:** native runtime vs VM vs WASM vs actor/hybrid.
6. **Framework semantics:** service, data, security, concurrency, and distributed behavior.

Do not compare candidates that change all dimensions simultaneously and then attribute the result to one choice.

## Agent cohorts

Test at least three capability tiers:
- constrained: smaller model, limited context/tool budget;
- general: mid-capability model;
- advanced: strongest available coding agent.

Use the same task statement, environment, allowed tools, dependency versions, time/token budget, and acceptance tests. Randomize candidate order. Repeat each task enough times to estimate variance; report failures, not only successful runs.

## Task corpus

Start with small, independently verifiable tasks and grow to full service tasks:
- add a typed endpoint;
- add a field and safe migration;
- implement tenant isolation;
- add idempotent event processing;
- handle a timeout and retry safely;
- refactor service boundaries;
- diagnose and repair injected failure;
- add a backward-compatible API version;
- submit durable work, recover after process restart, fence a stale worker, and atomically record a local effect;
- inspect a service, propose a typed change, validate it, and produce a safe execution plan;
- handle a stale proposal revision and repair a machine-readable diagnostic.

Each task must have hidden acceptance tests where feasible, plus explicit security and resource-limit checks.

## Metrics

### Agent cost
- input/output tokens and inference cost;
- tool calls;
- wall-clock time;
- compilation/test cycles;
- failed edits and repair loops;
- human interventions;
- task completion rate;
- time to first correct implementation;
- regression rate after change;
- tool-schema discovery tokens and payload size;
- diagnostic repair success and number of follow-up tool calls;
- ratio of read-only/proposal calls to mutation-capable calls.

### Runtime cost
- p50/p95/p99 latency;
- throughput;
- CPU and peak memory;
- startup time;
- binary/artifact size;
- database and network overhead;
- resource use under load and failure.

### Quality
- functional acceptance;
- type/contract correctness;
- security policy violations;
- data integrity;
- fault recovery;
- compatibility;
- observability completeness;
- maintainability under follow-up changes.

## Scoring

Report raw metrics first. Composite scores may be used only with published weights and sensitivity analysis. Never hide catastrophic security or correctness failures inside an average.

Primary metric: total cost per accepted task, with hard gates for security, data integrity, and minimum runtime performance.

## Reproducibility

Every experiment records:
- task corpus revision and hashes;
- agent/model identifiers and settings;
- prompt and tool policy;
- hardware/OS/container image;
- candidate/compiler/runtime versions;
- dependency lockfiles;
- benchmark scripts and raw outputs;
- number of repetitions and confidence intervals;
- failed and timed-out trials.

## Baseline fairness

Existing frameworks are comparison baselines only, not implementation foundations. Use idiomatic, maintained versions and competent reference implementations. Do not intentionally handicap alternatives. Compare equivalent semantics, not superficial line counts.

## Gates

- **G0 — Research integrity:** criteria, tasks, and baseline environments fixed.
- **G1 — Agent interface:** repeatable evidence that both the tool surface and service representation improve agent task success/cost without sacrificing expressiveness or safety.
- **G2 — Core feasibility:** executable prototype with typed service, data, effects, and runtime lifecycle.
- **G3 — Safety:** adversarial and negative tests show authority is enforced outside the model.
- **G4 — Distributed behavior:** failure, retry, cancellation, idempotency, and schema evolution verified.
- **G5 — Performance:** competitive measurements on equivalent workloads.
- **G6 — Production candidate:** deployment, observability, recovery, compatibility, and upgrade story validated.

No production-readiness claim before G0–G6 evidence exists.


The current public task subset and provider-neutral trace metrics live in `experiments/e007/`. It defines tasks and oracle identifiers only; hidden acceptance assertions must be mounted by an evaluator outside the agent-visible workspace. No agent runs have been performed.


E-008 adds an executable transactional outbox/inbox model for producer atomicity, fenced relay leases, at-least-once delivery, retry exhaustion, and consumer deduplication after publish-before-ack crashes. It does not claim exactly-once delivery to arbitrary external APIs.
