# E-004 Security Threat Model

**Status:** executable reference authorization model plus partial runtime enforcement prototypes. This document is a threat model and control boundary, not a production security certification.

## Security objective

Agent-authored source, prompts, repository content, structured IR, tool output, dependencies, and external inputs are untrusted. A model cannot grant itself authority. The compiler, runtime, host, persistence adapters, and other trusted components must independently enforce authorization at every effect boundary. Unknown, malformed, unauthenticated, expired, revoked, out-of-scope, or unverifiable authority is denied.

The E-004 Python policy model is a reference contract. E-009 demonstrates a runtime integration. Neither prototype alone establishes production readiness.

## Assets

1. Tenant data, personal/customer records, business records, and data integrity.
2. Credentials, signing keys, scoped secret handles, and secrets.
3. Service definitions, canonical IR, compiler artifacts, dependency manifests, and migration plans.
4. Runtime integrity, host resources, process boundaries, and service availability.
5. Inter-service messages, idempotency records, durable workflow state, and external effects.
6. Security decisions, audit records, and incident evidence.
7. Production deployment state, infrastructure, and external systems reached through effects.
8. Workload identities, authorization grants, revocation state, and approval records.

## Actors

- Authorized human developer/operator.
- AI agent acting with explicitly delegated authority.
- Compromised or malicious agent, including one influenced by prompt injection.
- Unauthenticated or authenticated external client.
- Malicious tenant or cross-tenant attacker.
- Compromised worker or service process.
- Malicious or compromised dependency/build artifact.
- Infrastructure/operator identity with privileged access.
- Compromised identity, token-issuing, audit, or policy service.

## Trust boundaries and mandatory enforcement

| Boundary | Untrusted side | Trusted enforcement point | Required property |
|---|---|---|---|
| Agent ↔ compiler | Prompts, generated source, repository text, tool output | Parser, type checker, policy validator | Agent proposals never grant authority |
| Source ↔ canonical IR | Imported or generated IR | Schema and semantic validator | Reject malformed, unknown, or widened contracts |
| Service code ↔ effects | Service logic and agent-authored operations | Runtime effect broker | Every effect is declared and capability-checked before execution |
| Principal ↔ tenant data | Client-supplied tenant/resource identifiers | Authenticated identity and tenant-aware data layer | Tenant context cannot be selected by untrusted input |
| Token ↔ runtime | Bearer token and claims | Trusted token verifier, key custody, revocation lookup | Signature, issuer, audience, time, identity, scope, and revocation are checked |
| Workload ↔ service | Process/service identity and transport peer | Workload identity provider and authenticated channel | Caller workload is independently authenticated and propagated |
| Guest ↔ host | Component/native guest code | Host sandbox and resource policy | Explicit filesystem, network, clock, process, and resource authority |
| Service ↔ secrets | Application code and logs | Secret broker / scoped secret handle | No ambient environment-wide secret access |
| Service ↔ network | Application destinations, DNS, redirects | Default-deny egress broker | Only approved destinations/protocols are reachable |
| Service ↔ service | Messages, retries, event payloads | Authenticated channel and contract validator | Identity, tenant, deadline, and idempotency propagate |
| Runtime ↔ storage | Queries, tenant IDs, pooled DB connections | Database-enforced tenant isolation | Every read/write is tenant-scoped at the storage boundary |
| Runtime ↔ audit | Audit events and transport | Authenticated append-only audit sink | Decisions are durable, tamper-evident, and independently retained |
| Build ↔ production | Artifacts, dependencies, migration plans | CI policy and human approval gate | Unreviewed agent output cannot deploy or destroy data |

Authorization is evaluated by trusted code using a trusted identity context and trusted time. Model messages, prompt text, tool output, request bodies, and client-controlled headers are never accepted as authorization evidence.

## Entry points

- Textual DSL and structured IR imports.
- Schema and migration definitions.
- HTTP requests, event messages, and streaming inputs.
- Inter-service calls and retries.
- Declared effects: persistence, filesystem, network, secrets, process execution, and external APIs.
- Dependency manifests, compiler plugins, and build artifacts.
- Runtime configuration, policy updates, token issuance, and deployment manifests.
- Logs, traces, metrics, and diagnostic payloads.
- Agent proposals, tool results, repository instructions, retrieved documents, and other prompt-injection carriers.

## Abuse cases and required controls

