# E-002 — Shared durable storage conformance contract v1

**Status:** preregistered contract; SQLite and PostgreSQL reference adapters independently pass their current conformance suites; no product adapter selected and no runtime-candidate adapter parity established.  
**Purpose:** isolate persistence guarantees from runtime/language comparisons.  
**Normative language:** MUST / MUST NOT describe acceptance requirements for this experiment, not a production certification.

## 1. Decision boundary

The E-002 product workload requires an atomic durable outcome for job admission. A successful admission is one logical commit containing:

- the job record;
- exactly one outbox event for that job;
- the idempotency result;
- the corresponding audit outcome.

A candidate MUST NOT return an accepted response before this transaction satisfies the configured durability profile. A log line, in-memory queue, buffered file write, or independent writes to multiple stores do not satisfy this contract.

This contract deliberately does not choose SQLite, PostgreSQL, an embedded KV store, or a distributed database. It defines the behavior each adapter must demonstrate before performance is compared.

## 2. Minimal adapter surface

Each adapter exposes equivalent operations (names are illustrative; wire/API shape is not selected):

1. `append_audit(event)`: append one immutable event and return its durable sequence/identifier.
2. `admit_job(job, outbox_event, idempotency_record, audit_event)`: atomically commit all four records or none.
3. `lookup_idempotency(tenant, operation, key)`: return the canonical request hash and original logical outcome.
4. `read_job(job_id)` and `read_outbox(event_id)`: inspect committed state for conformance and recovery.
5. `claim_outbox(consumer, limit, lease)` and `ack_outbox(event_id, consumer)`: support at-least-once delivery; acknowledgement is not proof of exactly-once external effects.
6. `recover()`: reopen/recover after process termination and expose committed state.

Adapters may have richer internal APIs, but benchmark code must use only this common semantic surface. A no-persistence control benchmark is a separate tier and cannot pass this contract.

## 3. Identity, idempotency and ordering

- Idempotency scope is the tuple `(authenticated_tenant_id, operation_id, idempotency_key)`.
- The canonical request hash is computed from the validated semantic request, with a versioned canonicalization algorithm pinned in the fixture manifest.
- Same scope + same hash returns the original logical outcome and MUST NOT create another job, outbox event, or canonical admission event. The retry attempt still receives its own request ID and a durable audit event recording the replayed outcome.
- Same scope + different hash returns a stable conflict and MUST NOT mutate the original job/outbox/idempotency records; the rejected attempt receives its own durable denial audit event.
- Concurrent requests racing on the same scope are linearizable: exactly one new logical admission may win.
- A retry after an ambiguous client timeout MUST reconcile by the same idempotency key; it MUST NOT invent a new key automatically.
- Request/attempt IDs identify individual attempts and are distinct from the idempotency key.
- Audit events are append-only. The adapter exposes a stable per-tenant or global ordering token sufficient to prove the admission audit event is committed with the job. The exact ordering scope is a design choice, but it must be declared and consistently tested.

## 4. Transaction and durability profile

The conformance profile is **local durable commit**: after an adapter reports success, a process crash or operating-system crash followed by supported recovery MUST preserve the committed transaction. Power-loss guarantees are reported separately because they depend on filesystem, device cache, virtualization and storage configuration.

For each candidate, the run manifest records:
- engine and exact version;
- journal/WAL mode and synchronous/flush settings;
- filesystem and mount options;
- storage medium and virtualization/container boundary;
- transaction isolation and locking mode;
- replication mode, if any;
- backup/recovery assumptions;
- any acknowledged durability downgrade.

A configuration that acknowledges commits before its documented durability point is not equivalent to the profile. Such a mode may be measured as a separately labelled relaxed-durability arm, never silently pooled with the durable arm.

Research basis:
- PostgreSQL documents that `fsync=off` risks unrecoverable corruption after OS/hardware failure and that `synchronous_commit=off` can acknowledge before WAL is safely flushed, allowing recent transactions to be lost after a crash: https://www.postgresql.org/docs/current/runtime-config-wal.html
- SQLite WAL commits append a commit record to the WAL; `synchronous=NORMAL` may omit a sync on each commit and can lose recent transactions after power loss/hard reset, while `FULL` syncs the WAL at each commit: https://www.sqlite.org/wal.html

These are engine-specific mechanisms, not evidence that the engines have identical latency or durability under arbitrary configurations.

## 5. Required conformance tests

Every test runs against each adapter using the same deterministic fixture set.

### Atomicity
1. Commit a valid job admission; verify all four records are visible.
2. Inject failure before transaction begin; verify no records.
3. Inject failure after each logical write but before commit; verify no partial records after recovery.
4. Inject failure at commit; classify outcome as committed or not committed only after recovery, never by assuming the client-side exception means rollback.
5. Kill the process immediately after commit but before response delivery; retry with the same key/hash and verify the original outcome is returned without duplicate job/outbox/admission effects, while the retry attempt is separately audited.

