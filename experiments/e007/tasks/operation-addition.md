# M3 task: operation addition

**Task ID:** `m3-operation-add-v1`  
**Status:** draft; not preregistered; no apply.

## Agent-visible task

Extend the supplied sample service with one new read-only operation that retrieves an item by its normalized name. The operation must follow the service's existing contract and response conventions, require the least-privilege read capability, validate the path input, and preserve tenant scoping from the authenticated request context. Do not add a write effect or weaken an existing authorization rule.

## Expected proposal

- A complete candidate service contract/IR.
- The operation's method, route, typed input, output, declared errors, validation rules, effects, and capability.
- Tests covering a valid lookup, a missing item, invalid input, unauthorized access, and cross-tenant isolation.
- A validation report and a safe execution plan bound to the exact candidate hash.

## Evaluation boundary

The agent receives only the public task and service baseline. Hidden evaluator assertions, oracle data, and expected candidate hashes must live outside the agent workspace. No apply or production mutation is permitted.
