# Agent Native v0.1 Product Contract

**Status:** Target product contract for v0.1. This document specifies the acceptance target; it is not a claim that the implementation is complete or production-ready.

## Product identity and primary user

Agent Native is an independent backend framework. **AI agents are the primary authors and operators** of services built with it. Human owners remain accountable for product and operational decisions, but the framework must not depend on an agent guessing implicit conventions or compensating for unsafe runtime behavior.

The product is the framework's own service model and execution system. It is not a wrapper, adapter, framework manager, prompt pack, or code generator that delegates its core semantics to an existing backend framework. Trusted contracts and runtime components—not prompts or generated comments—define what a service may do.

## v0.1 objective

The v0.1 target is a **single PostgreSQL-backed service**: one independently deployable service that exposes a declared HTTP API and persists its authoritative application state in PostgreSQL.

This is the smallest useful product boundary for proving that the framework can describe, validate, execute, secure, persist, and operate a real backend service. It is a vertical-slice target, not a claim that every distributed-system capability in the long-term vision is included in v0.1.

## Single-service boundary

The v0.1 deployment boundary contains:

- One independently deployable Agent Native service.
- Its declared service contract, operations, routes, and policy.
- One logical PostgreSQL database as the authoritative production persistence target.
- The trusted host/runtime components needed to validate, authorize, execute, and observe that service.

The service may be internally modular, but the v0.1 product does not require multiple independently deployed Agent Native services or a distributed control plane. Internal module boundaries must not be confused with a multi-service deployment topology.

**PostgreSQL is the authoritative production persistence target.** SQLite and other stores may remain useful as experiment or reference substrates, but passing an experiment against them does not satisfy the v0.1 production persistence requirement. Hosting vendor, topology, and managed-versus-self-hosted operation are not selected here.

## User-visible behavior

### Agent authoring and verification

An agent building or changing a service must be able to:

1. Discover the service's declared contract and the operations available to it.
2. Validate service definitions and proposed changes before relying on them.
3. Receive deterministic, machine-readable diagnostics for invalid contracts, inputs, or operations.
4. Inspect the effective service contract and relevant runtime state without causing application side effects.
5. Distinguish validation and planning from execution. An inspection, proposal, validation, or plan operation must not silently apply a change.

The exact service representation and its schema are established by the versioned contract work in T03; this document does not preselect a textual language, DSL, or IR encoding.

### HTTP API client

An external client must be able to call declared HTTP operations using their specified methods, routes, and typed inputs. The service must validate requests against the declared contract and must not dispatch malformed or unauthorized requests to application handlers.

Success and failure behavior must be deterministic and testable. Unknown routes, invalid inputs, authentication or authorization failures, conflicts, resource exhaustion, and unexpected internal failures must have explicit response behavior rather than relying on incidental framework defaults. Exact status codes, response shapes, and failure cases are frozen and tested by the HTTP conformance work in T04.

### Human operator

An operator must be able to determine whether the service is healthy, observe relevant operational metrics, understand bounded-resource behavior, and stop the service without abandoning in-flight work or corrupting durable state. Health, metrics, limits, and graceful-shutdown behavior are part of the product boundary, not optional deployment polish.

## Data and persistence boundary

PostgreSQL is the production persistence target for v0.1. Persistent state must be protected by database-enforced constraints and transactions appropriate to the operation. Tenant-scoped reads and writes must enforce scope in the persistence boundary; filtering unauthorized rows only after fetching them is not an acceptable isolation mechanism.

Schema evolution must be tied to the versioned service representation and have executable validation. Where an operation changes application data, its corresponding audit record and outbox record must commit atomically when required by the operation contract. Crash testing must demonstrate that a process interruption cannot leave those records in a contradictory partial state.

Outbox delivery is not a promise of exactly-once execution against arbitrary external systems. The supported contract must state the delivery guarantee, preserve retry and failure evidence, and use idempotent consumer-side handling where applicable.

## Security and authority

Security decisions must be enforced by trusted runtime or host components:

- Authorization is default-deny. An operation without a valid grant is rejected.
- A caller cannot grant itself capabilities by supplying principal, tenant, role, or grant fields in an untrusted request.
- Identity and tenant context come from a trusted authentication boundary; capability grants come from a trusted policy source.
- Operations declare the effects and capabilities they require. Unknown or undeclared effects fail closed.
- Audit of security-relevant decisions is part of the trusted execution path and must fail closed when its required durable write cannot be completed.
- Resource limits and cancellation boundaries are enforced outside agent instructions.