### Idempotency and concurrency
6. Repeat same key/hash sequentially; one job, one outbox event, one canonical admission audit event, plus one audit event per retry attempt.
7. Repeat same key with a different hash; stable conflict, unchanged original job/outbox/idempotency records, and one denial audit event for the conflicting attempt.
8. Race at least 32 concurrent same-key/same-hash requests; exactly one logical admission.
9. Race same-key/different-hash requests; at most one hash wins, all conflicting hashes are rejected.
10. Reuse the same key under another tenant; verify scope isolation.
11. Reuse the same key under another operation; verify scope isolation.

### Audit and recovery
12. Verify audit append-only behavior through adapter-supported mutation attempts.
13. Verify the canonical admission audit record, job, outbox and idempotency result share the same transaction outcome; verify replay/conflict attempt audit records are durable without creating a second logical admission.
14. Reopen the adapter after clean shutdown and after forced process termination.
15. Verify committed sequence/order tokens remain stable after recovery.
16. Make audit storage unavailable; admission fails closed and creates no job/outbox record.

### Outbox delivery semantics
17. Publish event, crash before acknowledgement, redeliver; consumer deduplicates by stable event ID.
18. Consumer applies local effect and records consumed event ID in one local transaction; replay causes no second local effect.
19. Lease expiry allows recovery by another consumer without losing the event.
20. Queue-capacity rejection creates no accepted job and has a durable denial audit event if the audit store is available.

The suite distinguishes adapter guarantees from the delivery system: the storage contract guarantees atomic durable outbox admission, not exactly-once network delivery or exactly-once external side effects.

## 6. Common result schema

Each test result records:
- adapter ID, version, configuration hash and source SHA;
- test ID, deterministic seed and attempt ID;
- operation outcome and stable reason code;
- expected and observed record counts;
- canonical request hash and idempotency scope (never credentials);
- transaction/commit duration;
- recovery duration and recovered state;
- injected fault point;
- durability profile and any downgraded guarantees.

A missing measurement is null/unknown, never zero. Failed trials remain in the corpus.

## 7. Benchmark fairness and measurement

Only adapters passing all mandatory atomicity, idempotency, audit and recovery gates enter the durable product benchmark. A candidate cannot trade away correctness to improve p99 or throughput.

Use identical request fixtures, transaction contents, key distributions, concurrency, host, filesystem, and durability profile. Randomize candidate order and run at least ten repetitions after warm-up. Report p50/p95/p99, throughput, CPU, peak memory, transaction/commit latency, recovery time, lock/contention indicators and failure outcomes.

Prefer a dedicated cgroup v2 for whole-process-tree CPU accounting and record `cpu.max`, `cpu.stat` usage/user/system and throttling. The existing 5 ms `/proc` sampler is diagnostic only: it may miss short-lived descendants and is affected by shared-runner noise. Never promote its measurements to a controlled capacity claim.

## 8. Candidate adapter sequence

1. Implement the conformance suite and fixture manifest independently of any engine.
2. Implement one adapter at a time behind the same surface; first reference adapter should be chosen for ease of proving semantics, not presumed performance.
3. Add at least one materially different adapter only after the contract tests are stable.
4. Run conformance and fault injection before performance tests.
5. Keep no-persistence control-plane results separate from durable product-tier results.
6. Do not choose a default storage engine until adapter parity and controlled measurements exist.

## 8.1 Executable SQLite reference adapter (2026-11-18)

`experiments/e002/sqlite_reference_adapter.py` uses a file-backed SQLite WAL database with `synchronous=FULL`; job, outbox, tenant+operation-scoped idempotency result, and admission audit commit in one transaction. Its 24-test suite passed in [workflow 44339334484](https://github.com/mojtaba-arvin/agent-native/actions/runs/44339334484).

Coverage includes pre-commit rollback at each logical write boundary, same-key replay/conflict, tenant and operation isolation, 32-way same-hash and different-hash races, real process termination after commit but before response, audit-outage fail-closed behavior, append-only audit, and fenced outbox lease/ack.

## 8.2 Executable PostgreSQL reference adapter (2026-11-18)

`experiments/e002/postgres_reference_adapter.py` implements the same contract against PostgreSQL 16.4 with `fsync=on`, `synchronous_commit=on`, versioned canonical hashing, and transaction-scoped advisory locks for idempotency scope. Its 9-test suite passed in [workflow 44341683697](https://github.com/mojtaba-arvin/agent-native/actions/runs/44341683697), using pinned psycopg 3.2.9.

It covers atomic admission, rollback at every pre-commit write boundary, same-key replay/conflict, tenant+operation isolation, 32-way same-hash and different-hash races, process crash after commit/before response, audit outage fail-closed, append-only audit, and fenced outbox lease/ack.

These two adapters establish useful single-node reference evidence, not a product database choice. They do not certify power-loss behavior, replication, online migration, backup/PITR, or multi-node linearizability. No Go/Rust/WASI/BEAM runtime adapter parity is claimed. The next correctness gate is a shared generated-trace runner that executes identical traces against both adapters and compares outcomes before performance ranking.

## 9. Explicit non-goals

This contract does not establish multi-region durability, consensus, exactly-once message delivery, global ordering across shards, backup/PITR policy, tenant encryption-at-rest, online schema migration, or production operational readiness. Those require separate experiments and threat/failure models.
