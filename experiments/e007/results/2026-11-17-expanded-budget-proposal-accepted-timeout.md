# E-007 deterministic expanded-budget Qwen3 run — proposal accepted, lifecycle timed out

**Classification:** one deterministic, single-run observation; partial proposal-contract success; no accepted E-007 task  
**Workflow:** [44149712970](https://github.com/mojtaba-arvin/agent-native/actions/runs/44149712970)  
**Artifact:** [14360782135](https://github.com/mojtaba-arvin/agent-native/actions/runs/44149712970/artifacts/14360782135)  
**Source revision:** `cb640a2db1fe35ff9f5065abff8399ed5a3422ba`  
**Model/configuration:** `qwen3:8b`, Ollama, temperature `0`, seed `42`, top-p `1`, context `8192`, prediction cap `2048`; one repetition; input/output/tool/wall ceilings `96,000 / 6,000 / 20 / 1,800s`.

## Run summary

| Measure | Result |
|---|---:|
| Duration | 1,800.116 s |
| Input / output tokens | 65,692 / 3,171 |
| Tool calls | 15 |
| Existing operations inspected | 6 / 6 |
| Proposal attempts | 3 |
| Gateway-accepted proposals | 1 |
| Validation / plan | Neither reached |
| Apply | Never called |
| Final candidate wrapper | Not emitted; `candidate_path=null` |
| Currency inference cost | Unpriced local Ollama; unknown, not zero |
| E-007 accepted | No |

The workflow's original summary marked all three scorers false because the run did not emit the final candidate JSON wrapper and did not reach validation or plan. A separate forensic audit of the retained raw tool trace was therefore necessary; the aggregate scorer result alone concealed a meaningful intermediate success.

## Exact proposal sequence

| Trace sequence | Tool result | Evidence |
|---:|---|---|
| 1 | `service.propose` rejected: `INSPECTION_INCOMPLETE` | The model submitted a complete-shaped seven-operation IR before inspecting the six existing operations. The Gateway correctly blocked it. |
| 2 | `service.propose` rejected: `IR_PRESERVATION_MISMATCH` | After inspecting all six operations, the model still changed the existing `submit_rebuild` contract. The Gateway identified the exact preservation violation. |
| 3 | `service.propose` accepted | The third proposal preserved all six inspected operation objects in original order, preserved service and types, included `ir_version=1`, and appended exactly the requested seventh operation with an array input declaration. The Gateway returned change-set hash `0f3c1ffab2fd1aa73e311513879ff305858cc8b1bce3942462450f0d5f4a4def`. An independent canonical SHA-256 recomputation matches the Gateway hash. |

The raw trace independently verifies all of the following for the accepted third proposal:

- all six existing operations were successfully inspected;
- `ir_version=1` was present;
- service identity and types matched the inspected base;
- the six existing operation JSON objects were preserved exactly and in order;
- the new operation exactly matched the task contract, including `input: [{name, source, type}]`;
- the Gateway accepted the proposal and returned the matching change-set hash.

**No `AN021` occurred in this run.** The Gateway preservation gate rejected the second proposal before validation, and the third proposal passed the Gateway proposal boundary. This is direct evidence that the full-IR shape and exact-preservation corrections worked for one deterministic attempt.

## Why the run still failed

After the successful third proposal, the adapter requested another model response so the agent could continue with `service.validate`. The provider-response log ends after the successful proposal tool call; the following Ollama request was cancelled at the 1,800-second runner wall deadline. Ollama's daemon log records the active request being cancelled at the boundary and an HTTP 500 response at that time. The final request was still generating (the daemon reports roughly 2.38 generated tokens/second before cancellation).

There is no OOM marker in the daemon log or evidence of an independently occurring Ollama outage before the wall deadline. The observed terminal HTTP/transport symptom is therefore correlated with runner-initiated wall-budget cancellation. Preserve the raw `provider_transport_failure` code, but classify it separately as a wall-budget-terminal transport symptom; do not call it an autonomous provider outage or model-semantic rejection.

The run did not call `service.validate`, `service.plan`, or `service.apply`. The proposal success does not prove validation semantics, plan safety, or the complete propose → validate → plan loop.

## Scoring interpretation and runner correction

The previous `candidate_contract` scorer required a final candidate wrapper. That made it report zero even when the trace contained a Gateway-accepted proposal with a verifiable full IR. The scorer now falls back to the last Gateway-accepted proposal retained in the raw trace when no final wrapper exists. This can pass only the contract scorer; the lifecycle scorer still requires the same hash to be validated and planned, and the safety scorer still requires a safe plan and no apply. A regression test explicitly verifies that an accepted proposal without validation/plan does **not** become an accepted task.

This is a scoring-granularity correction, not a change to the E-007 acceptance criteria. The raw workflow artifact remains immutable and its original scores are not retroactively rewritten.

## Evidence boundary

**Established:** in one fixed-seed Qwen3 run, after two bounded repair attempts, the Gateway accepted a complete, exact-preserving proposal and no AN021 occurred. The Gateway's inspect-all and exact-preservation gates produced actionable feedback that the model eventually followed.

**Not established:** successful semantic validation, safe planning, task acceptance, reliable completion within the current wall budget, stochastic robustness, statistical reliability, or model superiority. This is one deterministic observation, not an independent sample or a statistical cohort.
