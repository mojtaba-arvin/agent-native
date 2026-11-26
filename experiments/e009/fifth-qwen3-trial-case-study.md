# E-009 fifth Qwen3 trial — a repeatable IR and repair-loop failure

**Classification:** one real-model failure case; useful diagnostic evidence, not a statistical result  
**Workflow:** [44081733833](https://github.com/mojtaba-arvin/agent-native/actions/runs/44081733833)  
**Artifact:** [14328213511](https://github.com/mojtaba-arvin/agent-native/actions/runs/44081733833/artifacts/14328213511)  
**Run record:** `e009-20261117T121839Z-c3c98188`  
**Source revision:** `71a957d1949d4d8bbbeb4267ccaaa0589c8a77ba`  
**Model:** `qwen3:8b` via Ollama

## Observed result

| Measure | Observation |
|---|---:|
| Status | Failed |
| Duration | 765,073 ms (12m 45s) |
| Input / output tokens | 33,714 / 1,314 |
| Tool calls | 12 |
| Proposal attempts | 3 total: first rejected, second accepted by proposal endpoint, third repeated |
| Existing operations inspected | 6 of 6 before the accepted proposal |
| Validation | `ok=true`, but `result.valid=false`; diagnostic `AN021` |
| Plan / apply | Neither reached |
| Candidate artifact | None; runner terminated on repeated successful proposal |
| Currency inference cost | Unpriced local Ollama; not zero |

## Trace reconstruction

1. The agent successfully inspected the Catalog service and received its current revision and six existing operation names.
2. It tried to inspect the requested new operation before it existed. The Gateway returned `OPERATION_NOT_FOUND`.
3. It submitted a proposal before inspecting the six existing operations. The Gateway rejected this request with `INSPECTION_INCOMPLETE` and named all six missing inspections.
4. The agent inspected all six existing operations successfully.
5. It resubmitted the proposal. The proposal endpoint accepted it and returned change-set ID `f3cc8938599080bd0489694208562655ca92cc5547b9ed26f32543023b73a8fb`.
6. The accepted proposal IR was structurally incomplete: its top-level keys were only `types` and `operations`; it omitted `ir_version` and `service`; it contained only the new operation rather than the complete existing service snapshot; and the operation's `input` was an object map `{"name":"String"}`, not the required array of declarations with `name`, `source`, and `type`.
7. `service.validate` returned an outer `ok=true` tool envelope, but `result.valid=false` with `AN021` ("unsupported or malformed IR version or top-level shape").
8. The model then submitted the same malformed proposal again. The trace shows the same change-set hash and unchanged IR. The local runner terminated with `multiple_successful_proposals`; no plan or apply occurred.

The raw artifact therefore establishes a sequence of distinct defects, not one generic "bad JSON" event: incomplete inspection on the first proposal, an invalid full-snapshot schema on the accepted proposal, a semantic validation failure hidden by the outer successful tool envelope, and an identical proposal repeated after that failure.

## Infrastructure exclusion

The retained provider diagnostics show 12 completed Ollama responses with usage telemetry. The daemon log ends with HTTP 200 for the final `/api/chat` request and contains no observed OOM, killed-process, cancellation, or provider-error marker. The run's failure is therefore classified as an agent/repair-loop failure, not a provider transport failure, timeout, or observed resource exhaustion. This conclusion is limited to the retained logs; it does not establish the absence of every possible host-level resource constraint.

## Why this failure is useful

It exposed four contract boundaries that need separate checks:

- **Inspection completeness:** proposing against an unseen base must be rejected before the proposal is stored.
- **IR shape:** a proposal accepted by the proposal endpoint is not necessarily a valid IR snapshot. The canonical IR requires `ir_version`, `service`, `types`, and `operations`; each operation's inputs are typed declaration arrays.
- **Semantic validation:** `ok=true` means the tool invocation was processed. Only `result.valid=true` means the proposal passed validation.
- **Repair-loop integrity:** repeating the same proposal hash after a failed validation is not progress and must not be mistaken for a successful correction.

## Corrective work and verification boundary

The following controls were added in later revisions:

1. The canonical full-snapshot IR contract and E-005 tool schema now expose the required top-level fields and typed input-array shape.
2. `AN021` now carries actionable repair guidance.
3. The E-009 local adapter requires `result.valid is True` for the current proposal hash before allowing `service.plan`.
4. Proposal attempts are bounded, and repeated proposals are retained/classified rather than silently accepted as repair progress.
5. The E-009 Gateway now requires all existing operations to be inspected and enforces exact preservation of the inspected service, types, and existing operation declarations before forwarding a same-revision proposal.
6. Parseable final candidate JSON is retained before trusted verification so a rejected candidate remains inspectable.

These controls have deterministic test coverage. They must not be described as successful Qwen3 behavior until a post-fix real-model artifact demonstrates a complete proposal → valid validation → safe matching plan sequence. The later three-run E-007 cohort and stochastic probe are separate observations and must not be merged with this fifth-trial record.

## Research interpretation

This is one bounded, fully traced failure case. It supports a causal account of the observed failure path and motivates the subsequent contract, Gateway, and runner changes. It does **not** support a model-wide failure rate, a statistical reliability estimate, or a claim that the later fixes work with a real model. Preserve the failure as counter-evidence; do not rewrite it as a successful trial.
