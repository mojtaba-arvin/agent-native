# E-009 proposal IR contract

**Status:** normative for the E-005/E-009 proposal interface prototype  
**Revision:** 17 November 2026

## Proposal semantics

The value supplied as `service.propose.arguments.ir` is the **complete proposed service IR snapshot**. It is not a patch, an operation-only delta, or an instruction for the Gateway to merge missing fields from the current service.

The E-005 interface deep-copies the submitted object into an immutable proposal record. `service.validate` passes that stored object directly to the canonical E-001 `validate_ir` function. It does not infer omitted fields or reconstruct the service from prior inspections.

The base revision binds the proposal to the inspected service version. Inspection is a separate prerequisite: the E-009 gateway requires a service-level inspection and inspection of every existing operation before it forwards a proposal. This prerequisite does not transform a partial IR into a full IR.

## Required top-level structure

A proposal IR must have exactly these top-level fields:

| Field | Required value |
|---|---|
| `ir_version` | Integer `1` |
| `service` | Complete service identity, containing `name` and `version` |
| `types` | Complete array of type declarations and their fields |
| `operations` | Complete array of operation declarations |

Unknown top-level properties are rejected. In particular, omitting `ir_version` produces `AN021` ("unsupported or malformed IR version or top-level shape").

Each operation has the complete E-001 operation shape: `name`, `method`, `path`, `input`, `output`, `errors`, `validation`, `effects`, and `capability`. `input` is an array of objects with exactly `name`, `type`, and `source`. The source is one of `path`, `query`, `body`, or `header`.

## Preservation is task-specific

When a task says to preserve an existing service, type, field, or operation, the agent must copy the full inspected declarations into the proposed snapshot and make only the requested change. The interface prototype validates canonical structure and effect allowlists; the E-009 evaluation scorer additionally checks that all existing declarations are preserved exactly. The scorer is not a substitute for server-side validation in a future production protocol.

## Exact preservation enforcement in the E-009 Gateway

For the E-009 fixed Catalog task, the Gateway retains the inspected service identity, type declarations, the original operation order, and each exact inspected operation object for the inspected revision. Before forwarding a proposal based on that same revision, it compares those declarations with the submitted complete IR. The existing service, types, and ordered operation prefix must be identical. A mismatch is rejected with `IR_PRESERVATION_MISMATCH`, naming changed operations and instructing the agent to copy the exact inspected objects.

This check is in the Gateway boundary, not just the local model adapter. It does not silently normalize or repair the proposal. The model must submit a corrected full snapshot. The generic E-005 proposal API still accepts immutable proposals and validates canonical IR; the stronger preserve-the-existing-Catalog policy is scoped to the E-009 Gateway experiment.

## Validation response semantics

The outer tool response can be `ok=true` while `result.valid=false`. The outer flag means the tool request was handled; it is not the semantic acceptance result.

An agent or client must:
1. Inspect `result.valid` and the diagnostics returned inside `result`.
2. Treat `valid=false` as a rejected proposal.
3. Correct the complete IR and submit a new proposal hash.
4. Call `service.plan` only after `valid=true` for the same change-set hash.

The E-009 local runner enforces the last condition independently: a premature plan call is blocked before reaching the Gateway and returned as a structured `VALIDATION_REQUIRED` diagnostic.

## Failure observed in the Qwen3 three-run artifact

The model did correctly serialize the new operation's `input` as an array with `name`, `source`, and `type`. The submitted IR nevertheless omitted `ir_version` and contained only the new operation rather than the complete existing operations plus the new operation. The first omission explains the observed `AN021`; the second would fail the preservation scorer even after correcting the version field.

The validation diagnostic in that artifact contained the generic AN021 message and a null fix hint. The interface now adds a fix hint naming the required top-level fields and complete-snapshot semantics. The model-visible proposal schema and task prompt have also been made explicit.

## Deliberate non-goals

This contract does not introduce a patch/merge protocol. A future patch protocol would require a separate explicit type and semantics (including base binding, conflict detection, and patch validation); it must not be inferred from a partial `ir` object.
