# Agent Native — research and prototype status

**Snapshot:** 17 November 2026  
**Project state:** executable research prototypes; no production framework or technology choice has been declared.

## Executive summary

Agent Native is exploring a backend framework designed from first principles for AI agents as its primary authors and operators. The intended product owns its programming model, service semantics, runtime, security boundary, data behavior, distributed execution, and operational lifecycle. It is not a wrapper, adapter, control plane, or code generator for an existing backend framework.

The repository now contains eight independent research workstreams plus E-009, an integrated framework-kernel vertical slice. E-009 connects service IR, capability enforcement, HTTP request handling, tenant-scoped persistence, durable work, a worker/relay, a wired SQLite authorization audit sink, and an Agent-facing inspect/propose/validate/plan gateway. E-007 now has its first executable real-agent eval case and deterministic scorer pipeline; E-002 has a ten-repetition diagnostic runtime matrix with registered gates. The first E-007 Qwen3 attempt exposed an Ollama template-renderer configuration error and is ineligible as an agent-task outcome; a corrected three-run attempt is in progress. The project still has no accepted E-007 model result and no evidence that Agent Native improves agent productivity or is production-ready.

## Product thesis

A framework designed for agents should reduce the total cost and failure rate of building and operating backend systems by making contracts explicit, authority enforceable outside the model, and execution behavior deterministic.

The project optimizes for accepted backend work rather than generated code volume. Relevant costs include model tokens, tool calls, repair loops, human intervention, runtime resources, infrastructure, security failures, and future maintenance.

No implementation language, service syntax, compiler architecture, runtime, or public protocol is preselected. Those are research variables, not decisions already made.

## Work completed

| Workstream | Executable contribution | Evidence boundary |
|---|---|---|
| E-001 — Service representation | Textual service-contract parser, canonical IR validation, structured-IR parity fixture, disposable reference executor, and a loopback HTTP slice | Parser and prototype behavior are tested; this is not a released language or framework |
| E-002 — Execution substrates | Go, Rust, WASI P2, and BEAM black-box conformance baselines, plus reproducible load and randomized-matrix runners; ten randomized repetitions per candidate now report distributions and bootstrap intervals | Ten-run shared-host diagnostic completed; all candidates passed functional checks but all failed the pre-registered CPU gate; no runtime selected |
| E-003 — Concurrency and failure | Deterministic reference model for admission, deadlines, cancellation, retries, idempotency, worker crashes, and shutdown | Semantics are modeled and tested independently, not yet integrated into a complete runtime |
| E-004 — Security | Default-deny capability reference model, threat model, requirements, and adversarial policy tests | Prototype policy evidence is not a production security audit |
| E-005 — Agent interface | Progressive schema discovery, proposal hashing, strict request validation, semantic validation, safe planning, and disabled apply | It is an experimental interface prototype, not the final Agent Native protocol |
| E-006 — Durable execution | SQLite reference model with idempotent submission, lease fencing, recovery, retries, deadlines, and atomic local effects | Durable semantics are tested in isolation, not yet part of an integrated framework |
| E-007 — Agent benchmark | Public backend-agent task corpus, oracle-isolation contract, trace schema, metrics aggregation, workspace packager, first declarative eval case, real Ollama runner, three deterministic scorers, and CI artifact pipeline | First three-run attempt was invalid due missing Qwen3-compatible Ollama template configuration; corrected run is in progress; no accepted agent-task result yet |
| E-008 — External-effect delivery | SQLite transactional outbox/inbox model with fenced relay leases, retry exhaustion, at-least-once delivery, and consumer deduplication | It does not claim exactly-once delivery to arbitrary external APIs |
| E-009 — Integrated kernel | Contract-driven HTTP runtime, default-deny authorization, tenant-scoped SQLite, durable work, fenced workers, transactional outbox/inbox, wired SQLite authorization audit sink, and Agent inspect/propose/validate/plan gateway | 72 E-009 tests pass in CI, including audit persistence/reopen/concurrency/fail-closed checks and bounded local-agent repair/provenance checks. Five standalone Qwen3 trials remain unsuccessful; trial 5 reached validation but was rejected with AN021 and repeated the same malformed proposal. This is a single-node semantic integration proof, not a production framework or technology choice |

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
- E-001 through E-008 retain independent executable research implementations; E-009 composes the service representation, authority model, durable jobs, and external-event handling into one runnable HTTP service slice.
- Go, Rust, WASI P2, and BEAM prototype baselines have passed the shared black-box conformance suite.
- The E-009 kernel has a live Agent Gateway for schema discovery, inspect, immutable proposal, validation, safe planning, and disabled apply; a bounded local Ollama runner; a stdlib HTTP host; tenant-scoped durable persistence; a queue/worker/outbox/inbox path; and a durable SQLite audit sink wired before application handlers, all covered by automated tests.
- The E-005 pilot gateway, paired schedule, local adapter, batch runner, trace handling, and candidate/finalization path are covered by automated protocol tests.
- Experiment inputs and source revisions can be pinned and checked before a run.
- Model usage is recorded from provider telemetry rather than inferred from elapsed time or message size.

