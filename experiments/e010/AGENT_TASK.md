# E-010 — Isolated end-to-end apply demonstration

Task ID: `e010-sandbox-apply-lifecycle`

Extend the live `catalog` service with exactly one new read-only operation:

- Name: `get_item_by_normalized_name`
- Method: `GET`
- Path: `/items/by-normalized-name/{name}`
- Input: `name` from path, type `String`
- Output: `Item`
- Errors: `InvalidInput`, `NotFound`, `Unauthorized`
- Validation: `name.non_empty`
- Effects: `repository.read`
- Capability: `items.read`

Use the Agent Native service lifecycle in order:

1. Inspect the service and every existing operation.
2. Propose a complete IR snapshot preserving every existing service, type, and operation exactly, then append only the operation above.
3. Validate the exact proposal.
4. Plan the same change set. The plan must state `will_mutate=true`, `will_deploy=false`, and `sandbox_only=true`.
5. Call `service.apply` exactly once with the same change-set ID. This tool is available only in the isolated E-010 temporary sandbox; it cannot deploy or mutate production.
6. Confirm the apply response reports a successful runtime smoke test for the new route.

Return only this JSON object, replacing the placeholders with values from the actual tool results:

```json
{
  "schema_version": 1,
  "task_id": "e010-sandbox-apply-lifecycle",
  "service_id": "catalog",
  "base_revision": "<inspected revision>",
  "change_set_id": "<successful proposal change set id>",
  "ir": {}
}
```

Do not invent tool results, modify existing operations, add other operations, or call apply more than once.
