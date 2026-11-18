# E-007 follow-up — proposal representation and base-disclosure factorial experiment

**Status:** research protocol proposal; not implemented, not dispatched, and not evidence of an architecture decision.  
**Parent evidence:** E-009 full-snapshot proposal task; E-007 real-agent traces through 2026-11-18.  
**Decision question:** Is the current agent failure dominated by the amount of base contract the agent must reproduce, by the full-snapshot proposal representation, or by their interaction?

## 1. Why this experiment is necessary

The E-009 task currently requires the agent to inspect a service, inspect every existing operation, reconstruct the entire canonical IR snapshot, append one operation, propose it, validate it, and plan it. The Gateway independently verifies exact preservation of the inspected base.

The real-model history has exposed several distinct failure modes:

- Earlier deterministic trials omitted required top-level IR fields and existing operations.
- A stochastic trial produced a full-shaped IR but rewrote five existing operations.
- A later deterministic trial reached a Gateway-accepted, exact-preserving proposal after two rejected attempts, but exhausted its wall budget before validation and planning.
- The latest retry is testing whether the corrected task-path runner and unchanged bounded model settings can complete the existing full-snapshot flow.

These observations establish that the current task is difficult for the tested Qwen3 configuration. They do **not** establish why. In particular, they do not prove that full snapshots are inherently inferior, that the model is incapable, or that a delta interface is safer. The next experiment should distinguish these explanations rather than immediately changing the core contract.

## 2. Competing hypotheses

- **H1 — Snapshot reconstruction burden:** reproducing unchanged declarations consumes substantial context and creates avoidable preservation errors.
- **H2 — Representation mismatch:** a constrained change-intent representation is easier for agents to author correctly than a complete service snapshot.
- **H3 — Inspection burden:** requiring operation-by-operation inspection is a material source of tool calls, latency, and context growth.
- **H4 — Safety trade-off:** server-side materialization of a constrained delta can preserve the same or stronger integrity guarantees, but only if the base revision, allowed mutation set, and canonical resulting IR are enforced by trusted code.
- **H0 — No material improvement:** after controlling the task and runtime, a delta surface does not materially improve accepted-task rate or total cost per accepted task.

All remain open.

## 3. Experimental design: 2 × 2 factorial

Use the same service state, requested operation, model/runtime, task semantics, validator, planner, effect policy, and no-apply rule. Vary two factors only.

| Arm | Proposal representation | Base material exposed to the agent |
|---|---|---|
| A — current baseline | Complete canonical IR snapshot | Full contracts; operation-by-operation inspection required |
| B | Constrained typed delta | Full contracts; operation-by-operation inspection required |
| C | Complete canonical IR snapshot | Full canonical base IR supplied in the initial read-only inspection result; no redundant per-operation calls |
| D | Constrained typed delta | Minimal service revision and operation summaries; full unchanged contracts remain server-side |

This design distinguishes representation effects from base-inspection/material-exposure effects and reveals whether they interact. Arm C is important: it tests whether the current inspection sequence itself is expensive even when all data is available up front. Arm B tests the representation without removing the existing inspection requirement. Arm D tests the full proposed simplification.

Do not compare only A with D and attribute the entire difference to the delta format.

## 4. Candidate delta contract (hypothesis, not a committed API)

A minimal first delta should be intentionally narrow:

```json
{
  "service_id": "catalog",
  "base_revision": "<exact inspected revision>",
  "changes": [
    {
      "kind": "add_operation",
      "operation": {
        "name": "get_item_by_normalized_name",
        "method": "GET",
        "path": "/items/by-normalized-name/{name}",
        "input": [
          {"name": "name", "source": "path", "type": "String"}
        ],
        "output": "Item",
        "errors": ["InvalidInput", "NotFound", "Unauthorized"],
        "validation": ["name.non_empty"],
        "effects": ["repository.read"],
        "capability": "items.read"
      }
    }
  ]
}
```

The agent must not supply or choose the preserved base declarations in this arm. The trusted proposal handler must:

1. Resolve the service from trusted state, never from agent-provided base content.
2. Require an exact current `base_revision`; reject stale revisions.
3. Allow only explicitly supported operations (initially exactly one `add_operation`).
4. Reject duplicate names, replacement, deletion, reordering, implicit coercion, unknown fields, and unsupported change kinds.
5. Materialize the resulting complete canonical IR from the trusted base plus the validated delta.
6. Run the same canonical IR validator and effect/capability checks used by the snapshot arm.
7. Hash and store the immutable canonical result and its base revision; the returned change-set ID must bind both.
8. Feed the same immutable canonical result to `service.validate` and `service.plan`.
9. Keep apply disabled. No mutation occurs in any arm.

A delta is not permission to weaken validation or infer intent. It is a smaller, typed authoring surface whose trusted materializer must produce the same canonical artifact as the snapshot arm.

