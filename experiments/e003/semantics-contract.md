# E-003 semantics contract v0

This contract defines observable behavior for the reference model only. It is a candidate for framework semantics, not a final design decision.

| Concern | Required observable rule | Model behavior |
|---|---|---|
| Admission | Reject new work when outstanding capacity is exhausted; never silently grow an unbounded queue | `backpressure` submission |
| Concurrency | Active workers never exceed the configured limit | `start` refuses excess workers |
| Deadline | One absolute deadline bounds queue wait, execution, and retries | `advance` and `finish` expire overdue tasks |
| Cancellation | Queued/running work becomes terminal and releases active worker capacity | `cancel` |
| Retry | Only transient failures retry, with finite attempts and before deadline | `finish` |
| Crash | Worker loss is observable; task requeues only when budget remains | `crash` |
| Idempotency | Repeated submissions with the same key map to the original task | `submit` deduplicates |
| Success | Completed idempotency keys are retained in the model | in-memory completed-key ledger |

## Open production questions

- Is idempotency scoped per service, tenant, operation, or global key namespace?
- What durable storage and atomic commit boundary bind side effects to idempotency records?
- What happens when a worker performs a side effect and crashes before acknowledgement?
- Are retries immediate, delayed, exponential, jittered, or policy-driven?
- How are deadline budgets propagated across service boundaries and clock skew?
- What fairness policy applies across tenants and priority classes?
- How are cancellation races with completion linearized?
- How do durable queues, leases, visibility timeouts, and worker fencing interact?
- What is the exact delivery guarantee: at-most-once, at-least-once, or application-level effectively-once?
- How are retry storms and overload prevented globally?

These questions must be answered and tested before promoting this model to framework semantics.
