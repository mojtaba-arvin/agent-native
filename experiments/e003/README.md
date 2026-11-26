# E-003 executable semantics model

This is a deterministic, discrete-time reference model for a narrow set of framework-owned task semantics. It is not a production scheduler or runtime and makes no claim about throughput.

The model tests:
- bounded outstanding work and explicit backpressure;
- absolute deadlines;
- cooperative cancellation with slot release;
- bounded transient retries;
- worker-crash requeue;
- idempotency-key deduplication.

Time advances only through explicit calls, so tests are reproducible without sleeps or wall-clock races.

## Run

```sh
python -m unittest discover -s experiments/e003 -v
```

## Deliberate simplifications

No persistence, distributed consensus, network transport, real worker process, fairness guarantee, lease expiry, exactly-once side-effect guarantee, or crash-safe idempotency store is implemented. The model's in-memory idempotency ledger demonstrates deduplication semantics only; production durability and atomicity remain open research questions.


## Input contract validation

The in-memory reference model now rejects blank/non-string task and worker identities, booleans masquerading as integer limits or time values, non-integer retry/concurrency bounds, invalid outcomes, and non-string task results. These checks make the executable model's input boundary explicit; they do not add persistence, distributed coordination, or production resource enforcement.


## Cooperative cancellation and capacity accounting

A cancellation request for running work now moves the task to `cancelling`; it does not immediately free the worker slot. Both worker-concurrency and outstanding-task capacity remain occupied until the worker finishes or crashes and acknowledges that it has stopped. A deadline expiry uses the same stop-request path and resolves to `expired` only after the worker stops. Immediate shutdown cancels queued work and requests cancellation of running work, but it is not drained until those workers stop.

This avoids the unsafe reference-model assumption that removing a worker from bookkeeping instantly stops its execution. Real runtimes still need a cancellation token/IPC mechanism and a bounded kill escalation policy.
