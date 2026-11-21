# M3 task: tenant isolation

**Task ID:** `m3-tenant-isolation-v1`  
**Status:** draft; not preregistered; no apply.

## Agent-visible task

Review and change the supplied sample service so that every item read and write is scoped to the tenant derived from the trusted authenticated request context. Agent-supplied arguments must never override the tenant identity. Unauthorized cross-tenant access must fail closed and produce the appropriate audit evidence without disclosing another tenant's data.

## Expected proposal

- A complete candidate service contract/IR and implementation changes.
- Explicit trust-source and tenant-scoping rules for every repository operation.
- Tests proving tenant A cannot read or mutate tenant B's records, including attempts to pass a different tenant ID in request input.
- Audit assertions for both allowed and denied access.
- A validation report and safe execution plan bound to the exact candidate hash.

## Evaluation boundary

The agent receives only the public task and service baseline. Cross-tenant oracle fixtures and expected outcomes must remain in a separate evaluator sandbox. No apply or production mutation is permitted.
