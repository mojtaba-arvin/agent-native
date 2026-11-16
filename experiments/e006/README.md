# E-006 durable execution reference model

This experiment tests persistence and crash semantics with Python's standard-library SQLite engine. SQLite is an experimental local transaction substrate here, not a preselected production database or distributed queue.

## Behaviors

- Durable task submission with a unique idempotency key.
- Duplicate key + identical payload returns the original task; different payload is rejected.
- Atomic task claiming with lease expiry and monotonically increasing fencing tokens.
- A stale worker cannot complete a task after another worker acquires a newer lease.
- Deadline expiration, retry budget, and delayed retry.
- Local state mutation, effect-ledger insert, and task completion occur in one SQLite transaction.
- A simulated crash before commit proves rollback of all three writes.
- Reopening the database preserves tasks and effect records.

## Run

```sh
python -m unittest discover -s experiments/e006 -v
```

## Important boundary

The atomic effect demonstration covers only state stored in the same SQLite database and transaction. It does not provide exactly-once semantics for external HTTP calls, payment providers, message brokers, or other databases. Those require an outbox/inbox, idempotent receiver, saga/compensation, or another explicitly designed protocol. WAL and SQLite write serialization also do not establish multi-node availability or horizontal scaling.


## Input and persistence-boundary validation

The reference queue now rejects blank/non-string identities, boolean or non-integer timestamps/limits/lease tokens/amounts, non-object task payloads, and non-finite JSON numbers before entering a transaction. Canonical JSON hashing explicitly disables NaN/Infinity. These checks prevent Python's boolean-as-integer behavior and non-standard JSON values from silently changing durable task or effect semantics.

This remains a single-node SQLite semantic model. It does not provide distributed coordination, authenticated worker identity, external-effect delivery, production retention, or a production queue substrate.
