# E-007 post-proposal continuation and bounded-retry analysis

**Date:** 17 November 2026  
**Scope:** forensic review of the raw artifacts for workflows [44149712970](https://github.com/mojtaba-arvin/agent-native/actions/runs/44149712970) and [44189163401](https://github.com/mojtaba-arvin/agent-native/actions/runs/44189163401).  
**Decision:** no further wall-time, context, or token-budget increase for this Qwen3 task until the interaction protocol is redesigned and deterministically tested.

## 1. The 1,800-second run: proposal accepted, no validation request returned

**Artifact:** [14360782135](https://github.com/mojtaba-arvin/agent-native/actions/runs/44149712970/artifacts/14360782135)  
**Source revision:** `cb640a2db1fe35ff9f5065abff8399ed5a3422ba`

| Measure | Observation |
|---|---:|
| Wall duration | 1,800.116 s / 1,800 s |
| Input / output tokens | 65,692 / 3,171 |
| Tool calls | 15 |
| Existing operations inspected | 6 / 6 |
| Proposal attempts | 3 |
| Gateway-accepted proposals | 1 |
| Validation / plan / apply | 0 / 0 / 0 |
| Candidate wrapper | Not emitted |
| Currency inference cost | Unpriced local Ollama; unknown |

The first proposal was rejected with `INSPECTION_INCOMPLETE`; the second with `IR_PRESERVATION_MISMATCH` for `submit_rebuild`. The third was accepted. Its IR contained `ir_version=1`, the unchanged service and types, all six existing operations in their original order, and exactly the requested seventh operation with array-shaped input. An independent canonical SHA-256 calculation matched change-set ID `0f3c1ffab2fd1aa73e311513879ff305858cc8b1bce3942462450f0d5f4a4def`.

### What happened after acceptance

The Gateway response to the accepted proposal included `next_actions: ["service.validate with the change_set_id"]`. The system prompt also explicitly required `service.validate` as the immediate next tool call using that exact ID. The adapter appended the successful tool result to the conversation and issued the next Ollama request.

The Ollama daemon log shows that request had 7,734 prompt tokens with an 8,192-token context. At the runner's 1,800-second deadline, prompt evaluation had progressed only to approximately 4,860 tokens. The request was cancelled at the wall boundary and Ollama returned an HTTP 500 symptom. The retained provider-response file has no completed response for this post-acceptance turn; it therefore contains no last generated assistant tokens or validate tool call. The daemon log indicates prompt prefill had not completed, so there is no evidence that the model began decoding a `service.validate` call.

**Conclusion:** the evidence supports deadline-limited prompt prefill/continuation after a valid proposal. It does not show that the model refused, forgot, or misunderstood the validate instruction. It also does not prove that it would have called validate if given more time.

## 2. The 3,000-second/context-16,384 run: repeated malformed tool arguments

**Artifact:** [14376970288](https://github.com/mojtaba-arvin/agent-native/actions/runs/44189163401/artifacts/14376970288)  
**Workflow:** [44189163401](https://github.com/mojtaba-arvin/agent-native/actions/runs/44189163401)  
**Source revision:** `32ede5a7f63584784143851b7c4f9c5a72d30084`

| Measure | Observation |
|---|---:|
| Wall duration | 267.785 s / 3,000 s |
| Context | 16,384 |
| Input / output tokens | 5,418 / 78 |
| Tool calls | 2 |
| Inspections completed | 0 |
| Proposals / validation / plan | 0 / 0 / 0 |
| Failure | `repeated_invalid_tool_call` |

The first provider response produced `service.inspect` with an empty `arguments: {}`. The Gateway returned `ARGUMENTS_REQUIRED`. The second provider response repeated the same tool and empty arguments; the runner terminated with `repeated_invalid_tool_call`. This occurred after about 268 seconds, far below the configured 3,000-second wall ceiling and without input/output budget exhaustion.

**Conclusion:** this is an agent/tool-schema adherence failure, not a timeout, provider transport failure, or resource-budget failure. The larger context and wall allowance did not resolve the interaction problem. Preserve it as a distinct failure mode.

## 3. Model-driven versus automatic validation

For the current Agent Native evaluation contract, validation remains **model-invoked and Gateway-enforced**:

- The model must explicitly request `service.validate` for the accepted proposal hash.
- The Gateway/adapter must reject `service.plan` unless that same hash has `result.valid=true`.
- The runner must not silently call validate on the model's behalf in this experiment, because that would demonstrate orchestrator-driven continuation, not autonomous agent tool selection.

The 1,800-second artifact does not justify changing this decision: the model never completed the post-acceptance prompt prefill, so it did not get a chance to choose the next tool. If a future experiment adds automatic validation as a control arm, it must be labelled separately and must not count as evidence that the model invoked validation.

## 4. Failure taxonomy correction

For workflow 44149712970, the raw record says `provider_transport_failure`, but the Ollama daemon log independently shows runner-deadline cancellation and a terminal HTTP 500 symptom. This should not be counted as an independent transport outage.

The evaluator now treats a provider transport/HTTP symptom at the configured wall ceiling as `timeout` plus `resource_budget_exceeded`, while preserving the raw failure string. A provider transport failure well before the wall ceiling remains `transport_error`. The historical artifact is immutable; only the derived classification and interpretation are corrected.

## 5. Hard stop and next work

The 1,800-second and 3,000-second attempts are the bounded resource experiments. **Do not dispatch another Qwen3 run with a larger time, context, or token budget.** Before any further real-model attempt:

1. Reduce repeated conversation-prefix growth and avoid unnecessary schema/tool turns without removing evidence needed by the scorer.
2. Add adversarial provider-double tests for missing required tool arguments, identical repeated invalid calls, and valid repair after a structured diagnostic.
3. Test that the model-visible tool schema and the prompt's required first action agree for the upfront disclosure arm.
4. Consider a smaller isolated continuation experiment to measure Gateway validation independently, but label any runner-invoked validation as orchestration evidence, not model behavior.
5. Only then preregister a redesigned, bounded experiment with the existing semantic, preservation, and no-apply gates unchanged.

These are one-task, fixed-seed observations. They do not establish model reliability, statistical significance, or model superiority.


## 6. Follow-up infrastructure analysis (18 November 2026)

The original forensic conclusion that prompt prefill was incomplete remains correct, but the throughput interpretation is refined by the full Ollama logs. Both the 1,800s and 3,000s workflows used CPU-only Ollama backends with two model threads; neither loaded a GPU backend or GPU model buffer. The first host was AMD EPYC 9V74 / ggml-cpu-zen4, and the second AMD EPYC 7763 / ggml-cpu-haswell.

For the final 7,734-token prompt in the 1,800s run, Ollama logged prefill at 20.09, 19.05, 18.05, and 17.04 tokens/second. The request began with about 240 seconds left in the global run budget, and 764 prompt tokens were reusable from the cache. At cancellation, 4,860 total prompt tokens (4,096 newly evaluated tokens) had been processed. The preceding request's 2.38 tokens/second was generation/decode throughput, not prefill. The 1,800 seconds covered the entire agent run, not the final prompt alone.

This confirms CPU-only execution as a threat to validity, but does not justify the proposed 2.7 tok/s prefill estimate. A rough extrapolation from the last prefill checkpoint suggests about 169 seconds would have been needed for the remaining uncached prompt under the same rate; that is not a measured completion time. No assistant decoding began and no validate tool call was emitted before the global deadline.

The full analysis and implementation response are recorded in [the CPU/prefill baseline report](2026-11-18-ollama-cpu-prefill-baseline.md). The adapter now compacts repeated assistant/tool history into an exact Gateway-state ledger while preserving raw traces. Deterministic verification is pending; no new full-task Qwen3 run is authorized yet.
