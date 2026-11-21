# E-007 deterministic post-Gateway trial — input-budget exhaustion

**Classification:** one real-model observation; ineligible for agent acceptance under the corrected budget taxonomy; not statistical evidence  
**Workflow:** [44144939813](https://github.com/mojtaba-arvin/agent-native/actions/runs/44144939813)  
**Artifact:** [14357367813](https://github.com/mojtaba-arvin/agent-native/actions/runs/44144939813/artifacts/14357367813)  
**Source revision:** `f476e5a5ead74317da7c831c48460934b75bcf4e`  
**Run record:** `e009-20261117T181209Z-6bbde153`  
**Model:** `qwen3:8b` via Ollama

## Pinned configuration and outcome

| Measure | Result |
|---|---:|
| Temperature / seed / top-p | 0 / 42 / 1.0 |
| Context / max prediction | 8,192 / 2,048 |
| Input / output ceilings | 48,000 / 6,000 tokens |
| Wall ceiling | 1,200 seconds |
| Duration | 1,020.139 s |
| Input / output usage | 48,307 / 1,373 tokens |
| Input overrun | 307 tokens (0.64%) |
| Tool calls / provider responses | 11 / 12 |
| Existing operations inspected | 5 of 6 |
| Proposal attempts | 1; rejected with `INSPECTION_INCOMPLETE` |
| Candidate / validation / plan | None / not reached / not reached |
| Apply | Not called |
| Currency inference cost | Unpriced local Ollama; not zero |

The runner stopped on `input_token_budget_exceeded`. The model step ended at 1,020 seconds, below the 1,200-second wall ceiling. This was not a wall timeout.

## Trace reconstruction

1. The model first issued an invalid `service.inspect` request, then retrieved the correct schema with `interface.describe`.
2. It inspected the Catalog service successfully.
3. It attempted to inspect the requested new operation before it existed; the Gateway returned `OPERATION_NOT_FOUND`.
4. It retrieved the `service.propose` schema and proposed before inspecting the existing operations. The Gateway returned `INSPECTION_INCOMPLETE` and listed all six required operations.
5. The model inspected five existing operations successfully: `cancel_job`, `create_item`, `get_item`, `get_item_by_name`, and `get_job`.
6. The input-token counter reached 48,307 after the twelfth provider response. The sixth operation (`submit_rebuild`) had not been inspected; the local adapter terminated before another proposal could be submitted.

The raw trace has 11 tool calls and three tool errors: two `OPERATION_NOT_FOUND` responses and one `INSPECTION_INCOMPLETE`. No `AN021`, validation, plan, candidate, or apply event appears in the trace.

## Provider and resource diagnosis

All 12 Ollama provider responses have complete token telemetry and completed normally. The daemon log ends with HTTP 200 for the final `/api/chat` request. The retained log contains no observed OOM, killed-process, cancellation, HTTP 500, or provider transport-error marker. The run lasted 1,020 seconds, below its 1,200-second wall limit.

**Diagnosis:** the observed terminal condition is the configured cumulative input-token ceiling. The artifact does not support classifying this as a provider transport failure, wall timeout, or observed memory exhaustion.

## Runner-classification correction

The original immutable `result.json` marked the run `eligible_for_acceptance=true` even though the failure was `input_token_budget_exceeded`. This was a runner eligibility bug: the taxonomy correctly named `resource_budget_exceeded`, but `_eligible()` did not exclude per-run token/output/tool/wall budget stops.

The runner now treats per-run budget exhaustion as ineligible for the acceptance denominator, while retaining the raw failure and resource-budget category. A deterministic regression test covers input, output, tool-call, wall-time, model-turn, candidate-size, and aggregate pre-run budget exhaustion. The original artifact is not rewritten; the eligibility correction is recorded as a later audit finding.

## Interpretation and next bounded experiment

This run does not verify full IR generation, exact base preservation, AN021 repair, validation, or planning: it stopped before all six existing operations were inspected and before a second proposal. It shows that the previous 48,000-token ceiling was insufficient for this prompt/Gateway path. The 1,200-second wall cap was not reached.

A single follow-up deterministic probe is justified with a larger, explicitly pinned resource envelope: 96,000 cumulative input tokens and 1,800 seconds wall time, while keeping Qwen3, temperature 0, seed 42, top-p, context, output ceiling, tool policy, scorers, and Gateway semantics unchanged. This is a bounded resource-envelope adjustment based on the observed trace, not a relaxation of IR/preservation/validation requirements and not statistical evidence. Local currency cost remains unpriced.
