# E-004 threat model (working draft)

**Status:** active research. This document defines the threat boundary for the future framework; it is not a claim that the current prototype mitigates every threat.

## System under consideration

Agent Native is an independent backend framework. AI agents author service definitions and propose changes. A trusted compiler, policy engine, runtime, and host enforce accepted contracts. The agent, its prompts, repository content, generated definitions, and external inputs are untrusted. Existing backend frameworks do not own the service model or runtime.

## Assets

1. Tenant business data and derived data.
2. Authentication credentials, capability grants, signing keys, and secrets.
3. Service definitions, canonical IR, compiler artifacts, and migration plans.
4. Runtime integrity, host resources, and service availability.
5. Inter-service messages, idempotency records, and durable workflow state.
6. Security decisions and audit records.
7. Production deployment state and external systems reached through effects.

## Actors

- Authorized human developer/operator.
- AI agent acting with explicitly delegated authority.
- Compromised or malicious agent, including one influenced by prompt injection.
- Unauthenticated or authenticated external client.
- Malicious tenant or cross-tenant attacker.
- Compromised worker or service process.
- Malicious or compromised dependency/build artifact.
- Infrastructure/operator identity with privileged access.

## Trust boundaries

| Boundary | Untrusted side | Trusted enforcement point | Required property |
|---|---|---|---|
| Agent ↔ compiler | Prompts, generated source, repository text, tool output | Parser, type checker, policy validator | Agent proposals never grant authority |
| Source ↔ canonical IR | Imported or generated IR | Schema and semantic validator | Reject malformed, unknown, or widened contracts |
| Service code ↔ effects | Service logic and agent-authored operations | Runtime effect broker | Every effect is declared and capability-checked |
| Principal ↔ tenant data | Client-supplied tenant/resource identifiers | Authenticated identity and tenant-aware data layer | Tenant context cannot be selected by untrusted input |
| Guest ↔ host | Component/native guest code | Host sandbox and resource policy | Explicit filesystem, network, clock, and resource authority |
| Service ↔ secrets | Application code and logs | Secret broker / scoped secret handle | No ambient environment-wide secret access |
| Service ↔ service | Messages, retries, event payloads | Authenticated channel and contract validator | Identity, tenant, deadline, and idempotency propagate |
| Build ↔ production | Artifacts, dependencies, migration plans | CI policy and human approval gate | Unreviewed agent output cannot deploy or destroy data |

## Entry points

- Textual DSL and structured IR imports.
- Schema and migration definitions.
- HTTP requests, event messages, and streaming inputs.
- Inter-service calls and retries.
- Declared effects: persistence, filesystem, network, secrets, process execution, and external APIs.
- Dependency manifests, compiler plugins, and build artifacts.
- Runtime configuration, policy updates, and deployment manifests.
- Logs, traces, metrics, and diagnostic payloads.

## Abuse cases and required controls

| Abuse case | Threat | Required mitigation | Current evidence / gap |
|---|---|---|---|
| Prompt injection in repository or tool output | Agent proposes privileged or malicious service behavior | Treat all agent output as untrusted; compiler/runtime enforce explicit policy | Agent contract exists; adversarial end-to-end tests pending |
| Capability escalation | Agent widens authority through generated IR or delegation | Deny by default; validated contracts; monotonic attenuation | E-004 tests missing grants and scope/expiry widening |
| Cross-tenant confused deputy | Valid principal uses another tenant's resource | Principal- and tenant-bound grants; tenant context from trusted identity | E-004 tenant mismatch test; storage-layer isolation pending |
| Resource path confusion | Prefix matching grants access to sibling paths | Canonical resource identifiers and segment-aware scope checks | E-004 path-boundary and traversal tests |
| Expired grant replay | Old authority is reused | Trusted clock, expiry check, bounded token lifetime, revocation | E-004 expiry test; clock and distributed revocation pending |
| Undeclared side effect | Service performs network/write/secret action not in contract | Effect typing and runtime broker checks | E-004 undeclared-effect test; integration with runtime pending |
| Secret exfiltration | Secret appears in output, logs, traces, or agent context | Scoped handles, redaction, non-serializable secret types, audit without values | Design only |
| Network exfiltration | Service sends tenant data to arbitrary destinations | Default-deny egress, destination policy, DNS/IP rebinding defenses | Design only |
| Resource exhaustion | Agent creates unbounded tasks, streams, memory, or retries | Hard runtime quotas, backpressure, deadlines, cancellation, retry budgets | E-003 reference model; OS/runtime enforcement pending |
| Duplicate/replayed events | Repeated effects corrupt data or double-charge | Durable idempotency, atomic effect/ledger boundary, authenticated message identity | E-003 in-memory model only |
| Malicious dependency/artifact | Supply-chain compromise at build or runtime | Lockfiles, provenance, signature verification, allowlists, reproducible builds | Toolchain pins/lockfiles added; artifact attestation pending |
| Worker compromise | Compromised worker pivots to host or other tenants | Process/component isolation, least authority, bounded IPC | Runtime substrate experiment pending |
| Audit tampering | Attacker erases or forges security evidence | Append-only authenticated audit pipeline, external retention | E-004 emits in-memory events only |

## Human approval gates

The framework must not infer approval from agent-generated text. A trusted policy and explicit human approval are required before:

- Production deployment or promotion.
- Destructive or irreversible schema/data migration.
- Granting new principals, widening capability scope, or increasing delegation depth.
- Enabling broad network egress or access to high-impact external systems.
- Reading, exporting, rotating, or deleting production secrets.
- Raising hard resource quotas beyond an approved budget.
- Publishing a release or changing trusted build/release credentials.

The current repository does not enable these execution paths.

## Residual risks and open decisions

- Cryptographic representation, signing, rotation, and revocation of capability grants.
- Trusted identity establishment and propagation across services.
- Database row-level enforcement and isolation under connection pooling.
- Atomicity between authorization, idempotency, durable state, and external side effects.
- Filesystem/network sandbox design and host escape risk.
- Secret lifetime, memory exposure, and diagnostic redaction.
- Time source trust, clock skew, and revocation latency.
- Side channels, kernel/runtime vulnerabilities, and supply-chain compromise.
- Audit integrity, retention, privacy, and tenant separation.
- Safe migration planning, rollback, and human approval UX.

No single sandbox, WASI runtime, prompt, or language type system is assumed to solve the complete threat model.
