# Design decisions and evidence-driven reversals

**Snapshot:** 17 November 2026  
**Branch:** `research/reboot-core`  
**Purpose:** durable record of experimental findings, bugs, contract decisions, and rejected interpretations. Entries are append-only; changing a decision requires a new dated entry rather than rewriting the historical outcome.

## D-001 — Three Qwen3 repetitions are deterministic reproductions, not independent samples

**Evidence:** E-007 workflow [44087982547](https://github.com/mojtaba-arvin/agent-native/actions/runs/44087982547), artifact ID `14332334550`, source SHA `1596d595e040267279324aafb7542213b9f31d89`.

The three runs used `temperature=0.0`, `seed=42`, `top_p=1.0`, `qwen3:8b`, and identical prompts/configuration. All three produced identical per-request token-count sequences, 35,984 input tokens, 1,602 output tokens, 11 tool calls, and the same tool arguments/diagnostics. The Ollama server log explicitly shows prompt/KV cache reuse (including `prompt is already in the cache, skipping` and repeated `cached n_tokens` entries).

**Decision:** label the cohort “three deterministic repetitions of one failure path,” not independent model samples and not statistical evidence. The log supports prompt-state caching, not response-cache replay; the retained provider diagnostic records do not expose a cached-token counter, so cache savings cannot be quantified. A future stochastic trial must use temperature above zero and vary the seed by repetition; its outputs must be inspected separately.

## D-002 — E-009 proposal IR is a complete snapshot, never an implicit patch

**Evidence:** the same E-007 artifact. The accepted proposal request contained `service`, `types`, and `operations`, but omitted `ir_version` and included only the new operation. Its new operation `input` was correctly serialized as an array containing `name`, `source`, and `type`.

The E-005 `_propose` handler deep-copies and stores the submitted IR as-is. `_validate` passes that stored object directly to E-001 `validate_ir`; there is no merge, inferred version, or patch expansion. The missing `ir_version` explains the observed `AN021`. Omitting the existing operations is a separate completeness/preservation defect that would be caught by the E-007 scorer even after the version field is added.

**Decision:** document the full-snapshot contract; expose the complete IR shape in the tool schema; explicitly require the version, service identity, complete types, all existing operations, and requested change. Do not silently relax the validator or invent an implicit patch format.

**Implemented:** `experiments/e009/ir-contract.md`, updated E-005 `tools.json`, E-009 task and system prompt, an `AN021` fix hint, and contract tests. These changes pass deterministic CI but have not yet been validated by a post-fix real-model run.

## D-003 — Validation's semantic result must gate planning

**Evidence:** in all three E-007 runs, `service.validate` returned an outer `ok=true` tool envelope while `result.valid=false` with nested `AN021`. The model called `service.plan` next. The runner had treated outer tool success as sufficient to record validation, and the gateway's plan endpoint returned a non-mutating invalid plan rather than forcing the model to repair first.

**Decision:** distinguish transport/tool invocation success from semantic validation success. A plan is allowed only when the latest proposal hash has an explicit `result.valid=true` validation result. The E-009 local runner now intercepts a premature/mismatched plan request before it reaches the Gateway and returns `VALIDATION_REQUIRED` with a repair hint.

**Implemented:** pure gate helper and tests for invalid validation, hash mismatch, and valid matching hash. E-009 CI passed. Real-model behavior after this guard remains unverified.

## D-004 — Aggregate evaluation budgets reserve the next repetition before launch

**Decision:** keep per-run input/output/tool/wall ceilings and add an aggregate run-level budget for tokens, elapsed agent time, and estimated local inference charge. Before every repetition, the runner reserves the configured worst-case per-run allowance; if the next repetition cannot fit, it records remaining repetitions as `not_started` and excludes them from agent acceptance rather than labelling them model failures. Missing usage after a run fails closed for further repetitions.

**Cost semantics:** the current Ollama run has no per-token provider tariff. Its billable inference charge is therefore not priced; electricity, hardware depreciation, and shared runner-hosting cost are not estimated. A zero configured local tariff is not a claim that total compute cost is zero.

**Implemented:** aggregate budget settings, fail-fast reservation, explicit `resource_budget_exceeded` taxonomy, and an integration-style mock runner test that executes one fake run then refuses two further repetitions when aggregate input reservation would exceed the ceiling. CI passed. The real-model three-run artifact predates this budget implementation.

## D-005 — Failure taxonomy must inspect nested validation diagnostics

The E-007 Gateway protocol places semantic validation diagnostics under `response.result.diagnostics` while the outer envelope remains successful. Inspecting only `response.diagnostics` misses `AN021`. The classifier now examines outer diagnostics, nested validation diagnostics, and plan validation diagnostics. The raw failure code remains preserved alongside taxonomy categories.

**Implemented:** nested-diagnostic extraction and regression tests. The old E-007 artifact remains the ground truth for the original run; no retrospective rewrite of its stored data is claimed.

## D-006 — E-002 CPU threshold remains a provisional screen, not a product SLO

The 0.5 CPU-second/5,000-request limit was registered before the ten-run matrix, but the available repository evidence does not derive it from a product workload, vCPU capacity target, deployment-cost envelope, or production SLO. All four candidate means exceeded it. The result is retained without a post-hoc threshold change.

**Decision:** do not declare the threshold invalid merely because candidates missed it, and do not declare it a product requirement. Derive any future limit from a documented capacity/cost model before a new benchmark. See [CPU gate analysis](../experiments/e002/cpu-gate-analysis.md).

## D-007 — Three repetitions do not establish model superiority or statistical reliability

The E-007 trial has one task, one model version, one temperature/seed configuration, and three deterministic failure reproductions. It supports a reproducible failure analysis only. A broader evaluation requires multiple model capability/size levels, diverse tasks and difficulty strata, and a pre-registered stochastic seed schedule with a power/sample-size rationale. That design is future work, not current evidence.
