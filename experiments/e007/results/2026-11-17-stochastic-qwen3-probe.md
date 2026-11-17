# E-007 stochastic Qwen3 post-fix probe — 17 November 2026

**Classification:** one exploratory real-model observation; not accepted; not statistical evidence  
**Workflow:** [44105440141](https://github.com/mojtaba-arvin/agent-native/actions/runs/44105440141)  
**Artifact:** [14337879630](https://github.com/mojtaba-arvin/agent-native/actions/runs/44105440141/artifacts/14337879630)  
**Source revision:** `cc62169a7932d9d0d3ebe775fe2bd9319fc3bbf9`  
**Model:** `qwen3:8b` via Ollama  
**Configuration:** temperature `0.7`, seed `20261117`, top-p `1.0`, context `8192`, maximum prediction `2048`, per-run input/output/tool/wall caps `48,000 / 6,000 / 20 / 900s`.

## Outcome

| Measure | Result |
|---|---:|
| Accepted | No |
| Eligible for acceptance | No — provider/runner transport ended at wall-time ceiling |
| Duration | 900,030.535 ms |
| Input / output tokens | 44,377 / 1,399 |
| Tool calls | 12 |
| Candidate artifact | Not present in this run (candidate-preservation change was committed later) |
| Validation / plan | Neither reached |
| Currency inference cost | Unpriced local Ollama; not zero |

The workflow ended non-zero. The Ollama log shows the last `/api/chat` request returned HTTP 500 after approximately 50.83 seconds and the inference server logged cancellation of the active task at the 900-second boundary. The E-007 runner recorded `provider_transport_failure`; this should not be interpreted as a semantic validation rejection. Usage telemetry was complete, but the run remained ineligible for acceptance.

## What the model did

1. It first attempted to call `service.inspect` with an invalid operation name and issued one malformed `interface.describe` request with an extra field. It then retrieved the correct `service.inspect` schema and successfully inspected the service-level Catalog contract.
2. It attempted to inspect the requested new operation before it existed; the Gateway correctly returned `OPERATION_NOT_FOUND`.
3. It sent a proposal **before inspecting the six existing operations**. The Gateway rejected it with `INSPECTION_INCOMPLETE` and enumerated all six required inspections.
4. The model then inspected all six existing operations. This shows that the Gateway's feedback caused the required inspection sequence to be completed.
5. The proposal request itself contained a complete top-level shape: `ir_version=1`, `service`, `types`, and seven operations (six existing plus the requested new operation). All operation inputs were arrays of declarations; the new operation's `input` was the correct `[{name, source, type}]` form.
6. However, the proposal had already been rejected at step 3. The trace contains **no second proposal** after the six inspections, no `service.validate`, and no `service.plan`. The model had not demonstrated a successful corrected proposal by the time the wall budget expired.

## Preservation defects in the attempted full IR

Although its outer shape was complete, the model rewrote existing operation contracts rather than copying them exactly:

| Existing operation | Material change in submitted IR |
|---|---|
| `cancel_job` | Changed capability from `jobs.cancel` to `jobs.read`, effect from `queue.cancel` to `repository.read`, removed `ServiceUnavailable`, and added an `id.non_empty` rule that was not in the inspected contract |
| `create_item` | Replaced the two inspected declarations (`idempotency_key` header and `name` body) with a single `item: Item` body declaration; also removed the `Conflict` error and changed validation |
| `get_item` | Added `id.non_empty` despite the inspected validation list being empty |
| `get_job` | Removed `ServiceUnavailable` and added an `id.non_empty` rule absent from the inspected contract |
| `submit_rebuild` | Replaced the `idempotency_key` header with an `items: Item` body input; changed `jobs.submit` capability to `items.rebuild`, `queue.submit` effect to `repository.write`, removed several declared errors, and changed validation |

The existing operation contracts are grounded in the six successful `service.inspect` responses retained in the artifact. These are preservation failures, not an IR top-level-shape failure. The new operation itself had the expected input declaration array.

## Interpretation

- The non-zero temperature/seed produced a materially different path from the temperature-zero cohort. The model formed a full-top-level IR with the required version and all seven operation slots, unlike the earlier deterministic cohort.
- That apparent improvement did **not** meet the task contract: the model mutated multiple pre-existing operation definitions and submitted the full IR before satisfying the inspect-all gate.
- The Gateway's `INSPECTION_INCOMPLETE` response successfully induced all six inspections, but the model did not submit the corrected proposal before the time cap.
- This one run is an exploratory observation only. It cannot estimate success probability, prove model improvement, or support a model comparison. Ollama still reused prompt/KV prefix state; that does not remove sampling variability at temperature 0.7 and does not establish response-cache replay.
- No E-009 validation rejection occurred in this probe: the incomplete proposal was blocked at the Gateway before validation. The terminal failure was provider/runner transport at the wall-time boundary.

## Design implications

1. Retain the inspect-all gate as a server-side precondition. It is doing useful work.
2. Add a more explicit instruction and deterministic trusted check that existing operation declarations must be copied byte-for-byte/structure-for-structure from inspection results. The E-007 candidate scorer already checks preservation, but the server-side proposal/validation API may also benefit from an explicit preservation policy in future design.
3. Do not relax server validation to accommodate semantically plausible rewrites. These fields carry authority and behavior semantics; changing capability/effects/errors/inputs is not a harmless formatting change.
4. Improve budget observability so a provider HTTP 500 near the configured wall ceiling is classified with both raw provider transport cause and the exhausted wall-time budget. The subsequent taxonomy change records this combination.

## Evidence boundary

The run does not pass any of the three E-007 scorers, does not validate a proposal, does not produce a plan, and does not prove the complete-IR correction works end-to-end. It does show that under a different sampling configuration the model can produce the complete top-level IR shape, but cannot yet preserve the inspected contracts or complete the corrected proposal cycle within the current budget.
