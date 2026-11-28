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

## Normative semantics and adversarial coverage

`semantics-contract.md` is now the normative contract for this reference model: bounded admission/accounting, global FIFO among eligible work, one absolute deadline, cooperative cancellation stop acknowledgement, finite retries, crash requeue, idempotency scope, and graceful/immediate shutdown. Retries and worker-crash requeues join the FIFO tail so they cannot continually jump ahead of older eligible work. The adversarial suite in `test_adversarial.py` covers FIFO fairness, capacity recovery, duplicate submission after shutdown, deadline preservation, and late completion/cancellation races.

The fairness statement is deliberately narrow: global FIFO in one in-memory engine. It does not imply per-tenant fairness, weighted scheduling, starvation freedom under unbounded arrivals, or fairness across processes/hosts. E-003 still has no bounded shutdown deadline, process supervisor, kill escalation, durable ledger, or shared clock.

## Deterministic scheduling trace

Run `python experiments/e003/performance_trace.py` to emit a reproducible synthetic scheduling trace (default: 16 tasks, 4 worker slots). It reports admission/start/completion events, maximum observed model concurrency, logical duration, and p50/p99 queue wait in **logical ticks**. This is a queueing/concurrency trace of the reference model, not a wall-clock throughput/latency benchmark and not a production capacity claim. Its deterministic output is covered by `test_performance_trace.py`.
