# Design Space and Research Questions

This document defines the decisions that must be resolved through evidence. It does not preselect a language or runtime.

## 1. Programming model

Candidates:
- declarative service and dataflow specification;
- typed imperative language with agent-oriented constraints;
- purpose-built backend language;
- compact DSL compiled to a lower-level language or bytecode;
- hybrid: declarative contracts plus restricted imperative functions.

Questions:
- What is the smallest complete set of concepts an agent must learn?
- Can common CRUD, event, workflow, and streaming services be expressed without escape hatches?
- Can effects, ownership, retries, transactions, and authority be made explicit?
- Can syntax reduce ambiguity and repair loops without becoming too restrictive?
- Is textual syntax optimal, or should a canonical structured representation be primary with generated textual views?

## 2. Language and compiler

Candidates to compare include (not limited to) Rust, Go, Zig, OCaml, Gleam, Elixir, WebAssembly-oriented toolchains, and a purpose-built language. Compare the language used to implement the runtime separately from the language used to define services.

Questions:
- Which implementation language gives the best safety/performance/development trade-off for the core?
- Which service language gives the best agent success rate and lowest total task cost?
- Is a custom compiler justified by measurable improvements?
- Can diagnostics be stable, localized, machine-actionable, and repairable?
- How do compile times, binary sizes, cold starts, and cross-compilation compare?

## 3. Runtime and execution

Evaluate native process runtime, bytecode VM, WASM component runtime, actor runtime, and hybrid designs.

Required semantics to specify:
- process and service lifecycle;
- request/event/task execution;
- structured concurrency and cancellation;
- bounded resource use and backpressure;
- deadlines, retries, idempotency, and timeouts;
- panic/fault containment and supervision;
- graceful shutdown and draining;
- deterministic test and replay facilities.

## 4. Distributed architecture

The framework must own coherent semantics for:
- service identity and discovery;
- typed request/response and event contracts;
- transport selection and version negotiation;
- deadlines and cancellation propagation;
- retries and duplicate delivery;
- idempotency and deduplication;
- transactional boundaries and outbox/inbox patterns;
- schema evolution and compatibility;
- service health and load shedding.

Do not equate microservices with mandatory network calls. Support modular deployment boundaries and avoid forcing distribution where it harms correctness or performance.

## 5. Data model

Compare embedded and external persistence approaches without binding the framework to one database. Specify:
- typed schemas and constraints;
- migrations and rollback/forward repair;
- transaction semantics;
- query representation and safe parameterization;
- connection/resource pools;
- tenant isolation;
- consistency and concurrency behavior;
- generated data access vs explicit queries.

## 6. Security and authority

Security must be enforced by trusted components:
- deny-by-default capability grants;
- least-privilege service identities;
- explicit effects for network, filesystem, database, secrets, and process access;
- isolation boundaries and resource quotas;
- authentication and authorization policy semantics;
- audit events and provenance;
- safe handling of untrusted input and tool-produced data.

Never rely on generated code comments, prompts, or agent self-restraint as security controls.

## 7. Agent interface

Evaluate a canonical machine-readable intermediate representation, text syntax, CLI, language server, compiler API, and runtime introspection. Tool interfaces must be deterministic and narrow. Avoid requiring an agent to read large documentation sets to discover valid operations.

## 8. Performance

Measure at minimum:
- p50/p95/p99 request latency;
- throughput under fixed concurrency;
- CPU and peak RSS;
- startup and shutdown time;
- build/compile time;
- binary/artifact size;
- allocation and GC behavior where applicable;
- tail latency under dependency degradation;
- overhead of safety, tracing, and policy enforcement.

## 9. Mandatory workload set

All candidates must implement equivalent workloads:
1. health/readiness and typed HTTP request;
2. CRUD with validation, transaction, and migration;
3. authenticated multi-tenant API with object-level authorization;
4. service-to-service call with deadline, retry, idempotency;
5. event-driven workflow with durable delivery and replay;
6. long-running task with cancellation and bounded concurrency;
7. streaming response;
8. failure injection and recovery;
9. schema/API evolution without downtime.

## 10. Decision discipline

A design choice remains open until:
- alternatives are listed;
- criteria and weights are defined before the experiment;
- equivalent workloads are implemented;
- correctness and security tests pass;
- agent task cost and runtime cost are measured;
- results are reproducible;
- limitations and negative results are recorded.

The project is allowed to conclude that a purpose-built language is necessary, or that a hybrid architecture is superior. Neither conclusion may be assumed.