## 5. Fairness and controls

- Pin the exact source commit, task corpus revision, model digest/quantization, Ollama/runtime version, system prompt, task wording, temperature, seed, context, output ceiling, and provider template.
- Keep one model/runtime cohort initially. Do not claim model superiority from this study.
- Use matched seeds and paired task instances across arms; randomize arm order to reduce warm-cache/order effects.
- Record prompt and tool-schema hashes for every arm. The intentional interface difference is part of the treatment and must be visible in the manifest.
- Keep tool-call, input/output token, wall-time, and aggregate budgets equal across arms. Reserve worst-case budget before each run. Budget stops are reported separately and are not silently counted as agent failures.
- Use the same hidden acceptance checks, candidate-size limits, trusted validator, plan policy, and evaluator for all arms.
- Keep the evaluator/oracle outside the agent-visible workspace. The agent must never receive hidden assertions, scoring rules, or evaluator credentials.
- Retain every raw trace, candidate, provider usage record, failure class, and environment manifest. Do not overwrite historical artifacts.
- Never count repeated fixed-seed, temperature-zero runs as independent stochastic samples.

## 6. Primary and secondary outcomes

**Primary outcome:** completed task acceptance. A run is accepted only when the final canonical candidate is correct, exactly one successful proposal matches it, the same change-set hash is successfully validated, a subsequent plan for that same hash is valid with `will_mutate=false` and `will_deploy=false`, all required inspection/provenance checks pass for that arm, and no apply is attempted.

**Secondary outcomes:**

- input/output tokens and total inference time;
- tool calls, operation-inspection calls, invalid calls, repair attempts, and proposal attempts;
- time from first inspection to accepted proposal and from proposal to validated plan;
- candidate and canonical IR byte sizes;
- preservation/validation failure classes;
- wall-budget and token-budget stops;
- human interventions;
- total cost per accepted task (local Ollama remains explicitly unpriced unless a defensible compute-cost basis is measured).

Report acceptance numerator/denominator and uncertainty intervals. Separate infrastructure-invalid trials from eligible agent attempts. For an initial small feasibility probe, label findings exploratory; do not claim statistical significance.

## 7. Safety and adversarial tests required before any real-model delta run

The delta implementation must have deterministic tests proving rejection of:

- stale base revision;
- duplicate operation name;
- attempted replace/delete/reorder of existing operations;
- multiple changes when the arm permits exactly one;
- unknown change kinds and extra fields;
- malformed nested operation declarations;
- non-finite JSON, duplicate keys, oversized payloads, and invalid UTF-8 at the transport boundary;
- untrusted effects/capabilities;
- a delta whose materialized result differs from the canonical expected operation;
- validation or planning against a hash other than the immutable materialized result;
- repeated proposal, stale proposal, or proposal replay that could bypass current-base checks.

Property-based tests should generate valid base services and deltas, asserting that the only difference in the materialized IR is the explicitly added operation and that the base declarations remain byte-for-byte/canonical-JSON equivalent. Mutation testing should demonstrate that removing each guard causes at least one test to fail.

## 8. Decision rule

Do not replace the full-snapshot interface merely because one delta run succeeds. Keep the current interface as the control.

A delta arm becomes a serious candidate only if:
- its trusted materializer and adversarial tests pass;
- completed acceptance is not worse than the snapshot control within a pre-registered non-inferiority margin;
- it materially reduces total cost per accepted task or repair burden;
- it does not increase security, ambiguity, stale-base, or operational risk;
- the result replicates on more than one task before any broad architecture claim.

If the delta improves authoring cost but complicates the trusted runtime substantially, report that trade-off rather than hiding it. If the factorial results show inspection burden dominates, optimize the disclosure workflow separately. If neither factor helps, preserve the current design and investigate prompt/tool sequencing or model capability without silently relaxing correctness gates.

## 9. Execution sequence

1. Finish and inspect the currently running deterministic E-007 retry. Preserve its artifact and classify its result before changing the task or interface.
2. Implement the delta arm behind an explicit experimental feature flag on a research branch; do not alter the default snapshot behavior.
3. Add the four arm manifests, trusted evaluator assertions, and deterministic/adversarial tests.
4. Run protocol and kernel CI first. Do not spend model tokens until all local tests pass.
5. Calibrate a single small matched pilot. If resource reservations do not fit, do not dispatch.
6. Run paired arms and inspect raw traces before updating the evidence index or making a design recommendation.
7. Expand to additional tasks only after the pilot establishes that the instrumentation, scoring, and safety boundaries are sound.

## 10. Claim boundary

This document is a proposed experiment, not an implemented capability. No delta proposal API, factorial agent run, independent oracle service, or statistical result exists yet. The current E-007 full-snapshot task remains the active baseline until the running retry is evaluated. No language, syntax, runtime, transport, or persistence technology is selected by this proposal.
