# E-009 / E-010 — Kernel and sandbox trust-boundary review

**Review date:** 2026-11-18  
**Classification:** static code review; not a penetration test or production security certification.

## Scope inspected

- experiments/e009/kernel.py
- experiments/e009/agent_gateway.py
- experiments/e009/repository.py
- experiments/e009/work_store.py
- experiments/e009/audit.py
- experiments/e010/demo_apply.py
- experiments/e010/test_demo_apply.py

## Positive controls present

- Runtime rejects non-RequestContext identities and applies default-deny capability authorization.
- Tenant identity is taken from the trusted RequestContext abstraction, not parsed from a request body.
- Operation effects are checked against the host-provided trusted-effect set at runtime construction.
- Input binding rejects unexpected query/body fields, duplicate query parameters, invalid percent encoding, and malformed path encodings.
- Handler output types/statuses are checked against the service contract.
- Authorization audit failure is fail-closed before the application handler is called.
- Gateway NDJSON input uses strict UTF-8/JSON parsing, rejects duplicate keys/non-finite numbers, bounds message size, and exposes only catalogued tools.
- Delta proposal materialization is append-only and constrained to a small trusted effect/capability allowlist.
- Default E-009 apply remains disabled. E-010's exact coordinator validates service/base identity and exact baseline preservation before constructing a candidate runtime.
- E-010 tests cover tampered service/types/existing operation, apply-before-plan, replay idempotency, and runtime smoke request.

## Findings and required work

### F-01 — Trusted identity construction is outside the kernel boundary

**Severity:** High integration risk; not a demonstrated exploit in the reference tests.

ServiceRuntime.dispatch receives a RequestContext object and verifies its type, but does not authenticate its origin. A caller able to construct or inject a RequestContext can potentially supply arbitrary principal, tenant, and grants. The current kernel therefore assumes a trusted host/authentication adapter. This is acceptable for the vertical slice only if documented as a host trust boundary; it is not a network-facing authentication implementation.

**Required:** define a non-forgeable host-authenticated identity input boundary, keep RequestContext construction inside the trusted adapter, and add negative integration tests proving HTTP/NDJSON clients cannot submit principal, tenant, or grants as authority.

### F-02 — Runtime contract/handler state is mutable

**Severity:** High integrity risk if the runtime is shared with untrusted extensions or concurrent hot reload.

The runtime retains the IR and handler mappings and exposes mutable nested contract dictionaries through its internal structures. The operations tuple does not make nested operation dictionaries immutable. E-010 correctly documents this and only demonstrates construction of a new ServiceRuntime plus active-reference replacement.

**Progress in this branch:** ServiceRuntime now owns a deep copy of the validated IR, keeps operation definitions in private runtime-owned structures, returns defensive copies from public IR/operation inspection, exposes the handler registry through a read-only mapping, and passes a defensive operation copy to handlers. Regression tests mutate caller-owned IR/handler dictionaries and returned inspection copies. CI passed the kernel changes at commit d9c5b96; the added regression test is queued in the latest E-009 run. This is defensive ownership, not a formal deep-immutability guarantee: Python internals remain introspectable, handler callables/repository are trusted host dependencies, and atomic concurrent runtime publication is not implemented.

**Remaining:** define an explicit runtime publication abstraction and concurrency contract before hot reload; add dispatch-versus-publication race tests; decide whether a recursively immutable canonical IR representation is warranted.

### F-03 — Audit and business state are not yet one atomic durability boundary

**Severity:** High correctness risk for durable product semantics.

The kernel emits authorization audit before handler execution and fails closed if that sink is unavailable. E-009 repository/work-store and audit sink are separate concerns. This proves pre-handler authorization audit availability, not an atomic transaction containing successful state change, idempotency outcome, job, outbox, and terminal audit result.

**Required:** implement the shared storage adapter contract from E-002; distinguish attempt/decision audit from committed business outcome audit; atomically commit canonical admission outcome with job/outbox/idempotency; add crash-after-commit-before-response recovery tests.

### F-04 — E-010 callback is a host trust boundary, not a sandbox primitive

**Severity:** High isolation risk if generalized.

E-010's sandbox_only label is descriptive metadata. The Gateway invokes a host-injected callback; arbitrary callback code is not isolated by the label. The current coordinator confines its own SQLite files to a temporary directory and uses an exact baseline check, but this does not establish process, filesystem, network, or secret isolation for arbitrary callbacks.

**Required:** keep the demo callback allowlisted and test-only. A future untrusted extension/apply path needs an OS/container/VM isolation boundary with explicit filesystem, network, CPU, memory, process, and secret controls plus adversarial escape tests. Do not generalize the current proof.

### F-05 — Hostile concurrency and parser/resource tests remain incomplete

**Severity:** Medium.

Static tests exercise many malformed-input and tenant/capability cases, but the review does not establish exhaustive request-size, path-depth, regex/route explosion, concurrent dispatch/hot reload, repository lock contention, or denial-of-service resistance.

**Required:** add property/fuzz tests for strict JSON, path/query decoding and IR validation; bounded request/response sizes and per-tenant concurrency; race tests for dispatch versus runtime publication.

## Architecture decisions

1. Keep authentication, tenant authority, and RequestContext construction in a clearly identified trusted host adapter; never accept client-supplied grants as identity.
2. Do not expose mutable IR/handlers to untrusted code. Deep immutability is a prerequisite for concurrent runtime publication, not a claim of the current implementation.
3. Separate audit event classes: attempted/authorized/denied request audit versus committed business outcome audit. Define which are transactional with state.
4. Treat E-010 as a narrowly scoped demo coordinator only. It is not a general-purpose sandbox or production deployment path.
5. Prioritize E-002 atomic durable storage semantics before claiming reliable distributed job admission.
6. Keep E-011 implementation gated on E-007 real-agent lifecycle acceptance; semantic research may continue independently.

## Review limitation

This was a source-level review of the referenced prototype, not dynamic exploit testing, dependency audit, formal verification, or external penetration testing. Findings are actionable risk statements, not claims that an exploit has been reproduced.