A prompt, generated source comment, or agent assertion is never an authorization control.

## Explicit non-goals

The v0.1 single-service target does not require:

- A multi-service deployment topology, service mesh, distributed service discovery, or multi-region control plane.
- A general deployment orchestrator or framework-management platform.
- Multiple production persistence backends; PostgreSQL is the target for this release boundary.
- Exactly-once delivery guarantees for arbitrary external APIs.
- A graphical administration product or a broad integration marketplace.
- Compatibility layers that make an existing backend framework the owner of Agent Native's service model or runtime semantics.
- Premature selection of a programming language, syntax, compiler, or runtime based on familiarity or popularity.

These exclusions limit the first verifiable product slice; they do not prohibit later research or expansion of the framework's distributed-systems capabilities.

## Acceptance criteria

v0.1 acceptance is conjunctive: every applicable gate below must pass. A skipped check, an unmeasured property, a passing prototype, or a weighted average cannot substitute for a required result. The acceptance scripts and evidence for each task are the executable record.

| Gate | Required evidence | Task |
|---|---|---|
| SLO and resource envelope | Define measurable SLOs, resource limits, hard gates, and the runtime-selection rule before candidate measurements. | T02 |
| Versioned service contract | Freeze the v1 IR schema and compatibility rules; validate them with executable positive and negative cases. | T03 |
| HTTP behavior | Pass black-box positive, negative, and failure-contract tests against the Python reference. | T04 |
| PostgreSQL conformance | Demonstrate storage conformance and deterministic operation-trace parity against the reference behavior. | T05 |
| Reference implementation | Run the Python reference against PostgreSQL and demonstrate T04 trace parity. | T06 |
| Runtime candidates and selection | Complete Go and Rust spikes, measure candidates on a controlled host with the required repetitions and non-Python load generator, then record a decision using the pre-registered T02 rule. CI smoke results alone are not decision-grade. | T07–T10 |
| Production core | Implement the production IR loader and router and demonstrate catalog/inventory contract parity on PostgreSQL. | T11 |
| Authentication and capabilities | Enforce identity and capability checks with default-deny behavior and negative authorization tests. | T12 |
| Atomic persistence and recovery | Commit data, audit, and outbox atomically; apply migrations from IR; pass crash-recovery testing including process termination. | T13 |
| Service operations | Provide executable health, metrics, bounded-resource, and graceful-shutdown behavior. | T14 |
| Reproducible delivery | Produce a production container image, SBOM, and reproducible build path with verification evidence. | T15 |
| Controlled-host SLO result | Run the agreed workload on a controlled host and preserve raw measurements showing pass/fail against the T02 envelope. | T16 |
| Hardening | Resolve security, reliability, resource-exhaustion, and operational findings with regression and failure-contract tests. | T17 |
| Pilot | Run the pilot against PostgreSQL and record deployment configuration, acceptance evidence, and operational findings. | T18 |

T19's nightly acceptance and process-ratio reporting sustains regression visibility after task delivery; it does not replace any product acceptance gate above.

No production-readiness or performance claim is justified until the required evidence exists. In particular, shared-runner smoke measurements, prototype results, or skipped manual measurements must not be represented as controlled-host SLO acceptance.

## Decisions deliberately left open

This contract fixes the v0.1 product boundary and production persistence target; it does not choose the implementation:

- The implementation language, service syntax, compiler strategy, and execution runtime are not preselected. T07–T10 must resolve runtime candidates using the T02 rule and controlled measurements.
- The exact versioned service representation and compatibility semantics are established in T03.
- HTTP is the externally visible API boundary, while its complete status, payload, and failure contract is established in T04.
- Numeric SLOs and resource thresholds must come from T02 before the controlled measurements in T09 and T16; this document invents no thresholds.
- PostgreSQL is required for production conformance, but no hosting vendor, deployment topology, or managed database service is selected here.

Any later change to these product boundaries must be explicit, evidence-backed, and made through the repository's decision process. It must not be introduced by silently weakening an acceptance threshold or treating an unmeasured requirement as satisfied.
