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

**Limit:** this is a single deterministic debugging attempt, not an independent statistical sample or evidence of model reliability. Local Ollama currency cost remains unpriced. The bounded follow-up has been dispatched as [workflow 44149712970](https://github.com/mojtaba-arvin/agent-native/actions/runs/44149712970); its result remains pending raw-artifact review.


## D-012 — A Gateway-accepted proposal is distinct from a completed agent task

**Evidence:** E-007 run [44149712970](https://github.com/mojtaba-arvin/agent-native/actions/runs/44149712970), artifact [14360782135](https://github.com/mojtaba-arvin/agent-native/actions/runs/44149712970/artifacts/14360782135), source revision `cb640a2db1fe35ff9f5065abff8399ed5a3422ba). The fixed-seed Qwen3 run inspected all six existing operations. Proposal attempt one was rejected with `INSPECTION_INCOMPLETE`; attempt two was rejected with `IR_PRESERVATION_MISMATCH` for `submit_rebuild`; attempt three was accepted by the Gateway. The accepted IR included `ir_version=1`, the service and types, the six exact existing operations in original order, and the requested seventh operation with array-shaped input. Independent canonical SHA-256 recomputation matched the Gateway's change-set ID.

The run then reached its 1,800-second global wall ceiling while Ollama was still prefilling the next assistant prompt; assistant decoding had not begun. The Ollama daemon log shows the active request cancelled at the boundary and an HTTP 500 symptom; no OOM evidence or earlier independent outage was observed. No `service.validate` or `service.plan` call occurred.

**Decision:** report this as one deterministic observation of successful proposal construction and Gateway acceptance, not a successful E-007 task. Do not conflate proposal acceptance with semantic validation, plan safety, or the full lifecycle.

## D-013 — Score trace-observed proposal contracts separately from lifecycle completion

The earlier candidate-contract scorer returned zero when no final candidate JSON wrapper existed, even if the raw trace contained a Gateway-accepted proposal whose exact IR and hash could be verified. This collapsed two different facts: a correct proposal payload and a completed validate/plan lifecycle.

**Decision:** when the final wrapper is absent, the scorer may evaluate the last Gateway-accepted proposal directly from the raw trace for the candidate-contract scorer only. The proposal hash, full IR version/shape, exact existing-operation preservation, service/types preservation, and exact requested operation must all match. The proposal-lifecycle scorer still requires the same hash to pass semantic validation and planning; the behavioral-safety scorer still requires a safe non-mutating/non-deploying plan, complete inspection, and no apply. A regression test verifies that proposal-only success cannot produce overall acceptance.

**Failure taxonomy refinement:** when `provider_transport_failure` occurs at the configured wall ceiling, retain `transport_error`, `timeout`, and `resource_budget_exceeded`, and additionally mark `wall_budget_terminal_transport`. This is a temporal correlation marker, not proof of an independent provider outage or OOM. The raw Ollama daemon log remains necessary to distinguish runner cancellation from a spontaneous transport failure.


## D-014 — Post-proposal continuation is bounded by context-prefill and wall time

**Evidence:** expanded-budget Qwen3 run [44149712970](https://github.com/mojtaba-arvin/agent-native/actions/runs/44149712970), artifact [14360782135](https://github.com/mojtaba-arvin/agent-native/actions/runs/44149712970/artifacts/14360782135). The model's third proposal was accepted, after which the adapter issued the next Ollama request. The daemon log shows the next prompt had 7,734 tokens under the configured 8,192-token context. At the 1,800-second runner deadline, prompt evaluation had progressed to 4,860 tokens and the active request was cancelled. The prior request log shows generation around 2.38 tokens/second. There is no OOM evidence; the request was terminated at the configured wall boundary.

**Interpretation:** the trace supports a bounded continuation/prompt-prefill problem, not a claim that the Gateway or validation rejected the proposal. The run never reached the model response that would have called `service.validate`.

**Decision:** one follow-up keeps model, task, temperature, seed, Gateway preservation, scorer thresholds, same-hash validation gate and no-apply policy fixed; it makes the upfront action order explicit, tells the model not to call schema discovery when all schemas are already exposed, increases context to 16,384, input allowance to 120,000, and wall ceiling to 3,000 seconds. This is an exploratory resource/prompt adjustment, not a statistical comparison. Do not keep increasing resources if this bounded attempt fails; inspect its trace and reassess the interaction design.


## D-019 — The 1,800-second post-proposal stop was prompt-prefill timeout, not a missed validate decision

**Evidence:** workflow [44149712970](https://github.com/mojtaba-arvin/agent-native/actions/runs/44149712970), artifact [14360782135](https://github.com/mojtaba-arvin/agent-native/actions/runs/44149712970/artifacts/14360782135), and the retained Ollama daemon log. The accepted proposal response contained `next_actions: ["service.validate with the change_set_id"]`; the system prompt independently required an immediate `service.validate` call with that exact ID. The adapter appended the tool result and requested the next model turn. The next prompt contained 7,734 tokens under an 8,192-token context; at the 1,800-second deadline, daemon prompt evaluation had advanced only to about 4,860 tokens. No completed provider response or validate tool call was recorded.

**Decision:** retain model-invoked validation for the current Agent Native evaluation. Do not switch to automatic validation based on this trace: the model did not complete prompt prefill and therefore never had a recorded opportunity to select its next tool. A future runner-invoked validation control must be labelled orchestration-driven and cannot count as evidence of autonomous model tool selection.

## D-020 — Stop Qwen3 resource escalation after the bounded 3,000-second attempt

**Evidence:** workflow [44189163401](https://github.com/mojtaba-arvin/agent-native/actions/runs/44189163401), artifact [14376970288](https://github.com/mojtaba-arvin/agent-native/actions/runs/44189163401/artifacts/14376970288), source SHA `32ede5a7f63584784143851b7c4f9c5a72d30084`. The run used context 16,384, a 120,000 input-token ceiling, and a 3,000-second wall ceiling, but stopped after 267.785 seconds and 5,418 input / 78 output tokens. Qwen3 called `service.inspect` twice with empty argument objects; both were rejected with `ARGUMENTS_REQUIRED`, and the runner terminated the repeated identical invalid call. No inspection, proposal, validation, or plan succeeded.

**Decision:** no further increase to wall time, context, or token budgets for this Qwen3 task. The next step is interaction-protocol and tool-schema debugging, with provider-double/adversarial tests before any new real-model attempt. This failure is an eligible agent/tool-contract failure, not a resource-budget stop.

## D-021 — A provider symptom at a proven wall-deadline cancellation is not an independent transport failure

**Evidence:** workflow [44149712970](https://github.com/mojtaba-arvin/agent-native/actions/runs/44149712970) ended at 1,800.116 seconds; the Ollama daemon log shows the active request cancelled at the runner wall boundary and an HTTP 500 symptom. No independent outage or OOM evidence was observed.

**Decision:** preserve the raw historical failure code, but classify this boundary-correlated event as `timeout` and `resource_budget_exceeded`, not `transport_error`. A transport failure well before the wall deadline remains `transport_error`. The evaluator regression tests both cases. Historical artifact contents are not rewritten.


## D-022 — CPU-only inference and prefill/decode metrics must be separated

**Evidence:** raw Ollama daemon logs retained in artifacts [14360782135](https://github.com/mojtaba-arvin/agent-native/actions/runs/44149712970/artifacts/14360782135) and [14376970288](https://github.com/mojtaba-arvin/agent-native/actions/runs/44189163401); detailed analysis in [the CPU/prefill baseline](../experiments/e007/results/2026-11-18-ollama-cpu-prefill-baseline.md).

Both real-model workflows loaded a CPU backend only, with CPU model buffers and two llama.cpp threads on four visible logical CPUs. The first host reported AMD EPYC 9V74 / ggml-cpu-zen4; the second AMD EPYC 7763 / ggml-cpu-haswell. No GPU backend or GPU model buffer was loaded.

For the 1,800-second run, the final request prompt was 7,734 tokens in an 8,192-token context, with 764 cached prefix tokens. The global run budget had only about 240 seconds remaining when that request began. Ollama logged prefill at 20.09, 19.05, 18.05, and 17.04 tokens/second across successive 1,024-token checkpoints, reaching 4,860 total prompt tokens before cancellation. The preceding request's 2.38 tokens/second was decode throughput (863 generated tokens / 362.45 seconds), not prefill. The run-level 1,800 seconds must not be divided into the final prompt token count to estimate prefill throughput.

**Decision:** classify CPU-only inference and the global wall ceiling as an explicit threat to validity. The 1,800-second artifact demonstrates an accepted proposal followed by incomplete prompt prefill; it does not show that the model ignored or refused the validate instruction. The 3,000-second artifact remains a separate repeated-empty-tool-arguments failure. No model capability conclusion is drawn from either run.

The diagnostic label for the first artifact is prefill_not_completed_at_wall_deadline, derived only by correlating the raw run with Ollama daemon telemetry. Do not infer this phase label from provider_transport_failure alone; the runner does not currently receive structured prompt-prefill progress. The historical run.json and provider response files remain immutable.

**Implementation decision:** compact repeated assistant/tool history after each tool batch into a verified Gateway-state ledger containing the exact service inspection, exact inspected operation declarations, tool sequence, and compact recent outcomes/diagnostics. Preserve raw provider responses and append-only tool traces. This reduces prompt replay without relaxing IR, preservation, validation, planning, or no-apply gates.

**Decision threshold:** after the redesigned prompt is validated, if three consecutive full-task runs each produce a Gateway-accepted proposal, complete prefill, but still fail to invoke model-driven service.validate, trigger an architecture review. A runner-invoked validation control may then be evaluated as a separately labelled orchestration arm; it must not count as autonomous model behavior. Earlier runs with incomplete prefill or no accepted proposal do not satisfy this trigger's preconditions.

**Open measurement:** a fixed approximately 1,000-token isolated prefill benchmark has not yet been run. The daemon checkpoints are preliminary host-specific observations, not a standalone benchmark. No further full-task Qwen3 budget increase is authorized before prompt-compaction CI, a short schema probe, and the bounded infrastructure baseline.

## D-023 — A schema probe must reproduce the full upfront session surface

**Evidence:** workflow [44193765741](https://github.com/mojtaba-arvin/agent-native/actions/runs/44193765741), artifact [14378248130](https://github.com/mojtaba-arvin/agent-native/actions/runs/44193765741/artifacts/14378248130). The short probe supplied only the generic agent.invoke envelope schema and omitted the Gateway session surface containing per-tool input schemas. It observed an empty nested arguments object, but the model was not given the same schema context as the production upfront arm.

**Decision:** invalidate the schema-adherence interpretation of that probe. The diagnostic must include the exact live Gateway session surface as a model message, matching local_agent.py. A regression test enforces this. Do not use the previous empty-arguments response as evidence of model incapability or of context-window failure.

## D-024 — Cache measurements must keep the model loaded and report provider cache telemetry

**Evidence:** workflow 44193765741 used keep_alive=0 for every repeated prefill request. Ollama unloads the model immediately with this setting, so the run measured cold requests and cannot establish warm KV-cache reuse. The historical lifecycle artifact's 764 cached prefix tokens remain a trace observation, not a causal diagnosis.

**Decision:** use keep_alive=10m, nested prompts with exact shared prefixes, exact warm repeats, and prompt_eval_cached_count. Missing cache telemetry remains unknown, not zero. Distinguish stable-prefix reuse from changed conversation suffixes.

## D-025 — Thread-count comparisons are bounded by process-visible CPU allocation

**Evidence:** workflow 44193765741 reported an AMD EPYC 7763 64-Core host model but lscpu exposed only four logical CPUs (0–3); Ollama selected two model threads. Host product-core count is not the job's CPU allocation.

**Decision:** compare requested 2 and 4 threads as the primary settings and include 16 only as an explicitly labelled oversubscription stress arm. Record process affinity and cgroup CPU quota/cpuset with every measurement. Never describe a 16-thread request as using 16 cores on a four-CPU runner.

## D-026 — Compacted prompt state is deterministic and persisted per model turn

**Evidence:** experiments/e009/local_agent.py constructs the Gateway-state ledger only from trusted Gateway inspection results, the local tool-call sequence, and compacted tool outcomes. No LLM summarization step is used.

**Decision:** persist the exact state snapshot supplied for every provider turn in prompt-states.jsonl, with a SHA-256 digest, prompt-message digest, and base-message digest. The provider-response record references the corresponding state and prompt hashes. The initial turn records the live session surface; subsequent turns record the deterministic Gateway-state ledger. This makes compaction reviewable without replacing the append-only raw tool trace. Regression tests cover deterministic state construction and per-turn persistence, including the diagnostic state after an invalid tool call; the integrated E-009 CI run [44195694000](https://github.com/mojtaba-arvin/agent-native/actions/runs/44195694000) passed 82 tests.

