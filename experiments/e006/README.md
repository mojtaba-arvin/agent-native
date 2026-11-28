# E-006 durable execution reference model

This experiment tests persistence and crash semantics with Python's standard-library SQLite engine. SQLite is an experimental local transaction substrate here, not a preselected production database or distributed queue.

## Existing reference semantics

- Durable task submission with a unique idempotency key.
- Duplicate key + identical payload returns the original task; different payload is rejected.
- Atomic task claiming with lease expiry and monotonically increasing fencing tokens.
- A stale worker cannot complete a task after another lease is issued.
- Deadline expiration, retry budget, delayed retry, cancellation and lease renewal.
- Local state mutation, effect-ledger insert, and task completion occur in one SQLite transaction.
- A simulated crash before commit rolls back all three writes.
- Reopening the database preserves tasks and effect records.

## Additional recovery evidence

Run all E-006 tests:

```sh
python -m unittest discover -s experiments/e006 -p "test_*.py" -v
```

The additional executable coverage is intentionally narrow and tests only the remaining acceptance gaps:

- `test_recovery_protocols.py`: two independent processes race to claim one task; an abruptly terminated process leaves no partial transaction; an expired lease is fenced after process recovery.
- `recovery_protocols.py`: independent application and broker databases model transactional outbox/inbox boundaries. Failure injection after broker acknowledgement demonstrates duplicate publication; consumer inbox + local effect transaction suppresses duplicate local effects; failure after consumer commit but before broker acknowledgement is safe on redelivery.
- `schema_lifecycle.py` and `test_schema_lifecycle.py`: ordered, checksummed forward migrations; migration rollback and drift detection; bounded deletion of unpinned terminal records; WAL checkpoint, VACUUM and integrity check.
- `substrate_comparison.json`: machine-readable comparison of SQLite, PostgreSQL and MySQL InnoDB. It is an architecture comparison, not a benchmark, and explicitly defers production selection.
- `evidence.json`: claims are classified as observed, supported, hypothesis or decision. Newly added test claims remain hypotheses until the exact-head CI run passes.
- `run_evidence.py` and `.github/workflows/e006-recovery.yml`: run the full suite and upload a machine-readable exact-commit result artifact.

## External side-effect boundary

The outbox makes local business state and intent-to-publish atomic. It does not make broker publication exactly once. A relay can publish and crash before recording success, so publication is at least once and duplicates are expected. A consumer inbox suppresses duplicate *local transactional* effects only when its inbox marker and effect share one database transaction.

An inbox does not make a payment, HTTP call, email, or other remote side effect atomic. Such a receiver must honor a stable idempotency key, or the workflow needs explicit reconciliation/compensation and a documented ambiguous-outcome state. A lease/fencing token protects conditional database transitions; it cannot retract or prevent an already-issued external request.

## Substrate decision

No production persistence substrate is selected. SQLite WAL and writer serialization demonstrate a useful local reference model, not distributed locks, multi-node availability, consensus, or horizontal scaling. PostgreSQL and MySQL InnoDB remain candidates. A selection requires the same conformance suite and representative workload/failure measurements on each candidate, including HA failover, backup/restore, schema rollout, retention, compaction, and operational cost. See `substrate_comparison.json`.

## Retention and compaction boundary

The executable retention policy deletes only expired, unpinned terminal records. It deliberately does not choose a production retention period, legal-hold policy, audit archive, or replay window. Those are deployment decisions. SQLite compaction is explicitly maintenance work: checkpoint and VACUUM require operational headroom and must be scheduled against the real workload. The prototype's integrity check is not a production maintenance runbook.

## Input and persistence-boundary validation

The reference queue rejects blank/non-string identities, boolean or non-integer timestamps/limits/lease tokens/amounts, non-object task payloads, and non-finite JSON numbers before persistence. Canonical JSON hashing disables NaN/Infinity.

## Cancellation/completion linearization

The queue's `cancel` operation is a durable state fence: it atomically changes a queued/running task to `cancelled` and clears its lease. A later local completion attempt with the old lease is rejected before effect mutation. Concurrent cancel and completion are serialized by SQLite's write transaction; exactly one transition wins.

This is not an OS-level worker termination mechanism. A production runtime must separately request cooperative cancellation or kill the worker, retain resource accounting until it stops, and define external side-effect behavior. E-003 covers the stop-acknowledgement side of that contract.

## Evidence status

The original E-006 reference run and the additional 31-test recovery run (run `46108550642`, tested commit `a205dd77f2e28054f71f5ca2d4bef5463d3c980f`) are recorded in `evidence.json`. Those observations apply to that exact tested commit and the local-file/fake-broker scope described above. No production guarantee or substrate decision is inferred from this reference experiment.
