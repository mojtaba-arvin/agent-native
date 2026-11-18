# E-011 — Inter-service invocation and distributed failure semantics

**Status:** research plan only. No transport, broker, database, service mesh, runtime, or deployment technology is selected.

**Numbering:** E-010 is already the isolated sandbox-apply demonstration under `experiments/e010/`. The earlier `e010-interservice-communication-plan.md` filename was a numbering collision; this plan is now E-011.

## Why this experiment exists

E-009 integrates one service, its HTTP host, durable worker, outbox/inbox lifecycle, and Agent Gateway. E-010 demonstrates a private sandbox apply coordinator. E-008 demonstrates at-least-once event delivery and idempotent consumer processing in a single-node reference model.

None of those results proves that two independently running services can safely invoke one another across process, network, identity, and partial-failure boundaries.

E-011 must extend the existing service contract, capability, tenant, task, and outbox/inbox semantics. It must not introduce a second RPC or agent protocol stack.

## Research snapshot — 2026-11-18

The candidate technologies solve different layers. Treating them as interchangeable would create a category error.

| Layer | Candidate / reference | Evidence and useful properties | What it does not establish by itself |
|---|---|---|---|
| Service RPC | gRPC | Typed service definitions, unary and streaming calls, status model, deadlines and cancellation. Deadline propagation can subtract elapsed time to avoid cross-host clock skew. | Business idempotency, transaction outcome, tenant authority, or rollback semantics. The gRPC client has no deadline by default; handlers must cooperate with cancellation. |
| Service RPC | Connect | HTTP-based RPC; unary and client/server/bidirectional streaming; JSON or Protobuf payloads. Unary and one-way streaming patterns work over HTTP/1.1; bidirectional streaming requires HTTP/2. | Durable execution, authorization policy, retries after ambiguous outcomes, or exactly-once effects. |
| Service RPC envelope | JSON-RPC 2.0 | Stateless and transport-agnostic request/response envelope; request IDs correlate responses. | Deadlines, cancellation, service discovery, authorization, idempotency, or reliable notification delivery. A notification has no response and is explicitly unconfirmable. |
| Agent-to-tool/context | MCP | Defines tools, resources, and prompts for LLM applications; uses JSON-RPC messages and per-request capability negotiation in the 2026-07-28 specification. | General internal service RPC or durable business transactions. |
| Agent-to-agent collaboration | A2A | Task-oriented interaction between independent agents, with task/message/artifact models, asynchronous execution, polling, streaming, push updates, and version negotiation. | A replacement for low-level typed service calls between ordinary backend services. |
| Service-invocation layer | Dapr reference | Sidecar-based invocation over HTTP/gRPC with discovery, service-to-service security, retries, tracing, metrics, and access control. | A wire protocol choice: it orchestrates other protocols and adds a deployment/sidecar model. Streaming HTTP requests bypass retries because consumed bodies cannot be replayed. |
| Durable event delivery | E-008 reference model | Transactional outbox/inbox, at-least-once delivery, consumer deduplication and fencing. | Arbitrary exactly-once delivery or exactly-once external side effects. |

### Architectural separation

- **Agent → tool/resource:** MCP is a relevant interoperability candidate.
- **Agent ↔ agent:** A2A is a relevant task-collaboration candidate.
- **Service → service operation:** gRPC, Connect, JSON-RPC-over-a-transport, or a future alternative are candidates to compare.
- **Service → service event:** E-008's outbox/inbox semantics are the starting reference.
- **Discovery/resiliency/observability layer:** Dapr is a reference architecture, not a transport protocol.

The A2A project itself distinguishes MCP's tool/resource integration from A2A's peer-agent collaboration. This distinction is useful, but it does not imply that either protocol should become the framework's internal service RPC.

### Source set

