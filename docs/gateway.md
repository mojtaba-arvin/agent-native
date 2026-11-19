# Service-independent Agent Gateway

The Gateway is a proposal boundary, not an execution endpoint.

## Flow

1. Resolve a service by manifest service ID.
2. Validate normalized inputs against the service IR.
3. Derive the resource path from the IR route and typed path inputs.
4. Classify only the explicitly supported effect IDs as read or write.
5. Authorize the operation's declared capability against the caller's principal,
   tenant, resource scope, and current grant.
6. Produce an immutable proposal with a candidate hash.
7. Revalidate the proposal and produce a no-apply plan bound to the same hash.

## Safety invariants

- The manifest and IR define the operation, inputs, capability, and effects.
- Unknown effects fail closed.
- The caller cannot add capabilities or effects to a proposal.
- A proposal is bound to service ID, service name, version, operation, route,
  normalized inputs, effects, and capability.
- Validation rechecks current grants; a stale validation cannot authorize a plan.
- The Gateway has no apply method and never invokes a service handler.
- Execution/apply remains a separate, owner-controlled future milestone.

The versioned JSON Schemas under schemas/gateway-*-v1.schema.json describe the
serialized proposal, validation, and plan contracts. Input value types are
validated against the selected service IR at runtime.
