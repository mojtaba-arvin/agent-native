# E-003 concurrency and failure semantics — normative reference contract

Status: **normative for the E-003 single-process reference model only**. This document does not select or specify a production scheduler, distributed queue, consensus protocol, or deployment topology. E-006 separately specifies the durable single-node SQLite reference boundary.

## 1. Terms and accounting

- **Outstanding** means accepted work in `queued`, `running`, or `cancelling`. Terminal work does not consume outstanding capacity.
- **Running** means a worker owns an execution slot. `cancelling` work remains running until the worker acknowledges stop by finishing or crashing.
- **Attempt** increments exactly when a worker starts execution. Queue wait and delayed retry do not consume attempts.
- **Deadline** is an absolute timestamp in the model's single logical clock domain. It bounds admission-to-start wait, execution, and all retries; it is not reset per attempt.
- **Idempotency key** identifies one logical task submission within this reference engine's lifetime. It is not a globally durable identity.

## 2. Admission, bounds, and backpressure

1. `max_outstanding >= 1`, `max_concurrency >= 1`, and `max_concurrency <= max_outstanding`.
2. The engine accepts a new unique task only while accepting and while outstanding count is below `max_outstanding`.
3. At capacity, submission returns `backpressure`; it MUST NOT enqueue, block indefinitely, silently drop, or increase capacity.
4. A duplicate idempotency key is resolved before shutdown/capacity checks and returns the original task identity. A key collision is deduplication in E-003; payload equality/conflict semantics are defined by E-006.
5. The number of worker-owned tasks MUST never exceed `max_concurrency`. A cancelling worker continues to consume its slot.
6. Rejected submissions do not reserve task IDs or idempotency keys. A caller may retry admission after capacity is available.

## 3. Queue order and fairness

The reference policy is **global FIFO among eligible queued tasks**:

- Initial admissions append to the tail.
- A transient retry or recoverable worker-crash requeue appends to the tail; it MUST NOT jump ahead of older eligible work.
- Expired/cancelled queue entries are skipped and consume no worker slot.
- Delayed retries are not eligible before their retry time (the E-003 model has no delay parameter).
- This is not tenant fairness, weighted fair queuing, priority scheduling, starvation freedom under an infinite arrival stream, or a distributed fairness guarantee. No per-tenant isolation is implied.

## 4. Deadlines and time

1. Submission computes one absolute deadline from the engine's logical current time plus a strictly positive TTL.
2. A queued task whose deadline is reached becomes `expired` without starting.
3. A running task whose deadline is reached enters `cancelling`, records `expired` as its terminal-after-stop outcome, and retains its worker and outstanding slots.
4. A worker completion after deadline cannot publish success. Once stop is acknowledged, the task becomes `expired`.
5. Retry and crash recovery are permitted only while the same absolute deadline remains in the future and attempt budget remains.
6. E-003 uses explicit deterministic logical time; it does not read wall clocks. Cross-process/host clock authority, monotonicity, skew bounds, and deadline conversion are outside E-003 and remain residual risks. A production design MUST define one authoritative deadline representation and a bounded skew policy; it MUST NOT compare unrelated host monotonic clocks as if they shared an epoch.

## 5. Cancellation and completion races

- Queued cancellation is immediately terminal and removes the task from effective admission/dispatch.
- Running cancellation is a stop request, not proof of termination. State becomes `cancelling`; worker and outstanding capacity remain charged until finish/crash acknowledges the worker has stopped.
- The first serialized state transition wins. A completion that commits before cancellation may complete; a cancellation that fences first prevents later completion from publishing a result.
- A worker's late success/error after cancellation or deadline is discarded.
- This model simulates stop acknowledgement. It does not deliver OS signals, interrupt arbitrary code, kill processes, or prove that external work stopped.

## 6. Retries and idempotency

- Only transient outcomes are retryable. Fatal outcomes fail immediately.
- Attempts are finite and count actual starts. No retry is allowed when `attempts >= max_attempts` or the absolute deadline has elapsed.
- A crash consumes the attempt that had already started. It requeues only when budget and deadline remain.
- E-003 retains idempotency mappings only in memory. Same key returns the original task; this does not prove durable deduplication after restart.
- Task-level idempotency prevents duplicate logical task admission only. It does not make handler side effects idempotent.
- External side effects MUST use an explicit boundary: commit local state and an outbox record atomically; deliver outbox messages at least once; require an inbox/receiver deduplication key and payload fingerprint; reject same key with changed payload. If the external receiver cannot deduplicate, use reconciliation/compensation and expose unknown outcomes. Never claim exactly-once external effects.

## 7. Worker crash and isolation

- A worker crash releases its local execution slot only after the engine has observed worker loss.
- The active task follows the same attempt/deadline rules as a transient failure.
- Worker identity is unique among currently active workers.
- A crash does not prove that a remote side effect did not happen before the crash. Retried handlers must be safe under duplicate invocation or use the outbox/inbox protocol above.
- E-003 has no process supervisor, lease, fencing token, durable recovery, or cross-process ownership.

## 8. Shutdown

- Shutdown closes admission for new unique work; duplicate-key lookups still resolve to their original task.
- Graceful shutdown leaves accepted queued work eligible and waits for all queued/running/cancelling work to become terminal.
- Immediate shutdown cancels queued work and requests stop for running work; it is not drained until every running worker acknowledges stop.
- `is_drained` is true only when no worker is active and no outstanding task remains.
- E-003 has no bounded drain deadline or forced-kill escalation. Production shutdown MUST define listener closure, admission cutoff, drain budget, cancellation grace, kill escalation, and treatment of work whose outcome is unknown at process termination.

## 9. E-006 durable SQLite reference boundary

E-006 is a distinct single-node reference model:

- SQLite `BEGIN IMMEDIATE` serializes local write transactions; lease tokens fence stale claimants within the database.
- Task payload idempotency is scoped to the unique key in that database; identical canonical payload replays the task, changed payload conflicts.
- Local state mutation, local effect-ledger insert, and task completion are atomic only when all three are in that same SQLite transaction/database.
- Lease expiry permits another claimant; monotonically increasing fencing tokens reject stale local completion.
- Process reopen and multi-process access to one local SQLite file are testable reference properties, not evidence of distributed database availability, multi-host shared-filesystem safety, authenticated worker identity, or horizontally scalable scheduling.
- A real external API call cannot be atomically committed with SQLite. Use an outbox/inbox or a provider-supported idempotency protocol and reconcile ambiguous outcomes.

## 10. Required conformance and fault-injection cases

The suite MUST cover: capacity saturation and recovery; concurrency ceilings; FIFO order under retries/crashes; queued/running deadline expiry; cancellation/finish serialization and late completion; finite retry exhaustion; duplicate key and changed payload; worker crash before/after durable claim; stale lease fencing; process reopen; competing processes claiming one task; backward clock observation; graceful and immediate shutdown; and deterministic replay without sleeps where logical time suffices.

Fault tests use temporary databases, synthetic task/effect identities, barriers or explicit fault points, bounded joins, and no real external services. Every injected crash point states which writes may be visible after reopen.

## 11. Guarantee vocabulary

- **Observed:** directly asserted by a named test/run.
- **Reference guarantee:** invariant implemented and tested within the stated model boundary.
- **Not guaranteed:** production/distributed property absent a separate protocol and deployment proof.

Passing these tests establishes reference-model conformance only. It does not establish production throughput, multi-node fairness, distributed exactly-once processing, or external-effect atomicity.
