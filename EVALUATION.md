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

After Gateway-owned exact preservation, bounded proposal-attempt enforcement, and final-candidate retention were implemented, a new single deterministic Qwen3 attempt was dispatched: [workflow 44144939813](https://github.com/mojtaba-arvin/agent-native/actions/runs/44144939813). It uses `temperature=0`, `seed=42`, and a 1,200-second wall cap, rather than the earlier 900-second cap. The run completed but was ineligible: it consumed 48,307 input tokens against the 48,000 per-run cap after inspecting five of six operations. It did not submit a second proposal or reach validation/plan; no AN021 or provider/OOM failure occurred. The 1,200-second wall cap was not reached (1,020.139 seconds observed). The artifact originally marked this run eligible, but the runner's eligibility classifier was corrected because per-run budget exhaustion must not enter the agent-acceptance denominator. See [the raw-trace analysis](experiments/e007/results/2026-11-17-deterministic-postfix-budget-exhaustion.md). The expanded-budget follow-up [workflow 44149712970](https://github.com/mojtaba-arvin/agent-native/actions/runs/44149712970) has been inspected: the Gateway accepted one exact-preserving proposal, but the run reached its 1,800-second wall ceiling before validation or plan. All semantic and authority gates remained unchanged.

The E-009 Gateway now retains the inspected base declarations and rejects same-revision proposals that rewrite service identity, types, or original operations. It returns `IR_PRESERVATION_MISMATCH` with changed operation names and exact-copy guidance. The local adapter enforces a maximum of three proposal attempts (including Gateway-rejected attempts), blocks planning before semantic validation, and saves parseable final JSON before candidate verification. These deterministic controls pass in the latest 80-test E-009 suite [44128413303](https://github.com/mojtaba-arvin/agent-native/actions/runs/44128413303). The expanded-budget Qwen3 run now demonstrates one successful real-model proposal cycle through Gateway acceptance with exact preservation; semantic validation and planning remain unverified.

E-002 has two ten-run diagnostic cohorts; a second workflow measured one Linux x86_64 uncompressed deployment payload per candidate (Go 10,012,310 B, Rust 4,991,320 B, WASI+Wasmtime 71,947,386 B, BEAM+ERTS 74,856,626 B). Ecosystem/operability and comparable fault injection remain unmeasured, and all candidates fail the provisional CPU gate. Details are in [the second-pass matrix report](experiments/e002/results/2026-11-17-second-ten-run-artifact-diagnostic.md).

A later expanded-budget deterministic probe, [workflow 44149712970](https://github.com/mojtaba-arvin/agent-native/actions/runs/44149712970), [artifact 14360782135](https://github.com/mojtaba-arvin/agent-native/actions/runs/44149712970/artifacts/14360782135), used temperature 0 / seed 42, 96,000 input tokens and a 1,800-second wall cap. Raw-trace audit found 6/6 operations inspected; proposal attempt one was blocked by `INSPECTION_INCOMPLETE`, attempt two by `IR_PRESERVATION_MISMATCH` for `submit_rebuild`, and attempt three was accepted by the Gateway. The accepted IR had `ir_version=1`, the correct input declaration array, exact service/types and all six existing operation objects preserved in order, plus the exact requested seventh operation. Its SHA-256 matched the Gateway change-set ID. **No AN021 occurred.** The model then failed to produce the next assistant response before the 1,800-second wall deadline; the Ollama daemon log records cancellation at that boundary and an HTTP 500 symptom, with no OOM evidence. No `service.validate` or `service.plan` call occurred. This is one deterministic observation of proposal acceptance, not a completed eval task or statistical evidence. See [full trace analysis](experiments/e007/results/2026-11-17-expanded-budget-proposal-accepted-timeout.md).

A bounded deterministic continuation is now running as [workflow 44189163401](https://github.com/mojtaba-arvin/agent-native/actions/runs/44189163401). It keeps Qwen3, temperature 0, seed 42, the same task, Gateway preservation, scorer thresholds, validation gate and no-apply policy; the upfront sequence is made explicit and schema-discovery calls are discouraged. Context is 16,384, input cap 120,000 and wall cap 3,000 seconds. The run is exploratory and must not be counted as statistical evidence; acceptance remains pending raw artifact review.

The generic runner for all ten tasks, isolated hidden-oracle execution boundary/sandbox, and accepted E-007 model result are still absent. Hidden acceptance assertions must be mounted by an evaluator outside the agent-visible workspace. A broader three-tier/model cohort and expanded corpus are future work, not current evidence; see [research/e007-future-evaluation-plan.md](research/e007-future-evaluation-plan.md).

For statistical evaluation, do not count same-seed, temperature-zero, prefix-cache-reused reruns as independent model samples. Keep deterministic replay for debugging; stochastic comparisons require non-zero sampling temperature, varied recorded seeds, and a sample-size/power plan.

The runner's failure taxonomy distinguishes provider transport loss before the wall deadline from a provider symptom correlated with a proven wall-deadline cancellation. At the configured deadline, the derived failure class is `wall_clock_budget_exhausted` with `timeout` and `resource_budget_exceeded`; the immutable raw provider symptom remains in the run record. Explicit OOM evidence is separate. Regression tests cover both deadline cancellation and pre-deadline transport loss.


E-008 adds an executable transactional outbox/inbox model for producer atomicity, fenced relay leases, at-least-once delivery, retry exhaustion, and consumer deduplication after publish-before-ack crashes. It does not claim exactly-once delivery to arbitrary external APIs.

## Current decision/evidence links

- [E-002 CPU gate analysis](experiments/e002/cpu-gate-analysis.md): the 0.5 s / 5,000-request screen was preregistered but is not currently traced to a product capacity or cost requirement. All four candidates failed it; no runtime is selected.
- [E-009 complete IR contract](experiments/e009/ir-contract.md): proposal IR is a complete canonical snapshot, not an implicit patch.
- [E-007 evidence index](research/evidence-index.md) and [design decisions](research/design-decisions.md) preserve the run outcomes, cache/determinism finding, schema corrections, and budget semantics.


The bounded continuation [workflow 44189163401](https://github.com/mojtaba-arvin/agent-native/actions/runs/44189163401), artifact [14376970288](https://github.com/mojtaba-arvin/agent-native/actions/runs/44189163401/artifacts/14376970288), has been inspected. Despite context 16,384 and a 3,000-second wall cap, Qwen3 repeated `service.inspect` with empty arguments twice and was stopped as `repeated_invalid_tool_call` after 267.785 seconds. This is an agent/tool-schema failure, not a timeout. No further Qwen3 budget increase is authorized. The 1,800-second proposal-accepted run did not reach a completed validation request because its next prompt prefill was cancelled at the wall deadline. See the [forensic continuation analysis](experiments/e007/results/2026-11-17-post-proposal-continuation-analysis.md).


## Infrastructure validity update — 18 November 2026

The raw Ollama daemon logs for workflows [44149712970](https://github.com/mojtaba-arvin/agent-native/actions/runs/44149712970) and [44189163401](https://github.com/mojtaba-arvin/agent-native/actions/runs/44189163401) show CPU-only inference, CPU model buffers, and two model threads on standard GitHub-hosted workers. No GPU backend or GPU model buffer was loaded.

For the 1,800s run, the final prompt was 7,734 tokens in an 8,192-token context, with 764 cached prefix tokens and about 240 seconds left in the global run budget when the request began. Ollama logged prefill checkpoints at 20.09, 19.05, 18.05, and 17.04 tokens/second; prompt prefill was incomplete at the wall deadline. The 2.38 tokens/second figure in the preceding request is decode throughput, not prefill. The wall budget includes all prior model calls and Gateway work; it must not be treated as time available to the final prompt alone.

This is a threat to validity: the 1,800s run cannot be used to claim the model ignored or refused service.validate, because the model never completed prefill for the post-proposal turn and no decode/tool call was recorded. The separate 3,000s run remains a repeated empty-arguments tool-contract failure.

A deterministic prompt-compaction implementation now replaces repeated assistant/tool history with an exact Gateway-state ledger while retaining raw provider/tool traces. Its provider-double regression test checks exact inspected declarations and recent diagnostics. Real-model behavior is not yet validated. The isolated fixed-1,000-token prefill benchmark and short schema probe are still pending. No further full-task Qwen3 budget increase is authorized.
