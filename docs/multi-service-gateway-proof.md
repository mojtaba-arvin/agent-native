# M2-004 — multi-service Gateway proof

## Evidence

The same host-owned `AgentGateway` is exercised against two registered services:

- `catalog`: UUID-keyed read and item creation.
- `inventory`: filtered list and stock creation.

The second service is declared entirely by its `service.json`, `.an` IR,
declarative handler IDs/configuration, and default-deny `policy.json`. The
Gateway and runtime contain no service-name conditionals or Inventory-specific
branches.

## Assertions

- Both service IDs resolve through the same registry and Gateway API.
- Both services use the same proposal and validation contract.
- Inventory write operations can be proposed, validated, and planned.
- Missing and cross-tenant write grants are rejected.
- Planning is not execution: the Gateway exposes no `apply` method and does
  not invoke service handlers.

## Scope of this proof

This is an integration/architecture proof, not a production-readiness claim.
The existing Catalog and Inventory service declarations are reused; this
change adds tests and evidence documentation only. No core source, runtime,
Gateway, manifest, handler, or service configuration is modified.
