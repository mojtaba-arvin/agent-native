# E-007 follow-up — proposal representation and base-disclosure factorial experiment

**Status:** corrected factorial implemented through Gateway, local-agent adapter, independent scorer, and five pinned case manifests; deterministic CI passes. No factorial cell has been dispatched to a real model, and no architecture decision follows.  
**Parent evidence:** E-009 full-snapshot proposal task; E-007 real-agent traces through 2026-11-18.  
**Decision question:** Separately estimate the effect of proposal representation and the delivery sequence of the same complete base contract. Treat reduced-information/minimal disclosure as a separate exploratory treatment, not as a cell in the factorial.

## 1. Why this experiment is necessary

The E-009 task currently requires the agent to inspect a service, inspect every existing operation, reconstruct the entire canonical IR snapshot, append one operation, propose it, validate it, and plan it. The Gateway independently verifies exact preservation of the inspected base.

The real-model history has exposed several distinct failure modes:

- Earlier deterministic trials omitted required top-level IR fields and existing operations.
- A stochastic trial produced a full-shaped IR but rewrote five existing operations.
- A later deterministic trial reached a Gateway-accepted, exact-preserving proposal after two rejected attempts, but exhausted its wall budget before validation and planning.
- The 18 November Second Light retry completed but remained ineligible: it inspected four of six operations, issued seven proposals, and did not reach validation or plan. Its trace exposed a non-terminal repair-budget response and a post-run telemetry clock bug; both runner fixes are merged and covered by passing CI.

These observations establish that the current task is difficult for the tested Qwen3 configuration. They do **not** establish why. In particular, they do not prove that full snapshots are inherently inferior, that the model is incapable, or that a delta interface is safer. The next experiment should distinguish these explanations rather than immediately changing the core contract.

## 2. Competing hypotheses

- **H1 — Snapshot reconstruction burden:** reproducing unchanged declarations consumes substantial context and creates avoidable preservation errors.
- **H2 — Representation mismatch:** a constrained change-intent representation is easier for agents to author correctly than a complete service snapshot.
- **H3 — Inspection burden:** requiring operation-by-operation inspection is a material source of tool calls, latency, and context growth.
- **H4 — Safety trade-off:** server-side materialization of a constrained delta can preserve the same or stronger integrity guarantees, but only if the base revision, allowed mutation set, and canonical resulting IR are enforced by trusted code.
- **H0 — No material improvement:** after controlling the task and runtime, a delta surface does not materially improve accepted-task rate or total cost per accepted task.

All remain open.

## 3. Experimental design: corrected 2 × 2 factorial

The initial draft mixed two different meanings of "base disclosure": full contracts delivered one operation at a time, full contracts delivered in one service-level response, and minimal summaries. That was not a clean two-level factor. The corrected factorial keeps the *total information identical* in all four cells and varies only its delivery sequence.

- **Factor 1 — proposal representation:** complete canonical snapshot vs constrained typed delta.
- **Factor 2 — inspection delivery:** full contracts delivered operation-by-operation vs the same complete base IR delivered upfront in one read-only inspection result.

| Arm | Proposal representation | Inspection delivery |
|---|---|---|
| A — current baseline | Complete canonical IR snapshot | Full contracts; operation-by-operation |
| B | Constrained typed delta | Full contracts; operation-by-operation |
| C | Complete canonical IR snapshot | Complete service/type/operation contract in one service-level inspection |
| D | Constrained typed delta | Complete service/type/operation contract in one service-level inspection |

All four arms receive the same service identity, types, and complete existing operation contracts. In A/B, full operation contracts arrive through individual inspection calls and proposal is blocked until all required inspections are complete. In C/D, the service-level inspection returns the complete service object, types, and full operation contracts in one response; no per-operation calls are needed. The `ir_version=1` envelope constant is part of the task/schema contract in both snapshot cells. The validator, planner, effect policy, task, model/runtime, and no-apply rule remain identical.

This is a genuine factorial: the A↔B contrast estimates representation under per-operation delivery; C↔D estimates representation under upfront delivery; A↔C and B↔D estimate delivery-sequence effects for each representation. The interaction term tests whether the benefit of delta depends on how the base is disclosed.