| Abuse case | Threat | Required mitigation | Current evidence / gap |
|---|---|---|---|
| Prompt injection in repository or tool output | Agent proposes privileged or malicious service behavior | Treat all agent output as untrusted; compiler/runtime enforce explicit policy; adversarial end-to-end tests | E-009 Gateway exposes inspect/propose/validate/plan and no apply; prompt-injection integration tests pending |
| Capability escalation | Agent widens authority through generated IR or delegation | Deny by default; validated contracts; immutable allowlists; monotonic attenuation | E-004 negative tests cover missing grants, undeclared effects, scope/expiry widening, and malformed inputs |
| Forged or replayed capability | Attacker edits claims or reuses stolen bearer token | Authenticated short-lived token; bounded TTL; key custody; revocation and replay policy | Core has HMAC-SHA256 signed tokens with issuer/audience/expiry validation and tests; no revocation identifier/store or distributed revocation protocol |
| Cross-tenant confused deputy | Valid principal uses another tenant's resource | Principal- and tenant-bound grants; tenant context from trusted identity; storage-layer isolation | E-004 tenant mismatch test; E-009 SQLite query-scoping tests; production PostgreSQL isolation/RLS proof remains a gate |
| Resource path confusion | Prefix matching grants access to sibling paths or encoded traversal | Canonical NFC, unescaped resource paths; reject percent escapes, backslashes, controls, dot segments, and ambiguous separators; segment-aware scope checks | E-004 boundary, traversal, percent-encoding, Unicode-normalization, and backslash tests |
| Expired grant replay | Old authority is reused | Trusted clock, expiry check, bounded token lifetime, revocation | E-004 expiry and token-expiry tests; distributed revocation and clock-skew operations remain pending |
| Undeclared side effect | Service performs network/write/secret action not in contract | Effect typing and runtime broker checks | E-004 undeclared-effect test; E-009 checks declared effects before handlers; a complete host effect broker is not implemented |
| Secret exfiltration | Secret appears in output, logs, traces, or agent context | Scoped handles, redaction, non-serializable secret types, audit without values | Environment-only server secrets are present; no general secret broker or complete redaction proof |
| Network exfiltration | Service sends tenant data to arbitrary destinations | Default-deny egress, destination policy, DNS/IP rebinding defenses | No production egress broker; broad egress remains prohibited pending explicit human approval and implementation |
| Resource exhaustion | Agent creates unbounded tasks, streams, memory, or retries | Hard CPU/memory/process/storage quotas, backpressure, deadlines, cancellation, retry budgets | E-009 has bounded HTTP admission/body/read timeouts and queue backpressure; hard per-workload and per-tenant resource quotas remain absent |
| Duplicate/replayed events | Repeated effects corrupt data or double-charge | Durable idempotency, atomic effect/ledger boundary, authenticated message identity | E-003/E-009 prototype tests; no general arbitrary external API exactly-once guarantee |
| Malicious dependency/artifact | Supply-chain compromise at build or runtime | Lockfiles, provenance, signature verification, allowlists, reproducible builds | Toolchain pins/lockfiles exist; artifact attestation and production admission policy remain incomplete |
| Worker compromise | Compromised worker pivots to host or other tenants | Process/component isolation, least authority, bounded IPC, resource limits | E-010 sandbox-apply is a demonstration; production sandbox boundary and escape tests pending |
| Audit tampering | Attacker erases or forges security evidence | Append-only authenticated audit pipeline, integrity protection, external retention | E-009 durable SQLite audit fails closed and blocks application handler on sink failure; DB triggers are not cryptographic tamper evidence or remote replication |
| Workload impersonation | Caller supplies another service's principal/tenant identity | Workload attestation, mTLS/channel binding, trusted identity propagation | Signed claims bind a principal and tenant, but workload attestation and service-to-service identity propagation are not implemented |
| Revoked authority remains usable | Cached tokens survive revocation | Authoritative revocation state, bounded cache TTL, fail-closed lookup, measurable propagation bound | No revocation store, token identifier, or propagation protocol; production execution remains gated |
| Sandbox escape / ambient host access | Guest reaches host filesystem, process, credentials, or network | OS/container/WASM boundary selected by evidence; syscall and filesystem policy; escape tests | No production sandbox selection or enforcement; E-010 is not a production boundary |

## Existing executable enforcement and its limits

