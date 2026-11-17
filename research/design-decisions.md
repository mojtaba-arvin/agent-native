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

**Evidence:** in all three E-007 runs, `service.validate` returned an outer `ok=true` tool envelope while `result.valid=false` with nested `AN021`. The model called `service.plan` next; the original runner did not intercept it, and the Gateway returned an invalid, non-mutating plan with the same nested AN021 diagnostic. Provider diagnostics then recorded a final assistant response with 1,437 content characters, but the response body was not retained. The trace contains no subsequent corrected `service.propose`. We therefore know the model had a post-error response turn, but cannot inspect its exact text or assert whether it internally formulated a corrected candidate; we can say only that it did not submit one through the Gateway.

**Decision:** distinguish transport/tool invocation success from semantic validation success. A plan is allowed only when the latest proposal hash has an explicit `result.valid=true` validation result. The E-009 local runner now intercepts a premature/mismatched plan request before it reaches the Gateway and returns `VALIDATION_REQUIRED` with a repair hint.

**Implemented:** pure gate helper and tests for invalid validation, hash mismatch, and valid matching hash. E-009 CI passed. Real-model behavior after this guard remains unverified.

## D-004 — Aggregate evaluation budgets reserve the next repetition before launch

**Decision:** keep per-run input/output/tool/wall ceilings and add an aggregate run-level budget for tokens, elapsed agent time, and estimated local inference charge. Before every repetition, the runner reserves the configured worst-case per-run allowance; if the next repetition cannot fit, it records remaining repetitions as `not_started` and excludes them from agent acceptance rather than labelling them model failures. Missing usage after a run fails closed for further repetitions.

**Cost semantics:** local Ollama has no configured per-token provider tariff. The case now uses an explicit `unpriced_local` mode with null token rates and a null currency ceiling. The runner emits no `cost_usd` value and reports currency cost as unknown; it does not encode the absence of a tariff as $0. Electricity, hardware depreciation, and shared runner-hosting cost are also not estimated.

**Implemented:** aggregate budget settings, fail-fast reservation, explicit `resource_budget_exceeded` taxonomy, and an integration-style mock runner test that executes one fake run then refuses two further repetitions when aggregate input reservation would exceed the ceiling. CI passed. The real-model three-run artifact predates this budget implementation.

## D-005 — Failure taxonomy must inspect nested validation diagnostics

The E-007 Gateway protocol places semantic validation diagnostics under `response.result.diagnostics` while the outer envelope remains successful. Inspecting only `response.diagnostics` misses `AN021`. The classifier now examines outer diagnostics, nested validation diagnostics, and plan validation diagnostics. The raw failure code remains preserved alongside taxonomy categories.

**Implemented:** nested-diagnostic extraction and regression tests. The old E-007 artifact remains the ground truth for the original run; no retrospective rewrite of its stored data is claimed.

## D-006 — E-002 CPU threshold remains a provisional screen, not a product SLO

The 0.5 CPU-second/5,000-request limit was registered before the ten-run matrix, but the available repository evidence does not derive it from a product workload, vCPU capacity target, deployment-cost envelope, or production SLO. All four candidate means exceeded it. The result is retained without a post-hoc threshold change.

**Decision:** do not declare the threshold invalid merely because candidates missed it, and do not declare it a product requirement. Derive any future limit from a documented capacity/cost model before a new benchmark. See [CPU gate analysis](../experiments/e002/cpu-gate-analysis.md).

## D-007 — Three repetitions do not establish model superiority or statistical reliability

The E-007 trial has one task, one model version, one temperature/seed configuration, and three deterministic failure reproductions. It supports a reproducible failure analysis only. A broader evaluation requires multiple model capability/size levels, diverse tasks and difficulty strata, and a pre-registered stochastic seed schedule with a power/sample-size rationale. That design is future work, not current evidence.

## D-008 — Cost without a tariff is unknown, not zero

An Ollama-local run does not have a provider invoice or a configured per-token tariff. Setting input/output rates and maximum estimated cost to numeric zero would create a misleading statement in E-007 metrics, where `cost_usd=0` means known zero priced inference cost. The eval case now uses `cost_pricing_mode=unpriced_local` and null price/ceiling fields. The runner omits `cost_usd` from model-usage events in this mode, leaves inference currency cost null, and still enforces input/output-token and wall-time limits. Explicit per-token tariffs remain supported via `per_token` mode.

