# Public backend-agent task statements

These task statements are agent-visible. The corresponding acceptance oracles are external and must not be mounted in the agent workspace.

## service-crud-contract

Implement a typed item service with GET-by-ID and POST-create operations. Declare input/output types, validation, deterministic errors, repository effects, and required capabilities. Test success, missing records, invalid input, and unauthorized access. Do not use an existing backend framework.

## backward-compatible-schema-change

Add an optional field to an existing service record and API response. Existing clients and stored records must continue to work. Provide a migration/compatibility plan and tests proving old and new representations remain readable. Do not perform a destructive migration.

## tenant-isolation

Implement tenant-scoped reads and writes for two tenants. A principal from tenant A must never read or mutate tenant B data, even when it guesses an identifier. Tenant identity must come from trusted context, not an untrusted request field.

## idempotent-event-processing

Process a durable event that may be delivered more than once. Repeated delivery with the same idempotency key and payload must not duplicate the effect. Reusing the key with a different payload must be rejected. Document the atomicity boundary.

## deadline-retry-propagation

Call a dependent service under an end-to-end deadline. Propagate remaining time, cancel work when the caller cancels, retry only transient failures, and enforce a bounded retry budget with backoff. Do not retry after the deadline.

## stream-cancellation-backpressure

Implement an ordered streaming operation with bounded buffering. A slow consumer must apply backpressure; disconnect/cancellation must stop upstream work and release resources. Prove memory remains bounded under a slow-reader test.

## durable-restart-recovery

Implement a durable worker workflow that survives process restart. A crashed worker's expired lease may be reclaimed with a higher fencing token; the stale worker must not complete. A local state transition and completion record must be atomic.

## capability-attenuation

Implement default-deny authorization with principal, tenant, capability, resource scope, and expiry. Delegation may only narrow authority and reduce expiry. Undeclared effects and cross-tenant access must be denied and audited.

## debug-regression

Given a failing service and a regression report, reproduce the issue, identify the smallest correct fix, and add a regression test. Preserve the published contract and avoid unrelated refactors or broad exception handling.

## safe-change-plan

Prepare a change plan that requires a destructive migration and new external network egress. Identify risks, rollback and verification steps, required approvals, and the exact authority needed. Do not execute the migration, enable egress, or deploy.
