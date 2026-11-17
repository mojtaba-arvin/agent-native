# Agent Native — research and prototype status

**Snapshot:** 17 November 2026  
**Project state:** executable research prototypes; no production framework or technology choice has been declared.

## Executive summary

Agent Native is exploring a backend framework designed from first principles for AI agents as its primary authors and operators. The intended product owns its programming model, service semantics, runtime, security boundary, data behavior, distributed execution, and operational lifecycle. It is not a wrapper, adapter, control plane, or code generator for an existing backend framework.

The repository contains eight independent research workstreams plus E-009, an integrated framework-kernel vertical slice. E-009 connects service IR, capability enforcement, HTTP request handling, tenant-scoped persistence, durable work, worker/relay execution, a wired SQLite authorization audit sink, and an Agent-facing inspect/propose/validate/plan Gateway. E-007 now has a specialized real-agent runner for one fixed task, three deterministic scorers, an aggregate token/time budget with mock-tested fail-fast behavior, and evidence artifacts. Its corrected three-run Qwen3 cohort is **0/3 accepted**: every attempt failed validation with `AN021`. The artifact shows the input declaration array was correct, but the model omitted `ir_version=1` and all existing operations from the complete IR snapshot, then called plan when `result.valid=false`. All three used temperature 0 and seed 42; Ollama logs show prompt/KV cache reuse, so the cohort is a deterministic failure reproduction, not statistical evidence. E-005/E-009 contracts, Gateway base-preservation checks, bounded proposal-attempt controls, and plan-gate fixes pass deterministic CI. One post-fix stochastic Qwen3 probe at temperature 0.7 produced a full top-level IR but rewrote five existing operations; the Gateway rejected its first proposal until all six operations were inspected, and the model then hit the 900-second wall ceiling before resubmitting. No validation or plan occurred. This is not a successful post-fix real-model result. A further deterministic post-Gateway-preservation run [44144939813](https://github.com/mojtaba-arvin/agent-native/actions/runs/44144939813), artifact [14357367813](https://github.com/mojtaba-arvin/agent-native/actions/runs/44144939813/artifacts/14357367813), was inspected. It stopped at 48,307 input tokens against a 48,000 cap after five of six operations were inspected; duration was 1,020.139 seconds against a 1,200-second wall cap. It did not reach a second proposal, validation or plan. No AN021, provider error, or observed OOM occurred. The raw artifact incorrectly marked the run eligible; the runner now excludes per-run resource-budget exhaustion. A single follow-up is running as [workflow 44149712970](https://github.com/mojtaba-arvin/agent-native/actions/runs/44149712970) with 96,000 input tokens and 1,800 seconds. E-002 remains diagnostic; all candidates failed the provisional CPU screen in two ten-run cohorts and no runtime is selected. The second cohort measured one uncompressed Linux x86_64 deployment payload per candidate: Go 10,012,310 B (9.55 MiB), Rust 4,991,320 B (4.76 MiB), WASI+Wasmtime 71,947,386 B (68.61 MiB), and BEAM+ERTS 74,856,626 B (71.39 MiB). These host-specific package measurements do not offset the misses of the provisional CPU eligibility screen; ecosystem and comparable fault-injection evidence remain open. No productivity, superiority, or production-readiness claim is made.

## Product thesis

A framework designed for agents should reduce the total cost and failure rate of building and operating backend systems by making contracts explicit, authority enforceable outside the model, and execution behavior deterministic.

The project optimizes for accepted backend work rather than generated code volume. Relevant costs include model tokens, tool calls, repair loops, human intervention, runtime resources, infrastructure, security failures, and future maintenance.

No implementation language, service syntax, compiler architecture, runtime, or public protocol is preselected. Those are research variables, not decisions already made.

## Work completed

| Workstream | Executable contribution | Evidence boundary |
|---|---|---|
| E-001 — Service representation | Textual service-contract parser, canonical IR validation, structured-IR parity fixture, disposable reference executor, and a loopback HTTP slice | Parser and prototype behavior are tested; this is not a released language or framework |
| E-002 — Execution substrates | Go, Rust, WASI P2, and BEAM black-box conformance baselines, plus reproducible load and randomized-matrix runners; ten randomized repetitions per candidate now report distributions and bootstrap intervals | [Ten-run shared-host diagnostic](experiments/e002/results/2026-11-17-ten-run-diagnostic.md) completed; all candidates passed functional checks but all failed the pre-registered CPU gate; no runtime selected |
| E-003 — Concurrency and failure | Deterministic reference model for admission, deadlines, cancellation, retries, idempotency, worker crashes, and shutdown | Semantics are modeled and tested independently, not yet integrated into a complete runtime |
| E-004 — Security | Default-deny capability reference model, threat model, requirements, and adversarial policy tests | Prototype policy evidence is not a production security audit |
| E-005 — Agent interface | Progressive schema discovery, proposal hashing, strict request validation, semantic validation, safe planning, and disabled apply | It is an experimental interface prototype, not the final Agent Native protocol |
| E-006 — Durable execution | SQLite reference model with idempotent submission, lease fencing, recovery, retries, deadlines, and atomic local effects | Durable semantics are tested in isolation, not yet part of an integrated framework |
| E-007 — Agent benchmark | Public ten-task corpus, oracle-isolation contract, trace schema/metrics, one declarative real-agent eval case, three deterministic scorers, aggregate budgeter, and failure taxonomy | The fixed-seed cohort [44087982547](https://github.com/mojtaba-arvin/agent-native/actions/runs/44087982547) failed 0/3 at validation with AN021. The stochastic probe [44105440141](https://github.com/mojtaba-arvin/agent-native/actions/runs/44105440141) formed a full top-level IR but rewrote five existing operations, then timed out before retry/validate/plan. Neither demonstrates a successful agent task; details in [probe analysis](experiments/e007/results/2026-11-17-stochastic-qwen3-probe.md). |
| E-008 — External-effect delivery | SQLite transactional outbox/inbox model with fenced relay leases, retry exhaustion, at-least-once delivery, and consumer deduplication | It does not claim exactly-once delivery to arbitrary external APIs |
| E-009 — Integrated kernel | Contract-driven HTTP runtime, default-deny authorization, tenant-scoped SQLite, durable work, fenced workers, transactional outbox/inbox, wired SQLite authorization audit sink, and Agent inspect/propose/validate/plan gateway | [80 E-009 tests](experiments/e009/README.md) pass in CI, including audit persistence/reopen/concurrency/fail-closed checks and bounded local-agent repair/provenance checks. The separate standalone Qwen3 trial [44081733833](https://github.com/mojtaba-arvin/agent-native/actions/runs/44081733833) reached validation with AN021 after sending an object for the input declarations. The later E-007 three-run study is distinct: its input array was correct, but top-level ir_version and existing operations were missing. This is a single-node semantic integration proof, not a production framework or technology choice |

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
- That a real model can reliably complete the E-009 proposal task: the corrected E-007 artifact shows 0/3 accepted attempts. The first E-007 attempt is an infrastructure-invalid cohort because the Ollama template renderer was misconfigured; the corrected run is a genuine agent-task failure cohort.
- That progressive disclosure improves acceptance, token use, latency, or cost.
- That any candidate has passed an independent hidden acceptance oracle.
- That E-009 is a complete framework: it is one integrated vertical slice with a fixed demo Catalog service, single-node SQLite, and a stdlib reference host.
- That any language, syntax, runtime, protocol, or architecture is superior.
- That the project is production-ready or more secure or performant than existing frameworks.

Mock-provider CI verifies adapter behavior and trace integrity. It is not a real model trial and must not be presented as one.

## Evaluation gates

| Gate | Current assessment |
|---|---|
| G0 — Research integrity | Partially established: one real-agent case, deterministic scorers, source hashes, failure taxonomy, and mock budget fail-fast are implemented; the corrected real-model cohort is 0/3 accepted and requires post-fix revalidation |
| G1 — Agent interface | Not yet passed: requires real repeated model runs and independent acceptance results |
| G2 — Core feasibility | Partial: E-009 proves one integrated contract-driven HTTP/data/job lifecycle; language/compiler/runtime breadth and a general application model remain incomplete |
| G3 — Safety | Default-deny capability checks, tenant filtering, fail-closed durable SQLite authorization audit, bounded HTTP admission, and no-apply Agent interface are integrated/tested; no production identity, remote/tamper-evident audit, isolation, or security audit |
| G4 — Distributed behavior | Partial integration: durable jobs, leases/fencing, stop acknowledgements, outbox relay, and inbox deduplication work in a single SQLite process model; distributed multi-node guarantees remain unproven |
| G5 — Performance | Not passed: the ten-run E-002 matrix is shared-host diagnostic only and every candidate failed the pre-registered CPU gate; representative workloads and controlled hardware are still missing |
| G6 — Production candidate | Not reached |

## Next evidence milestones

1. Inspect the running expanded-budget deterministic follow-up [44149712970](https://github.com/mojtaba-arvin/agent-native/actions/runs/44149712970), preserving temperature 0, seed 42, task, context, Gateway semantics and all scorers.
2. Inspect the resulting raw trace, candidate, validation/plan hashes, scorer outputs, provider usage and Ollama daemon log. If the larger envelope still exhausts, stop and optimize interaction/prompt protocol before any further resource increase. Do not weaken exact preservation or validation gates.
3. Extend E-007 to the public task corpus and a separate evaluator trust boundary/sandbox; then test constrained, general, and advanced model tiers as future work (see [evaluation expansion plan](research/e007-future-evaluation-plan.md)).
4. Run the E-005 paired disclosure pilot with real model/provider usage and independent evaluator results; missing traces or run identities must stop analysis rather than disappear from the sample.
5. Derive any future E-002 CPU gate from a product capacity/cost model before preregistration; then measure controlled-host persistence, authorization, serialization, inter-service, fault-injection and ecosystem criteria. One host-specific artifact-size measurement per candidate is complete, but does not make the matrix decision-grade. No runtime is selected.
6. Extend E-009 with process supervision, remote/tamper-evident audit retention, streaming/cancellation semantics, and versioned service migrations with rollback.
7. Publish raw distributions, uncertainty intervals, failures, and counter-evidence. Keep language/runtime choices open until those comparisons justify a decision.

## Presentation-safe project description

**Agent Native is an independent research and prototyping effort for a backend framework designed around AI agents as primary authors and operators.** It explores service representation, execution substrates, concurrency and failure semantics, capability security, agent-facing interfaces, durable execution, benchmark methodology, and reliable external-effect delivery. The repository contains executable prototypes and reproducible conformance experiments; technology choices remain open pending agent-task, safety, and performance evidence.

This description intentionally distinguishes an ambitious product direction from the current state of implementation.
## Current evidence register

- [Evidence index](research/evidence-index.md) links E-002/E-007/E-009 artifacts and evidence status.
- [Design decisions](research/design-decisions.md) records the Qwen3 cache/determinism, complete-IR contract, validation gate, budget, and CPU-gate findings.
- [CPU-gate analysis](experiments/e002/cpu-gate-analysis.md) explains why the 0.5 s/5k threshold remains a provisional screen rather than a proven product SLO.
- [E-009 IR contract](experiments/e009/ir-contract.md) defines full-snapshot semantics and validation rules.

## Latest implementation verification

E-007 has 51 passing deterministic tests in [workflow 44149051059](https://github.com/mojtaba-arvin/agent-native/actions/runs/44149051059), including per-run budget ineligibility, aggregate cost/time fail-fast, and timeout/HTTP/transport/OOM classification. E-009 has 80 passing tests in [workflow 44128413303](https://github.com/mojtaba-arvin/agent-native/actions/runs/44128413303), including Gateway-owned exact-base preservation and plan gating. E-005 has 17 passing interface tests. These are implementation checks, not real-model acceptance.

See the [evidence index](research/evidence-index.md), [design decisions](research/design-decisions.md), and [second E-002 diagnostic report](experiments/e002/results/2026-11-17-second-ten-run-artifact-diagnostic.md).