**Not yet supported:**
- That a real model can reliably complete the pilot task through this adapter, or that the first E-007 Qwen3 eval attempt is an eligible agent-task result (it failed before any tool call because the Ollama template renderer was misconfigured).
- That progressive disclosure improves acceptance, token use, latency, or cost.
- That any candidate has passed an independent hidden acceptance oracle.
- That E-009 is a complete framework: it is one integrated vertical slice with a fixed demo Catalog service, single-node SQLite, and a stdlib reference host.
- That any language, syntax, runtime, protocol, or architecture is superior.
- That the project is production-ready or more secure or performant than existing frameworks.

Mock-provider CI verifies adapter behavior and trace integrity. It is not a real model trial and must not be presented as one.

## Evaluation gates

| Gate | Current assessment |
|---|---|
| G0 — Research integrity | Partially established: the first eval case, real-agent runner, deterministic scorers, source hashes, and failure classification exist; the first provider run was ineligible due environment configuration and no accepted evaluator-backed result exists yet |
| G1 — Agent interface | Not yet passed: requires real repeated model runs and independent acceptance results |
| G2 — Core feasibility | Partial: E-009 proves one integrated contract-driven HTTP/data/job lifecycle; language/compiler/runtime breadth and a general application model remain incomplete |
| G3 — Safety | Default-deny capability checks, tenant filtering, fail-closed durable SQLite authorization audit, bounded HTTP admission, and no-apply Agent interface are integrated/tested; no production identity, remote/tamper-evident audit, isolation, or security audit |
| G4 — Distributed behavior | Partial integration: durable jobs, leases/fencing, stop acknowledgements, outbox relay, and inbox deduplication work in a single SQLite process model; distributed multi-node guarantees remain unproven |
| G5 — Performance | Not passed: the ten-run E-002 matrix is shared-host diagnostic only and every candidate failed the pre-registered CPU gate; representative workloads and controlled hardware are still missing |
| G6 — Production candidate | Not reached |

## Next evidence milestones

1. Complete the corrected three-repetition Qwen3 E-007 eval with the Qwen3-compatible Ollama template renderer; classify every run and preserve all traces. Even a 3/3 pass is only an initial repeatability check.
2. Extend E-007 from the single structured E-009 proposal case to the public task corpus with a separate evaluator trust boundary/sandbox; then evaluate constrained, general, and advanced model tiers.
3. Run the E-005 paired disclosure pilot with real model/provider usage and independent evaluator results; missing traces or run identities must stop analysis rather than disappear from the sample.
4. Revisit the E-002 CPU screening threshold only in a new pre-registered cycle, then repeat on controlled hardware with persistence, authorization, serialization, inter-service, and injected-failure workloads. Measure ecosystem/operability and comparable artifact size.
5. Extend E-009 with process supervision, remote/tamper-evident audit retention, streaming/cancellation semantics, and versioned service migrations with rollback.
6. Publish raw distributions, uncertainty intervals, failures, and counter-evidence. Keep language/runtime choices open until those comparisons justify a decision.

## Presentation-safe project description

**Agent Native is an independent research and prototyping effort for a backend framework designed around AI agents as primary authors and operators.** It explores service representation, execution substrates, concurrency and failure semantics, capability security, agent-facing interfaces, durable execution, benchmark methodology, and reliable external-effect delivery. The repository contains executable prototypes and reproducible conformance experiments; technology choices remain open pending agent-task, safety, and performance evidence.

This description intentionally distinguishes an ambitious product direction from the current state of implementation.