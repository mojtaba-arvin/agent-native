# E-009 local Agent task

Inspect the live service with ID `catalog` (display name `Catalog`) and propose exactly one additional read-only operation:

- Name: `get_item_by_normalized_name`
- Method: `GET`
- Path: `/items/by-normalized-name/{name}`
- Input: `name: String` from the path
- Output: `Item`
- Errors: `[InvalidInput, NotFound, Unauthorized]`
- Validation: `[name.non_empty]`
- Effects: `[repository.read]`
- Capability: `items.read`

Preserve the service name/version, every existing type and field, and every existing operation exactly. Add no other operation, type, field, effect, or capability. Inspect first and use the exact inspected revision as the proposal base.

**The `service.propose.ir` value is a complete canonical service IR snapshot, not an incremental patch.** It must contain exactly:
- `ir_version`: integer `1`
- `service`: the complete inspected service identity (name and version)
- `types`: every inspected type and all of its fields
- `operations`: every existing operation in full, copied from its operation inspection, plus exactly the new operation

For every operation, `input` is an array of declarations. Each declaration has `name`, `source`, and `type`; an object map is invalid. Do not omit `ir_version`, replace the existing operations array with only the new operation, or assume the proposal endpoint merges a patch into the current service. The proposal endpoint stores the submitted IR as-is.

A successful tool envelope (`ok=true`) does not mean validation passed. Inspect `result.valid`; when it is `false`, use `result.diagnostics` to construct a corrected complete IR and submit a new proposal. Do not plan until validation returns `valid=true` for the same change-set hash. Do not apply it.

The final response must be one JSON object with exactly these fields: `schema_version` (1), `task_id` (`e009-add-readonly-operation`), `service_id` (`catalog`), `base_revision`, `change_set_id`, and `ir` (the complete proposed service IR).

Do not emit Markdown, explanations, or text outside that JSON object. If any step fails, report a failure JSON object instead of claiming success.
