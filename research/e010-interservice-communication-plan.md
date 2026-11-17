# E-010 — Inter-service communication and distributed failure semantics

**Status:** research plan only. No transport, broker, database, or deployment technology is selected.

## Why this experiment exists

E-009 integrates one service, its HTTP host, durable worker, and outbox/inbox lifecycle inside one process. E-008 demonstrates at-least-once delivery and idempotent consumer processing in a single-node SQLite reference model. Neither proves that two independently running services can communicate safely across process and failure boundaries.

E-010 is the next vertical slice after the real-model E-009 Agent trial is accepted. It must extend the existing contract and capability model rather than introduce a parallel RPC framework.

## Questions to answer

1. **Synchronous calls:** Can a service invoke another service operation through a declared contract, with typed input/output, capability authorization, deadline propagation, cancellation, and stable error mapping?
2. **Asynchronous events:** Can a producer commit local state and an outbox event atomically, deliver it at least once, and let a remote consumer deduplicate and apply its local effect atomically?
3. **Identity and authority:** Which principal is acting, on whose behalf, for which tenant, and with which narrowly scoped capability? Caller-supplied identity fields must never become authority.
4. **Failure behavior:** What happens on timeout, remote process death, duplicate request, duplicate event, stale lease, partial response, retry exhaustion, and backpressure?
5. **Evolution:** How are operation and event contracts versioned without silently breaking deployed consumers?

## Minimal experiment boundary

Use two independently started service processes with separate local databases and explicit service identities. Keep the first implementation technology-neutral and executable with the existing reference host where practical. Do not select a production broker, database, service mesh, or deployment platform in this experiment.

Implement only:
- one declared synchronous operation in Service A that calls Service B;
- one producer-side state change that emits a versioned event through an outbox;
- one remote consumer with an inbox/deduplication boundary;
- explicit request/event IDs, tenant scope, capability checks, deadline, retry policy, and correlation/trace context;
- restart and fault-injection tests across process boundaries.

## Required evidence

- contract and canonical IR for both services and the event;
- reproducible two-process runner with separate state stores;
- tests for authorized and denied calls, tenant isolation, timeout/deadline propagation, remote unavailable, retry exhaustion, duplicate request idempotency, duplicate event delivery, consumer crash before/after commit, and stale relay fencing;
- traces that show causal request/event relationships without leaking credentials;
- measured latency and resource usage for the reference transport;
- a decision record separating proven semantics from transport-specific behavior.

## Non-goals

- no exactly-once claim for arbitrary remote side effects;
- no distributed transaction or global ACID claim;
- no production-ready service discovery or orchestration;
- no premature transport or broker bake-off before the semantic envelope and failure tests exist;
- no reuse of the in-process E-009 worker as evidence of multi-process correctness.

## Exit condition

E-010 is complete only when two independently running services can perform the synchronous and asynchronous flows, survive the specified injected failures, and produce reproducible evidence. Only then should candidate transports and persistence substrates be compared.
