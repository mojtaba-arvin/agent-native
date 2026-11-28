# E-003 / E-006 residual-risk record

Status: research reference-model record, updated 2026-11-28. This is not a production-readiness assessment.

## Reproduction

Run from the repository root with Python 3.11+ and the standard library only:

```sh
python -m unittest discover -s experiments/e003 -p 'test*.py' -v
python -m unittest discover -s experiments/e006 -p 'test*.py' -v
```

The E-003 suite advances logical time explicitly and uses no sleeps. E-006 creates a fresh temporary SQLite database per test. Multi-process tests use Python's `spawn` context, a barrier, bounded process joins, and a pipe for the crash checkpoint. The crash worker exits with code 23 immediately after its claim transaction commits; the parent then advances the supplied logical time beyond lease expiry and asserts that a new claimant receives fencing token 2. No external service, network, real credential, or non-synthetic effect is used.

## Residual risks

| Risk | Current reference evidence | Residual / production requirement |
|---|---|---|
| Bounded admission and worker concurrency | E-003 explicit outstanding and worker-slot accounting tests | Runtime must enforce limits at every ingress and execution boundary; process-local limits do not compose into a global limit |
| Backpressure behavior | E-003 rejects without enqueue and recovers after terminal state | No queueing timeout, overload shedding policy, admission fairness, or retry-after protocol is selected |
| FIFO fairness | E-003 retry/crash requeues append to tail; E-006 ties use SQLite row insertion order | Global FIFO only. No tenant isolation, weighted fair queuing, priority policy, or cross-process fairness guarantee |
| Deadlines | E-003 absolute logical deadline covers queueing, execution, retries; E-006 stores absolute deadline | Production clock authority, clock skew bounds, cross-service propagation, and deadline conversion remain unspecified |
| Clock skew | E-006 rejects timestamps below the greatest observed value in the shared DB | Forward-skewed time can expire work early; caller-supplied time is not authenticated. Requires trusted authority and bounded skew; SQLite is not a distributed clock |
| Cancellation | E-003 retains capacity until stop acknowledgement; E-006 transactionally fences local completion | Neither model terminates arbitrary OS processes or proves external operations stopped. Need cancellation transport, grace period, kill escalation, and unknown-outcome handling |
| Retry safety | Finite attempts, absolute deadline, transient-only retry, and delayed retry in E-006 | No jitter/backoff policy, retry budget across services, storm control, or handler side-effect proof |
| Worker crash | E-003 requeues within attempt/deadline bounds; E-006 crash-after-claim test recovers with a newer fence | Crash after external side effect but before acknowledgement remains ambiguous; recovery can invoke handler again |
| Durable idempotency | E-006 canonical payload hash: same key/same payload replays; changed payload conflicts | Key namespace, retention/expiry, tenant/service scoping, key rotation, and operational cleanup policy need production decisions |
| Local atomic effects | E-006 commits local state, effect ledger, and task completion in one SQLite transaction; injected pre-commit crash rolls back | Atomicity stops at one SQLite database. It cannot include an external HTTP/API/broker or a second database |
| Outbox/inbox boundary | Contract requires transactional outbox, at-least-once relay, receiver inbox dedupe/fingerprint, and reconciliation | E-003/E-006 do not implement a production relay, broker, receiver, or provider idempotency contract; E-008 remains the separate reference experiment |
| Multi-process recovery | E-006 spawned-process competing claims and post-claim process death against one local SQLite file | No multi-host shared filesystem, network partition, distributed database, consensus, or replica failover guarantee |
| Graceful shutdown | E-003 drains accepted work and distinguishes immediate stop requests | No bounded drain deadline, listener closure, OS signal integration, process supervisor, or forced termination protocol |
| Exactly-once external effects | Explicitly not claimed | Impossible to infer from local task idempotency or SQLite transactions. Use receiver idempotency and reconciliation; expose unknown outcomes when acknowledgement is ambiguous |

## Guarantee boundary

- **Observed by tests:** only the behavior exercised by the named E-003/E-006 tests on the tested Python/SQLite runtime.
- **Reference guarantee:** deterministic in-memory state transitions in E-003; local transaction/lease/fencing properties in E-006.
- **Not established:** production scheduler behavior, throughput/latency, tenant fairness, distributed lock/lease safety, multi-node availability, cross-host clock behavior, arbitrary process termination, external-effect exactly-once, or deployment fault tolerance.

Do not promote any row in the residual-risk column to a product guarantee without a separate implementation, deployment-specific fault injection, reproducible evidence, and a reviewed decision.
