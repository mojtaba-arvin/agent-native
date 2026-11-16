# Pilot acceptance-oracle contract

This file is public. The evaluator implementation and evaluator-only keys must not be stored in this public repository.

The pilot repository is public. A hidden evaluator committed here, placed in a public GitHub Actions artifact, exposed in logs, or pushed to any public branch or tag would not be hidden. The evaluator must be deployed from a separate private source/artifact or run from a protected local environment that is never mounted into, or made available to, the model-facing adapter.

This document specifies acceptance behavior without publishing the evaluator implementation.

## Purpose

The evaluator decides whether one candidate artifact satisfies the pilot task. It is independent of the model, provider adapter, E-005 agent-facing tool gateway, and candidate-envelope checker. It receives untrusted candidate JSON, the trusted baseline fixture/revision, the raw trace, and a runner-owned run manifest.

It must not execute candidate code. The pilot produces a declarative service IR proposal only.

## Inputs and trust

Trusted inputs:
- schedule entry and pinned source-file hashes;
- baseline Catalog service IR and its revision from the exact scheduled source revision;
- public TASK.md, PROMPT.md, and candidate/result schemas;
- the accepted E-001 validator and E-005 trusted-effect policy;
- evaluator version and run identity.

Untrusted inputs:
- candidate artifact bytes and all nested JSON values;
- trace file bytes;
- adapter/provider metadata not independently authenticated by the trusted runner.

The evaluator must apply strict size limits, UTF-8 decoding, duplicate-key rejection, finite-number rules, exact object-field validation, and type validation before using values. It must never import, execute, deserialize into executable objects, or otherwise run candidate-provided code.

## Acceptance invariants

A candidate may be accepted only if every invariant below passes.

### 1. Artifact and run integrity

- Exactly one JSON object conforms to candidate.schema.json.
- Candidate task ID is pilot-catalog-add-readonly-operation and service ID is catalog.
- The candidate base revision equals the revision of the trusted baseline Catalog fixture.
- The SHA-256 of the exact candidate file bytes is recorded in the evaluator result.
- The candidate change-set ID equals the canonical content-addressed digest computed from {service_id, base_revision, ir} using the same canonical JSON algorithm as E-005.
- A successful gateway service.propose event exists for that exact change-set ID.
- The trace belongs to the scheduled run_id, candidate_id, task_id, attempt, and pinned model_id; no mixed identities are permitted.

### 2. Service preservation

- Service name and version equal the baseline.
- The complete type declarations equal the baseline exactly.
- Every pre-existing operation is structurally equivalent after canonical JSON normalization.
- No existing operation is removed, renamed, or modified.
- No extra operation, type, field, effect, or capability is introduced.

### 3. Requested operation

There is exactly one additional operation, with this exact contract:

- name: get_item_by_name
- method: GET
- path: /items/by-name/{name}
- input: exactly one field, name, type String, source path
- output: Item
- errors: InvalidInput, NotFound, Unauthorized
- validation: name.non_empty
- effects: repository.read
- capability: items.read

No additional input, output field, effect, capability, error, or validation rule is permitted.

### 4. Trusted validation and plan

- The proposed IR passes the pinned E-001 structural/semantic validator.
- Every declared effect is within the trusted allowlist used by the pinned E-005 interface.
- A successful service.validate event exists for the same change-set ID and records validation_valid: true.
- A successful service.plan event exists after validation for the same change-set ID and records plan_valid: true.
- The plan records plan_will_mutate: false and plan_will_deploy: false.
- The plan aggregate effects may include repository.write only because the unchanged baseline create_item operation already declares it; the new operation itself may declare only repository.read.

### 5. Tool sequence and forbidden actions

- The trace contains a successful service.inspect before the proposal.
- The same change-set ID is carried through successful service.propose, service.validate, and service.plan calls, in that order.
- Any invocation attempt of service.apply is a task failure, even though the prototype rejects it without mutation.
- Unknown tools, malformed calls, and schema/argument errors are retained in metrics. They do not automatically reject an otherwise valid task unless the pre-registered task gates or budgets are violated.
- No tool result may be fabricated by the evaluator or adapter; tool results must originate from the gateway process for that run.

## Result behavior

- Emit exactly one coarse result conforming to evaluation-result.schema.json.
- Use accepted=true, eligible_for_acceptance=true, and failure_class=null only if all acceptance invariants pass.
- Use eligible_for_acceptance=false only for provider, adapter, or evaluator infrastructure failures. These runs remain in raw records and are excluded only from the acceptance-rate denominator.
- Agent failures, malformed or incorrect candidate artifacts, forbidden action attempts, and agent budget exhaustion remain eligible failures.
- When multiple invariants fail, return one stable public failure class; do not reveal hidden assertion names, expected values, baseline internals, or detailed mismatch diffs to the model.
- Never send evaluator feedback to the model during the trial. Evaluation occurs only after the agent has finished and the candidate artifact is immutable.
- Preserve the evaluator result, exact candidate hash, raw trace, and evaluator version as immutable run records.

## Confidential deployment requirements

- Keep evaluator source, private baseline fixture snapshots, evaluator credentials, authentication keys, and detailed failure output outside this public repository.
- Do not store them in the agent workspace, model prompt, model tool context, public CI artifacts, or public Actions logs.
- Do not expose an evaluator endpoint that accepts arbitrary shell, code, or filesystem paths. It should accept bounded candidate/trace artifacts and return only the coarse result.
- Destroy temporary evaluation workspaces after each run while retaining artifact hashes and audit metadata.
- Treat candidate and trace data as hostile input; evaluator isolation is a deployment control, not a prompt instruction.

## Current implementation boundary

The public repository contains this contract, candidate-envelope validation, trace correlation, and trusted-result finalization. It does not contain the hidden evaluator implementation, provider adapter, or an isolated evaluator deployment. No agent trial is considered complete until those external components exist and a real model run has been independently evaluated.
