# E-003 semantics contract v0

This contract defines observable behavior for the reference model only. It is a candidate for framework semantics, not a final design decision.

| Concern | Required observable rule | Model behavior |
|---|---|---|
| Admission | Reject new work when outstanding capacity is exhausted; never silently grow an unbounded queue | `backpressure` submission |
| Concurrency | Active workers never exceed the configured limit | `start` refuses excess workers |
| Deadline | One absolute deadline bounds queue wait, execution, and retries; running work requests cancellation at expiry and retains capacity until stopped | `advance`, `finish`, and `crash` |
| Cancellation | Queued work becomes terminal immediately; running work enters `cancelling` and retains its worker slot until finish/crash acknowledges stop | `cancel`, `finish`, `crash` |
| Retry | Only transient failures retry, with finite attempts and before deadline | `finish` |
| Crash | Worker loss is observable; task requeues only when budget remains | `crash` |
| Idempotency | Repeated submissions with the same key map to the original task | `submit` deduplicates |
| Success | Completed idempotency keys are retained in the model | in-memory completed-key ledger |
| Shutdown | Stop admission; graceful mode drains accepted work, immediate mode cancels queued work and requests stop for running work; drained only after workers stop | `shutdown(graceful=True|False)` |

## Open production questions

- Is idempotency scoped per service, tenant, operation, or global key namespace?
- What durable storage and atomic commit boundary bind side effects to idempotency records?
- What happens when a worker performs a side effect and crashes before acknowledgement?
- Are retries immediate, delayed, exponential, jittered, or policy-driven?
- How are deadline budgets propagated across service boundaries and clock skew?
- What fairness policy applies across tenants and priority classes?
- How are cancellation races with completion linearized? The reference model uses first state transition wins; a running cancellation is only terminal after worker stop acknowledgement.
- How do durable queues, leases, visibility timeouts, and worker fencing interact?
- What is the exact delivery guarantee: at-most-once, at-least-once, or application-level effectively-once?
- How are retry storms and overload prevented globally?

These questions must be answered and tested before promoting this model to framework semantics.


## Shutdown contract

- Once shutdown begins, new unique submissions return `shutting_down`.
- Duplicate submissions for an existing idempotency key continue to resolve to the original task.
- Graceful shutdown leaves already accepted work eligible to start and finish; the runtime reports drained only when no task remains queued or running.
- Immediate shutdown marks all queued/running tasks cancelled and releases worker slots.
- A production runtime still needs a bounded drain deadline, signal handling, listener closure, in-flight response policy, and a defined behavior for tasks that exceed the drain budget.
