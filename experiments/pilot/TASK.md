# Pilot task: add a read-only Catalog operation

Inspect the existing `Catalog` service and propose one new operation named `get_item_by_name`.

Required contract:

- Method: `GET`
- Path: `/items/by-name/{name}`
- Input: `name: String from path`
- Output: `Item`
- Errors: `[InvalidInput, NotFound, Unauthorized]`
- Validation: `[name.non_empty]`
- Effects: `[repository.read]`
- Capability: `"items.read"`

Constraints:

- Preserve the existing service name, version, types, and both existing operations exactly.
- Do not modify or remove any existing operation.
- Do not add any other operation, type, effect, capability, or field.
- The proposal must be based on the current service revision.
- Inspect the service before proposing the change.
- Validate the proposal and produce a no-side-effect plan.
- Do not apply the proposal, mutate state, access a network, or deploy anything.

A successful result is a proposal whose normalized service IR contains exactly the requested additional operation and preserves all existing service definitions, passes the trusted structural/effect validator, and has a plan that includes `repository.read` for the new operation without introducing any effect beyond those already declared by the existing service. The plan may also report `repository.write` because the unchanged `create_item` operation already declares it. The acceptance oracle must verify these properties independently and must not be exposed to the agent.
