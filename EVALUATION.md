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


The public ten-task corpus, provider-neutral trace/metrics contract, workspace packager, first declarative eval case, Python real-agent runner, deterministic scorer pipeline, and aggregate token/time budget gate live in `experiments/e007/`. The first three-run attempt (Actions run 44087224894) was infrastructure-invalid: Ollama lacked the Qwen3-compatible template-renderer setting and returned empty responses before tool use. The initial eligibility classification was corrected before rerun.

The corrected three-run cohort (Actions run [44087982547](https://github.com/mojtaba-arvin/agent-native/actions/runs/44087982547), artifact [14332334550](https://github.com/mojtaba-arvin/agent-native/actions/runs/44087982547/artifacts/14332334550)) completed with 0/3 accepted. Each attempt failed at `service.validate` with `AN021`. The model supplied the new operation input as the required array, but the full IR snapshot omitted `ir_version=1` and all existing operations. It then called plan even though the semantic result was `valid=false`. The three attempts used `temperature=0` and fixed `seed=42`; per-run usage/tool paths matched and Ollama logs show prompt/KV cache reuse. Treat this as a deterministic failure reproduction, not independent statistical samples or evidence of model superiority. The corrected run is not accepted.

E-005 now documents the exact complete-snapshot IR schema and includes an actionable AN021 fix hint. E-009's local runner blocks planning until the current proposal hash has `result.valid=true`. The E-007 runner also reserves aggregate token/time budgets before each new repetition; a mock integration test confirms that a budget overrun records remaining repetitions as `not_started`, with a distinct resource-budget category. For local Ollama, token pricing is **unpriced** and represented as unknown, not as zero currency cost. These changes pass deterministic CI. A post-fix stochastic probe has now run, but it failed before submitting a corrected proposal, validation, or plan; see the artifact analysis below.

A one-run stochastic probe (Actions [44105440141](https://github.com/mojtaba-arvin/agent-native/actions/runs/44105440141), artifact [14337879630](https://github.com/mojtaba-arvin/agent-native/actions/runs/44105440141/artifacts/14337879630)) used temperature 0.7 and seed 20261117. It produced a full top-level IR with ir_version and seven operations, but rewrote five existing declarations. The Gateway rejected its first proposal because the six existing operations had not yet been inspected; the model then completed the six inspections but did not resubmit before the 900-second wall ceiling, when the provider request failed. No validation or plan occurred. This is one exploratory failure observation, not statistical evidence or a successful post-fix result. The raw payload analysis is in [the stochastic probe report](experiments/e007/results/2026-11-17-stochastic-qwen3-probe.md).

The generic runner for all ten tasks, isolated hidden-oracle execution boundary/sandbox, and accepted E-007 model result are still absent. Hidden acceptance assertions must be mounted by an evaluator outside the agent-visible workspace. A broader three-tier/model cohort and expanded corpus are future work, not current evidence; see [research/e007-future-evaluation-plan.md](research/e007-future-evaluation-plan.md).

For statistical evaluation, do not count same-seed, temperature-zero, prefix-cache-reused reruns as independent model samples. Keep deterministic replay for debugging; stochastic comparisons require non-zero sampling temperature, varied recorded seeds, and a sample-size/power plan.


E-008 adds an executable transactional outbox/inbox model for producer atomicity, fenced relay leases, at-least-once delivery, retry exhaustion, and consumer deduplication after publish-before-ack crashes. It does not claim exactly-once delivery to arbitrary external APIs.

## Current decision/evidence links

- [E-002 CPU gate analysis](experiments/e002/cpu-gate-analysis.md): the 0.5 s / 5,000-request screen was preregistered but is not currently traced to a product capacity or cost requirement. All four candidates failed it; no runtime is selected.
- [E-009 complete IR contract](experiments/e009/ir-contract.md): proposal IR is a complete canonical snapshot, not an implicit patch.
- [E-007 evidence index](research/evidence-index.md) and [design decisions](research/design-decisions.md) preserve the run outcomes, cache/determinism finding, schema corrections, and budget semantics.
