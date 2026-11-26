# E-009 read-only operation task — delta proposal treatment

Add exactly one read-only operation to the trusted `catalog` service:

- Name: `get_item_by_normalized_name`
- Method: `GET`
- Path: `/items/by-normalized-name/{name}`
- Input: one declaration `{"name":"name","source":"path","type":"String"}`
- Output: `Item`
- Errors: `InvalidInput`, `NotFound`, `Unauthorized`
- Validation: `name.non_empty`
- Effects: `repository.read`
- Capability: `items.read`

Use the exact `base_revision` returned by the initial service inspection. Follow the selected disclosure treatment and Gateway `next_actions`; do not request information that the treatment forbids.

Submit exactly one append-only delta through `service.propose_delta`:

```json
{
  "service_id": "catalog",
  "base_revision": "<inspected revision>",
  "changes": [
    {
      "kind": "add_operation",
      "operation": {
        "name": "get_item_by_normalized_name",
        "method": "GET",
        "path": "/items/by-normalized-name/{name}",
        "input": [{"name": "name", "source": "path", "type": "String"}],
        "output": "Item",
        "errors": ["InvalidInput", "NotFound", "Unauthorized"],
        "validation": ["name.non_empty"],
        "effects": ["repository.read"],
        "capability": "items.read"
      }
    }
  ]
}
```

The Gateway owns the trusted base and materializes the complete canonical IR. Do not submit a snapshot, replace or edit existing operations, add a second change, or request mutation/deployment.

Immediately after an accepted proposal, call `service.validate` with its exact `change_set_id`. Only if `result.valid` is true, call `service.plan` with that same hash. The plan must be valid, `will_mutate=false`, and `will_deploy=false`. Never call `service.apply`.

Return only one JSON object with exactly these fields:
- `schema_version`: integer `1`
- `task_id`: `e009-add-readonly-operation`
- `service_id`: `catalog`
- `base_revision`: the inspected revision
- `change_set_id`: the accepted proposal hash
- `proposal_mode`: `delta`
- `intent_digest`: the accepted proposal's intent digest
- `materialized_ir_digest`: the accepted proposal's materialized IR digest
- `changes`: the exact one-element changes array submitted to the Gateway

Do not invent tool results, hashes, validation outcomes, or plan outcomes.