| Capability | Observed implementation | Evidence | What it does not prove |
|---|---|---|---|
| Default-deny policy | E-004 PolicyEngine checks principal, tenant, capability, expiry, resource scope, and declared effects | `experiments/e004/test_security_model.py` | Cryptographic grant provenance or production deployment safety |
| Signed capability token | Core CapabilityTokenAuthority signs/verifies HMAC-SHA256 tokens; validates issuer, audience, expiry, claims, grant identity, and TTL | `experiments/e004/test_capability_tokens.py` | Revocation, key rotation, asymmetric issuer separation, workload attestation, or a production key-management service |
| Runtime authorization | E-009 authorizes before calling application handlers; identity is supplied by a separate trusted dependency, not request payloads | `experiments/e009/test_kernel.py` | A general host effect broker for arbitrary code |
| Tenant data access | E-009 SQLite repository includes tenant IDs in lookup predicates | `experiments/e009/test_repository.py`, `test_kernel.py` | PostgreSQL RLS, pooled-connection reset safety, or production cross-tenant isolation |
| Audit | E-009 audit sink is durable; failures deny before handler execution; write operations can require an atomic audit receipt | `experiments/e009/test_kernel.py` and E-009 audit tests | Cryptographic tamper evidence, remote replication, retention immutability, or independent audit identity |
| HTTP admission | E-009 host bounds request body, concurrency, and request read time | E-009 host tests | CPU/memory/process/storage quotas or egress isolation |
| Agent proposal path | E-009 Agent Gateway supports inspect/propose/validate/plan; apply is disabled | E-009 Gateway tests and README contract | Resistance to all prompt-injection classes or authorization of production mutations |

The E-004 reference model and E-009 integration are research prototypes. A test passing at one layer must not be described as proof that an unrelated production layer is enforced.

## Human approval gates

Approval must be an authenticated, explicit action by an authorized human outside model-generated content. A phrase in a prompt, proposal, repository file, tool result, or generated plan is not approval.

Until the corresponding executable controls and tests exist, the following actions remain disabled and require an explicit human gate:

- Production deployment, promotion, or enabling an apply path.
- Destructive or irreversible schema/data migration.
- Granting a new principal, widening capability scope, increasing delegation depth, or changing trusted issuers/keys.
- Enabling broad network egress or access to high-impact external systems.
- Reading, exporting, rotating, or deleting production secrets.
- Raising hard CPU, memory, process, storage, concurrency, or tenant quotas beyond an approved budget.
- Changing audit retention, integrity keys, or trusted audit destinations.
- Selecting or changing production sandbox/runtime isolation policy.
- Publishing a release or changing trusted build/release credentials.

Human approval is a release/action gate, not a substitute for authorization checks. An approved action must still pass compiler/runtime policy, workload identity, revocation, storage isolation, audit, egress, and sandbox enforcement.

## Requirement traceability

`requirements.json` is the machine-readable source for SEC-001 onward. Every requirement has at least one exact executable test reference or an explicit `human_approval_gate`. `production_gate` can additionally keep a prototype-tested capability unavailable for production until its remaining control boundary is verified.

Statuses describe evidence scope, not deployment readiness:

- `prototype_tested`: named tests exercise the stated reference/runtime prototype only.
- `design_only`: no executable enforcement test currently exists for that requirement.
- `approval_gate_defined`: a human gate is explicit, but the control is not claimed to be implemented.

## Residual risks and open decisions

- Cryptographic representation, signing-key rotation, custody, revocation, and bounded revocation propagation.
- Trusted workload identity establishment and propagation across services.
- Database row-level enforcement and isolation under connection pooling.
- Atomicity between authorization, idempotency, durable state, and external side effects.
- Filesystem/network sandbox design and host escape risk.
- Secret lifetime, memory exposure, and diagnostic redaction.
- Time source trust, clock skew, and revocation latency.
- Side channels, kernel/runtime vulnerabilities, and supply-chain compromise.
- Audit integrity, retention, privacy, transport authentication, and tenant separation.
- Safe migration planning, rollback, and human approval UX.
- Prompt-injection attack coverage across source, retrieved content, tool output, compiler diagnostics, and multi-step agent workflows.

No single sandbox, WASI runtime, prompt, or language type system is assumed to solve the complete threat model.

## Production safety invariant

`production_enforcement_enabled`, `production_execution_enabled`, `apply_enabled`, and `production_deployment_enabled` remain false in `requirements.json`. Do not enable apply, production mutation, or deployment based on the E-004 reference model, E-009 prototype, or human approval alone. Require independently tested trusted enforcement at every relevant boundary first.
