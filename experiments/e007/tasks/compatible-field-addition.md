# M3 task: backward-compatible field addition

**Task ID:** `m3-compatible-field-add-v1`  
**Status:** draft; not preregistered; no apply.

## Agent-visible task

Extend the supplied sample service's Item contract with an optional descriptive field while preserving compatibility for existing stored records and clients that omit the new field. The change must not require destructive migration, must define the default/absence semantics, and must keep tenant ownership and authorization unchanged.

## Expected proposal

- A complete candidate service contract/IR and any required schema/storage changes.
- Explicit optionality and default semantics.
- Compatibility analysis for old records and old clients.
- Tests for absent, present, invalid, and persisted values, plus tenant-boundary regression coverage.
- A validation report and safe execution plan bound to the exact candidate hash.

## Evaluation boundary

The agent receives only the public task and service baseline. Hidden evaluator assertions and oracle fixtures must remain outside the agent workspace. No apply or production mutation is permitted.