- [gRPC core concepts](https://grpc.io/docs/what-is-grpc/core-concepts/)
- [gRPC deadlines](https://grpc.io/docs/guides/deadlines/)
- [gRPC cancellation](https://grpc.io/docs/guides/cancellation/)
- [Connect protocol reference](https://connectrpc.com/docs/protocol/)
- [JSON-RPC 2.0 specification](https://www.jsonrpc.org/specification)
- [MCP specification — 2026-07-28](https://modelcontextprotocol.io/specification/2026-07-28)
- [A2A specification](https://a2a-protocol.org/latest/specification/)
- [A2A and MCP comparison](https://a2a-protocol.org/latest/topics/a2a-and-mcp/)
- [Dapr service invocation overview](https://docs.dapr.io/developing-applications/building-blocks/service-invocation/service-invocation-overview/)

These sources are a protocol survey, not a technology recommendation. Accessed 2026-11-18.

## Questions to answer

1. **Synchronous calls:** Can a service invoke another service operation through a declared contract, with typed input/output, authenticated caller identity, capability authorization, deadline propagation, cancellation, and stable error mapping?
2. **Unknown outcomes:** If the callee commits an effect but the response is lost, can the caller distinguish a definite failure from an unknown outcome and reconcile safely?
3. **Retry safety:** Which failures are known to occur before dispatch, which may occur after dispatch, and which operations are safe to replay with an idempotency key?
4. **Identity and authority:** Which principal is acting, on whose behalf, for which tenant, and with which attenuated capability? Caller-supplied identity fields must never become authority.
5. **Backpressure:** How are bounded concurrency, per-tenant quotas, queue admission, and overload responses enforced across process boundaries?
6. **Cancellation:** Does cancellation propagate to downstream calls? Is completion acknowledged? Is worker capacity retained until work has actually stopped? What happens if an irreversible effect already committed?
7. **Asynchronous events:** Can a producer commit local state and an outbox event atomically, deliver at least once, and let a remote consumer deduplicate and apply its local effect atomically?
8. **Evolution:** How are operation and event contracts versioned without silent downgrade or incompatible deployed consumers?
9. **Streaming:** What happens when a client disconnects after partial request or response consumption? Which streams are replayable, resumable, or explicitly non-retryable?

## Transport-neutral semantic envelope (hypothesis, not a wire format)

The first artifact should specify semantics independently of a protocol. Candidate fields:

- `request_id`: correlation for one attempt/response; not an idempotency key.
- `parent_call_id`: causal parent for nested service calls.
- `caller_service_id`, `callee_service_id`, `operation_id`, and pinned `contract_version`.
- `tenant_scope`: a routing/partition scope, checked against authenticated authority rather than trusted as a credential.
- `authenticated_principal`: derived from the authenticated transport peer or verified token, never accepted as an unsigned caller assertion.
- `delegated_capability_ref`: a verifiable, attenuated grant bound to principal, tenant, operation, resource scope, and expiry.
- `remaining_timeout_ms`: a remaining duration budget, not a wall-clock deadline copied unchanged across machines.
- `idempotency_key`: required for retryable operations with effects; stored with the canonical request identity and terminal outcome.
- `attempt`: diagnostic attempt number; never sufficient to authorize a replay.
- `trace_context`: causal tracing metadata with bounded size and no secrets.
- `payload`: contract-validated input, with streaming/replay properties declared separately.

The semantic result must distinguish at least:

- `rejected_before_dispatch`
- `accepted_or_in_progress`
- `completed`
- `failed_before_effect`
- `cancelled_and_stopped`
- `outcome_unknown_after_dispatch`

A generic timeout must not be treated as proof that the callee did not execute. A transport cancellation is a request to stop work, not a distributed rollback. If an effect may already have committed, the caller must reconcile by idempotency key or a dedicated status operation rather than blindly retrying.

## Minimal experiment boundary

Only after E-007 real-agent acceptance and review of E-010's sandbox-apply evidence:

1. Define the transport-neutral call envelope, outcome state machine, retry classification, and trust boundary.
2. Start two independently running service processes with separate state stores and explicit service identities.
3. Implement one declared synchronous operation in Service A that invokes Service B.
4. Implement one producer-side state change that emits a versioned event through an outbox, and one remote consumer with an inbox/deduplication boundary.
5. Add deterministic fault injection at: before receive, after admission, before commit, after commit but before response, during response streaming, and during consumer processing.
6. Keep the first harness technology-neutral and executable with the existing reference host where practical. Do not select a production broker, database, service mesh, or deployment platform.

## Required evidence and tests

- Canonical contract/IR for both services and the event, with explicit compatibility rules.
- Reproducible two-process runner and separate state stores; no in-process worker may count as multi-process evidence.
- Authorized and denied calls, tenant isolation, capability attenuation, invalid service identity, and unsupported contract version.
- Deadline propagation that subtracts elapsed time; downstream cancellation propagation; no premature release of worker capacity before stop acknowledgement.
- Timeout before dispatch is distinguishable from response loss after commit.
- A retry with the same idempotency key produces one logical effect; a retry with a different key is a distinct operation.
- Retry exhaustion, overload admission, bounded concurrency, and per-tenant fairness.
- Duplicate request and event delivery; consumer crash before/after commit; stale lease/fencing; restart recovery.
- Stream disconnect and partial-body tests; no automatic replay of a consumed non-replayable stream.
- Causal traces across both processes without credentials or raw capability tokens.
- p50/p95 latency, throughput, bytes, memory, CPU, retry count, cancellation completion time, and unknown-outcome rate for the reference harness.
- A decision record that separates semantic guarantees from adapter-specific behavior.

## Non-goals

- No exactly-once claim for arbitrary remote side effects.
- No distributed transaction or global ACID claim.
- No production-ready service discovery or orchestration.
- No transport or broker bake-off before the semantic envelope and failure tests exist.
- No use of MCP or A2A as a shortcut for internal service RPC without evidence that the required semantics fit.
- No implementation of this experiment before E-007 acceptance and E-010 sandbox-apply review.

## Exit condition

E-011 is complete only when two independently running services can perform the synchronous and asynchronous flows, survive the specified injected failures, and produce reproducible evidence. Only then should candidate transports and persistence substrates be compared. A protocol selection requires a separate decision record and measured evidence.