**Verification:** deterministic runner tests cover unpriced cost as `None`, explicit per-token arithmetic, and aggregate budget fail-fast. The real-model 3-run artifact predates this refinement.

## D-009 — Preserve final candidate JSON before verification

The original E-007 artifact exposed an evidence gap: when the final assistant response was parseable JSON but semantic verification failed, `local_agent.py` raised before writing `candidate.json`. Tool traces proved that the model made no corrected proposal, but the final 1,437-character response body was not available for inspection.

**Decision:** persist the final parsed JSON candidate with private file permissions before semantic verification. A rejected candidate remains evidence and is still scored as unaccepted; persistence must not turn it into a verified candidate. Non-JSON responses are not promoted to candidate artifacts.

**Implemented:** `_persist_candidate_response` writes mode-0600 candidate JSON before validation, and a deterministic test checks the file content and permissions. The one-shot stochastic run already in progress began before this change; a subsequent real-model run is required to validate the new artifact path end to end.

## D-010 — Stochastic Qwen3 produces a different but still invalid proposal path

**Evidence:** exploratory workflow [44105440141](https://github.com/mojtaba-arvin/agent-native/actions/runs/44105440141), artifact [14337879630](https://github.com/mojtaba-arvin/agent-native/actions/runs/44105440141/artifacts/14337879630), one run of `qwen3:8b` with temperature 0.7 and seed 20261117.

Unlike the fixed temperature-zero cohort, the attempted proposal included `ir_version=1`, the complete top-level keys, seven operation entries, and array-shaped input declarations. The Gateway rejected it before validation because it was sent before the six existing operations had been inspected. After receiving `INSPECTION_INCOMPLETE`, the model inspected all six operations, demonstrating that this feedback path can direct the model to complete inspection. The proposal payload retained in the trace nevertheless rewrote five of the six existing operation contracts (capabilities, effects, input declarations, errors, or validation rules). No second corrected proposal was sent before the 900-second wall limit; the final provider request ended in an Ollama HTTP 500/cancel at the boundary. No validate or plan call occurred.

**Decision:** the complete-snapshot shape prompt improved the observed outer IR shape in this one stochastic attempt, but preservation remains a separate unsolved requirement. Do not relax preservation or authority semantics. Keep server-side inspect-all gating and strengthen the model-visible copy-exactly instruction and regression tests. This single probe is not statistical evidence or proof of end-to-end improvement.

**Failure classification refinement:** retain the raw `provider_transport_failure` and additionally tag `resource_budget_exceeded` when the failed run duration reaches its configured wall ceiling. A provider failure far below the deadline must not automatically be called a budget exhaustion.

**Record:** [stochastic probe report](../experiments/e007/results/2026-11-17-stochastic-qwen3-probe.md).

## D-011 — Complete IR shape is distinct from exact operation preservation

The deterministic Qwen3 cohort omitted `ir_version` and existing operations. The stochastic probe included the correct top-level keys and all seven operation entries, but rewrote five existing operation contracts. A top-level JSON schema can guarantee presence and type shape; it cannot prove the model copied the inspected semantic declarations unchanged. The E-007 exact candidate contract scorer remains necessary, and any future server-side preservation rule must explicitly bind the proposal to the inspected base revision and declarations. Do not conflate "complete IR" with "preserved IR."

## D-012 — Enforce base preservation in the E-009 Agent Gateway, not only in the local model adapter

The stochastic Qwen3 probe reached a proposal shape containing all seven operation slots, but rewrote five existing contracts. A task scorer can detect this only after a candidate is produced; prompt text alone is not an enforcement boundary. An adapter-only comparison would also be bypassable by another client of the Gateway.

**Decision:** the E-009 Gateway now snapshots the inspected service identity, types, and every existing operation declaration for the inspected revision. Before forwarding a same-revision `service.propose`, it checks that the submitted complete IR retains the service/types and exact ordered existing-operation declarations. A mismatch returns `IR_PRESERVATION_MISMATCH` with named operations and a fix hint. The Gateway still enforces the inspect-all prerequisite. The local adapter retains only the bounded total proposal-attempt budget; there is one authoritative preservation check at the Gateway rather than duplicate adapter and Gateway rules.

**Scope:** this is an E-009 Gateway policy for this fixed task environment, not a claim that all future Agent Native services must forbid operation deletion/change. A general change protocol needs explicit, typed change intent and migration/compatibility semantics rather than an implicit preservation rule.

**Tests:** Gateway tests cover exact service/types/operation preservation, reject a mutated existing capability, and verify actionable `IR_PRESERVATION_MISMATCH` diagnostics. The subsequent refactor removed duplicate local-adapter preservation logic and left the Gateway as the only authoritative enforcement point. The current branch passed 80 E-009 tests in [workflow 44128413303](https://github.com/mojtaba-arvin/agent-native/actions/runs/44128413303), including Gateway preservation, plan gating, bounded proposal attempts, candidate retention, and audit persistence.


## D-013 — A successful tool envelope is not a successful validation

The E-009 Gateway response envelope uses `ok` to report whether the tool request was processed. The semantic result of `service.validate` is separately represented by `result.valid`. An observed response with `ok=true` and `result.valid=false` is therefore a successful invocation of a failed validation, not an accepted proposal. The old local agent treated the outer envelope as sufficient to continue and called `service.plan` after AN021.

**Decision:** require an explicit `result.valid is True` for the exact current `change_set_id` before planning. A new proposal invalidates the prior validation state. A plan request with no matching successful validation is intercepted locally with `VALIDATION_REQUIRED`; the scorer independently checks the same hash continuity in the raw trace. This preserves the distinction between transport/protocol success and domain-level success.

**Evidence:** deterministic E-009 plan-gate tests and the original three-run Qwen3 trace (workflow [44087982547](https://github.com/mojtaba-arvin/agent-native/actions/runs/44087982547)). The new real-model trial after Gateway preservation enforcement is pending; no claim is made that Qwen3 follows the corrected gate yet.

## D-014 — Provider HTTP failure, transport loss, timeout, and resource exhaustion are distinct

The stochastic Qwen3 run ended at the configured 900-second boundary. The Ollama daemon log records cancellation of the active inference task and an HTTP 500 response at that boundary. The local adapter recorded the provider HTTP failure; this is not evidence of an arbitrary network disconnect or an out-of-memory event.

**Decision:** preserve the raw provider failure code and classify (a) connection/transport exceptions as `transport_error`, (b) non-200 provider responses as `provider_http_error`, (c) reaching the configured wall ceiling as `timeout` plus `resource_budget_exceeded`, and (d) explicit OOM/allocation-kill evidence as `resource_exhaustion`. Do not infer OOM from HTTP 500, or infer timeout from an early transport failure. The categories may coexist when the raw provider symptom occurs at the wall boundary.

**Verification:** E-007's 48-test deterministic suite covers HTTP 500 at the wall ceiling, transport failure well below the ceiling, local/outer runner wall expiration, explicit OOM evidence, and budget exhaustion without misclassifying it as an agent failure. The new one-run deterministic workflow uses a 1,200-second per-run wall limit because the previous deterministic cohort approached 900 seconds; this is an exploratory budget adjustment, not a retroactive reinterpretation of the earlier artifact.

## D-015 — The 900-second wall limit was too close to observed deterministic runtimes

The earlier deterministic cohort completed its three attempts in 843.78–894.95 seconds, with one run only about five seconds below the 900-second cap. The stochastic attempt reached the cap and Ollama cancelled the active request. The stochastic trial does not prove that temperature caused the longer path, and the 900-second cap was not derived from a product SLA.

**Decision:** use 1,200 seconds for the next single deterministic post-fix probe to avoid truncating a near-900-second path. Keep the limit explicit in the pinned case and workflow, retain aggregate budget enforcement, and report the setting difference. This is not an unlimited retry policy and does not imply that future runs should always receive more time. A successful run within 1,200 seconds would only establish one bounded observation.


## D-016 — Preserve the fifth Qwen3 trial as a layered failure case

**Evidence:** E-009 workflow [44081733833](https://github.com/mojtaba-arvin/agent-native/actions/runs/44081733833), artifact [14328213511](https://github.com/mojtaba-arvin/agent-native/actions/runs/44081733833/artifacts/14328213511), source revision `71a957d1949d4d8bbbeb4267ccaaa0589c8a77ba`. The 765.1-second run consumed 33,714 input and 1,314 output tokens over 12 tool calls. After the agent completed all six existing-operation inspections, the proposal endpoint accepted a malformed IR with only `types` and `operations`, no `ir_version` or `service`, one operation only, and object-shaped input `{"name":"String"}`. Validation returned outer `ok=true` but `result.valid=false` with `AN021`; the agent then repeated the same proposal hash and payload. The local runner stopped with `multiple_successful_proposals`. No plan or apply occurred. The retained Ollama log shows the final request completed HTTP 200 and no observed OOM, kill, cancellation, or provider error.

**Decision:** retain this as a distinct, fully traced failure case rather than collapse it into the later E-007 array-input/partial-IR failure. It demonstrates why inspection gating, complete-IR schema, semantic validation gating, and repeated-proposal classification must be separate controls. The case study is [fifth-qwen3-trial-case-study.md](../experiments/e009/fifth-qwen3-trial-case-study.md).

**Limit:** one run supports only the causal account of this trace; it does not establish a failure rate or model-wide behavior. Subsequent fixes are supported by deterministic tests but require a fresh real-model artifact for behavioral confirmation.


## D-017 — Per-run token exhaustion is resource-budget-ineligible, not an agent failure

**Evidence:** post-Gateway-preservation Qwen3 workflow [44144939813](https://github.com/mojtaba-arvin/agent-native/actions/runs/44144939813), artifact [14357367813](https://github.com/mojtaba-arvin/agent-native/actions/runs/44144939813/artifacts/14357367813), source SHA `f476e5a5ead74317da7c831c48460934b75bcf4e`. At temperature 0 / seed 42, the run used 48,307 input tokens against a 48,000 cap, 1,373 output tokens, 11 tool calls, and 1,020.139 seconds against a 1,200-second wall limit. It inspected five of six existing operations; the first proposal was rejected with `INSPECTION_INCOMPLETE`; the token ceiling stopped the run before a second proposal, validation, or plan. The Ollama log shows completed HTTP 200 responses and no observed OOM, cancellation, or provider error.

The raw artifact's original `eligible_for_acceptance` flag was `true`, despite `failure=AgentRunError:input_token_budget_exceeded` and `failure_categories=[resource_budget_exceeded]`. This is an evaluator eligibility bug, not evidence that the model completed or failed semantic validation.

**Decision:** per-run input/output/tool/wall/model-turn/candidate-size budget exhaustion is ineligible for the agent-acceptance denominator and remains separately reported as `resource_budget_exceeded`. Aggregate budget exhaustion before launching a repetition is likewise ineligible. Keep the raw artifact immutable; record the post-hoc classification correction rather than rewriting its JSON. Proposal-repair exhaustion remains an agent/task failure because it is a semantic repair limit, not an infrastructure budget stop.

**Verification:** E-007's 51-test suite [44149051059](https://github.com/mojtaba-arvin/agent-native/actions/runs/44149051059) covers the per-run budget codes and asserts they are ineligible and not categorized as `agent_or_runner_failure`.

## D-018 — Expand the next deterministic probe's resource envelope once, based on measured consumption

The 48,000-input-token cap stopped the post-Gateway run after five of six inspections. The 1,200-second wall ceiling was not reached (observed 1,020.139 seconds). The provider prompt-token sequence increased from 2,388 to 5,733 tokens per successive request; cumulative input usage counts repeated conversation context across requests. The remaining operation inspection and a corrected proposal/validation/plan sequence were therefore not covered by the run.

**Decision:** authorize one bounded follow-up at 96,000 cumulative input tokens and 1,800 seconds wall time, keeping model, task, temperature 0, seed 42, top-p, context, output/tool ceilings, Gateway preservation rules, scorers, and no-apply policy unchanged. The larger envelope is a preregistered correction to a demonstrably insufficient per-run resource cap; it does not relax any IR, preservation, validation, or authority requirement. If this single attempt still exhausts budget, stop and optimize the interaction/prompt protocol before any further resource increase.

**Limit:** this is a single deterministic debugging attempt, not an independent statistical sample or evidence of model reliability. Local Ollama currency cost remains unpriced.
