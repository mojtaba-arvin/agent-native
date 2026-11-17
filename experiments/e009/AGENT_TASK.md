# E-009 local Agent task

Inspect the live `Catalog` service and propose exactly one additional read-only operation:

- Name: `get_item_by_normalized_name`
- Method: `GET`
- Path: `/items/by-normalized-name/{name}`
- Input: `name: String` from the path
- Output: `Item`
- Errors: `[InvalidInput, NotFound, Unauthorized]`
- Validation: `[name.non_empty]`
- Effects: `[repository.read]`
- Capability: `items.read`

Preserve the service name/version, every existing type and field, and every existing operation exactly. Add no other operation, type, field, effect, or capability. Inspect first and use the exact inspected revision as the proposal base. Validate and plan the exact proposal. Do not apply it.

The final response must be one JSON object with exactly these fields: `schema_version` (1), `task_id` (`e009-add-readonly-operation`), `service_id` (`catalog`), `base_revision`, `change_set_id`, and `ir` (the complete proposed service IR).

Do not emit Markdown, explanations, or text outside that JSON object. If any step fails, report a failure JSON object instead of claiming success.