**Separate exploratory treatment E — minimal disclosure:** delta proposal with only service revision, type names, and operation summaries; full unchanged contracts stay server-side. E is not part of the 2×2 because a complete-snapshot authoring surface cannot fairly operate without the full base. Compare E only after the four-cell factorial, and label it exploratory rather than folding it into the factorial estimate.

Do not compare only A with E and attribute the entire difference to proposal representation.

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

A seeded generated-base test now constructs 12 valid service variants, shuffles their existing operation order, and asserts that materialization preserves every existing declaration, appends only the requested operation, and produces deterministic hashes. This is bounded generative coverage, not a claim of exhaustive property-based verification. Formal mutation testing is a precondition before generalizing the change language or enabling any apply path; it is deferred for this single-operation, read-only, no-apply feasibility pilot.

## 8. Decision rule

Do not replace the full-snapshot interface merely because one delta run succeeds. Keep the current interface as the control.

A delta arm becomes a serious candidate only if:
- its trusted materializer and adversarial tests pass;
- completed acceptance is not worse than the snapshot control within a pre-registered non-inferiority margin;
- it materially reduces total cost per accepted task or repair burden;
- it does not increase security, ambiguity, stale-base, or operational risk;
- the result replicates on more than one task before any broad architecture claim.

If the delta improves authoring cost but complicates the trusted runtime substantially, report that trade-off rather than hiding it. If the factorial results show inspection burden dominates, optimize the disclosure workflow separately. If neither factor helps, preserve the current design and investigate prompt/tool sequencing or model capability without silently relaxing correctness gates.

## 9. Execution sequence and implementation status

1. Preserve and inspect the completed Second Light artifact; its trace analysis is recorded. Do not rerun the unchanged full-snapshot task.
2. **Trusted materializer complete:** `experiments/e007/delta_materializer.py` strictly materializes one append-only operation against the trusted current base, validates the canonical result, and binds the exact base revision and result hash.
3. **Gateway treatment controls complete:** `AgentNativeGateway` exposes orthogonal `proposal_mode` and `base_disclosure` settings. The four factorial combinations are supported; minimal disclosure is restricted to delta as exploratory treatment E. Invalid combinations and attempts to cross treatment boundaries fail closed.
4. **Local-agent adapter complete:** `local_agent.py` accepts the proposal and disclosure modes, uses a mode-specific task contract, tracks both proposal tools, verifies delta candidates by independently re-materializing against the trusted catalog, and preserves the selected treatment in run metadata.
5. **Independent evaluator complete:** `eval_runner.py` reconstructs the trusted base outside the agent-visible context, recomputes the delta materialization and change-set hash, checks exact candidate schema, verifies the proposal/validation/plan hash chain, and enforces disclosure-specific inspection behavior.
6. **Pinned cases created:** A–D are the corrected 2×2 factorial cells under `experiments/e007/evals/e007-factorial-*.eval.json`; E is the separate minimal-disclosure exploratory case. All cells use the same task and fixed Qwen3 settings/budgets from the already-tested expanded-budget case; no model budget was increased.
7. **Deterministic CI passed:** the E-009 integrated runner/Gateway suite and E-007 evaluator suite pass, including delta candidate verification and all three disclosure modes. These tests are implementation evidence, not real-agent outcomes.
8. **Dispatch integrity complete:** the version-2 manifest separates dispatch_id from each case eval_id and binds exact case paths. The guarded script validates all four cells, equal settings/budgets, no-apply policy, and seeded execution order C-A-D-B before the first model request. The workflow is manual-dispatch-only; research-branch pushes cannot launch a model run. Pin the exact workflow commit and pass full protocol/kernel CI before manual dispatch.
9. Only after the preceding checks pass, manually run one matched, no-apply pilot for A–D with identical model/runtime settings and inspect raw traces. Run E separately and label it exploratory. Do not increase Qwen3 budgets or run the model before all preflight checks pass.
10. Expand to additional tasks only after the pilot establishes that instrumentation, scoring, and safety boundaries are sound.

## 10. Claim boundary

The corrected factorial is now implemented in the Gateway, local-agent adapter, independent evaluator, and case manifests. CI verifies the deterministic protocol and scorer paths. No A–D cell or E treatment has been dispatched to a real model, no acceptance or comparative performance result exists, and no architecture decision has been made. The snapshot interface remains the default. No language, syntax, runtime, transport, or persistence technology is selected by this experiment.
