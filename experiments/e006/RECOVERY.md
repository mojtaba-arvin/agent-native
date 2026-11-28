# E-006 recovery and substrate evidence

This document supplements the E-006 SQLite reference README without changing its original scope statement.

## Executable recovery coverage

Run all tests:

```sh
python -m unittest discover -s experiments/e006 -p "test_*.py" -v
```

- `test_recovery_protocols.py`: two independent processes race to claim one task; an abruptly terminated process leaves no partial transaction; an expired lease is fenced after process recovery.
- `recovery_protocols.py`: independent application and broker databases model transactional outbox/inbox boundaries. Failure injection after broker acknowledgement demonstrates duplicate publication; consumer inbox + local effect transaction suppresses duplicate local effects; failure after consumer commit but before broker acknowledgement is safe on redelivery.
- `schema_lifecycle.py` and `test_schema_lifecycle.py`: ordered, checksummed forward migrations; migration rollback and drift detection; bounded deletion of unpinned terminal records; WAL checkpoint, VACUUM and integrity check.
- `substrate_comparison.json`: machine-readable comparison of SQLite, PostgreSQL and MySQL InnoDB. It is an architecture comparison, not a benchmark, and explicitly defers production selection.
- `evidence.json`: claim classifications and the exact run/commit evidence. The 31-test recovery run is run `46108550642` on commit `a205dd77f2e28054f71f5ca2d4bef5463d3c980f`.
- `run_evidence.py` and `.github/workflows/e006-recovery.yml`: run the full suite and upload a machine-readable exact-commit result artifact.

## External side-effect boundary

The outbox makes local business state and intent-to-publish atomic. It does not make broker publication exactly once. A relay can publish and crash before recording success, so publication is at least once and duplicates are expected. A consumer inbox suppresses duplicate *local transactional* effects only when its inbox marker and effect share one database transaction.

An inbox does not make a payment, HTTP call, email, or other remote side effect atomic. Such a receiver must honor a stable idempotency key, or the workflow needs explicit reconciliation/compensation and a documented ambiguous-outcome state. A lease/fencing token protects conditional database transitions; it cannot retract or prevent an already-issued external request.

## Substrate decision

No production persistence substrate is selected. SQLite WAL and writer serialization demonstrate a useful local reference model, not distributed locks, multi-node availability, consensus, or horizontal scaling. PostgreSQL and MySQL InnoDB remain candidates. A selection requires the same conformance suite and representative workload/failure measurements on each candidate, including HA failover, backup/restore, schema rollout, retention, compaction, and operational cost. See `substrate_comparison.json`.

## Retention and compaction boundary

The executable retention policy deletes only expired, unpinned terminal records. It deliberately does not choose a production retention period, legal-hold policy, audit archive, or replay window. Those are deployment decisions. SQLite compaction is maintenance work: checkpoint and VACUUM require operational headroom and must be scheduled against the real workload. The prototype's integrity check is not a production maintenance runbook.

## Existing reference semantics retained

The existing E-006 queue continues to cover idempotent submission, lease expiry and fencing, deadlines, retry budgets, cancellation, local effect atomicity, crash rollback, and durable reopen. The additions do not claim OS-level worker termination, distributed locks, authenticated multi-host workers, exactly-once remote effects, or a production database choice.
