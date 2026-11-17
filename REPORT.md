# Agent Native — research and prototype status

**Snapshot:** 17 November 2026  
**Project state:** executable research prototypes; no production framework or technology choice has been declared.

## Executive summary

Agent Native is exploring a backend framework designed from first principles for AI agents as its primary authors and operators. The intended product owns its programming model, service semantics, runtime, security boundary, data behavior, distributed execution, and operational lifecycle. It is not a wrapper, adapter, control plane, or code generator for an existing backend framework.

The repository now contains eight executable research workstreams and a reproducible agent-interface pilot harness. The next meaningful evidence milestone is a real paired run with a local model and an independent evaluator. Until those runs exist, the project has prototype and conformance evidence—not evidence that Agent Native improves agent productivity or is production-ready.

## Product thesis

A framework designed for agents should reduce the total cost and failure rate of building and operating backend systems by making contracts explicit, authority enforceable outside the model, and execution behavior deterministic.

The project optimizes for accepted backend work rather than generated code volume. Relevant costs include model tokens, tool calls, repair loops, human intervention, runtime resources, infrastructure, security failures, and future maintenance.

No implementation language, service syntax, compiler architecture, runtime, or public protocol is preselected. Those are research variables, not decisions already made.

## Work completed

| Workstream | Executable contribution | Evidence boundary |
|---|---|---|
| E-001 — Service representation | Textual service-contract parser, canonical IR validation, structured-IR parity fixture, disposable reference executor, and a loopback HTTP slice | Parser and prototype behavior are tested; this is not a released language or framework |
| E-002 — Execution substrates | Go, Rust, WASI P2, and BEAM black-box conformance baselines, plus reproducible load and randomized-matrix runners | Smoke matrices are preserved but are not decision-grade and select no runtime |
| E-003 — Concurrency and failure | Deterministic reference model for admission, deadlines, cancellation, retries, idempotency, worker crashes, and shutdown | Semantics are modeled and tested independently, not yet integrated into a complete runtime |
| E-004 — Security | Default-deny capability reference model, threat model, requirements, and adversarial policy tests | Prototype policy evidence is not a production security audit |
| E-005 — Agent interface | Progressive schema discovery, proposal hashing, strict request validation, semantic validation, safe planning, and disabled apply | It is an experimental interface prototype, not the final Agent Native protocol |
| E-006 — Durable execution | SQLite reference model with idempotent submission, lease fencing, recovery, retries, deadlines, and atomic local effects | Durable semantics are tested in isolation, not yet part of an integrated framework |
| E-007 — Agent benchmark | Public backend-agent task corpus, oracle-isolation contract, trace schema, metrics aggregation, and workspace packager | No agent performance result is claimed until real runs are independently evaluated |
| E-008 — External-effect delivery | SQLite transactional outbox/inbox model with fenced relay leases, retry exhaustion, at-least-once delivery, and consumer deduplication | It does not claim exactly-once delivery to arbitrary external APIs |

## First agent-interface experiment

The pilot isolates one question before the project invests in a general agent runtime:

> Does progressive disclosure of typed tool schemas reduce invalid tool selection and total agent effort without reducing task acceptance, compared with exposing the same complete schemas up front?

The two arms use the same six E-005 operations, backend state, prompt, task, model settings, budgets, result semantics, and provider-facing function. The only intended independent variable is whether detailed tool schemas are present in the initial session surface or retrieved by name when needed.

The task asks an agent to inspect a Catalog service, propose one read-only operation, validate the proposal, and produce a no-side-effect plan. Applying or deploying changes is disabled.

### Experimental harness

The public repository includes:

- An immutable paired schedule with recorded randomization seed, source revision, source-file hashes, model settings, and token/tool/time budgets.
- A schedule verifier that refuses a dirty or mismatched checkout.
- A local NDJSON gateway with a fixed tool allowlist, per-run traces, monotonic timestamps, and enforced token/tool ceilings.
- A bounded Ollama adapter that accepts only a loopback HTTP endpoint, exposes one `agent.invoke` function, and records provider-reported token usage through the gateway.
- A serial batch runner that preserves each run directory and writes a batch manifest, including classified failures and interruption state.
- A paired analysis tool that requires every finalized trace, checks schedule/run identity, reports per-arm acceptance and effort, paired differences, bootstrap intervals, exact McNemar results, and E-007 aggregates.
- Candidate-envelope validation and a finalizer that correlates candidate hashes, proposal traces, validation, planning, and a separately supplied evaluator result.

The adapter is pilot infrastructure only. It does not define the future Agent Native public protocol or make Ollama a product dependency.

## What the current evidence supports

**Supported:**
- The eight research workstreams have executable reference implementations and automated checks.
- Go, Rust, WASI P2, and BEAM prototype baselines have passed the shared black-box conformance suite.
- The pilot gateway, paired schedule, local adapter, batch runner, trace handling, and candidate/finalization path are covered by automated protocol tests.
- Experiment inputs and source revisions can be pinned and checked before a run.
- Model usage is recorded from provider telemetry rather than inferred from elapsed time or message size.

**Not yet supported:**
- That a real model can reliably complete the pilot task through this adapter.
- That progressive disclosure improves acceptance, token use, latency, or cost.
- That any candidate has passed an independent hidden acceptance oracle.
- That the current prototypes form a complete, integrated backend framework.
- That any language, syntax, runtime, protocol, or architecture is superior.
- That the project is production-ready or more secure or performant than existing frameworks.

Mock-provider CI verifies adapter behavior and trace integrity. It is not a real model trial and must not be presented as one.

## Evaluation gates

| Gate | Current assessment |
|---|---|
| G0 — Research integrity | Partially established: task, paired schedule, hashes, and public protocol are defined; real evaluator-backed trial records are still absent |
| G1 — Agent interface | Not yet passed: requires real repeated model runs and independent acceptance results |
| G2 — Core feasibility | Partial prototypes exist; no complete service compiler/runtime has been integrated |
| G3 — Safety | Reference capability model and pilot no-apply boundary are tested; no production security audit |
| G4 — Distributed behavior | Concurrency, durability, and delivery models exist independently; integrated runtime behavior remains unproven |
| G5 — Performance | Not passed: existing CI smoke matrices are explicitly non-decision-grade |
| G6 — Production candidate | Not reached |

## Next evidence milestones

1. Run the one-pair local-model wiring check from a clean checkout and retain both raw traces, candidate outputs, and batch manifest.
2. Provision the evaluator separately from the public repository and model-facing process. It must verify the candidate against the trusted baseline and emit only the coarse result contract.
3. Finalize every scheduled run through the trusted-result finalizer and run the paired analyzer; missing traces or run identities stop analysis rather than disappearing from the sample.
4. Run the pre-registered screening study, inspect all failures, and proceed to at least 30 paired repetitions only if the harness and evaluator pass integrity checks.
5. Publish raw distributions, paired differences, uncertainty intervals, excluded infrastructure failures, and the resulting decision—including a negative or inconclusive result if that is what the data shows.
6. Use the wider E-007 task corpus to test generality only after the narrow pilot has established a trustworthy end-to-end evaluation path.

## Presentation-safe project description

**Agent Native is an independent research and prototyping effort for a backend framework designed around AI agents as primary authors and operators.** It explores service representation, execution substrates, concurrency and failure semantics, capability security, agent-facing interfaces, durable execution, benchmark methodology, and reliable external-effect delivery. The repository contains executable prototypes and reproducible conformance experiments; technology choices remain open pending agent-task, safety, and performance evidence.

This description intentionally distinguishes an ambitious product direction from the current state of implementation.