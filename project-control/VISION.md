# v0.1 execution vision

## Product outcome

Deliver a reproducible, single-node Python reference runtime for Agent Native that can load and execute services described by `.an` files; expose a typed, deterministic Gateway through which an agent can inspect, propose, validate, and plan read/write operations; and support a separately trusted, explicitly enabled development-only apply/rollback controller.

The framework remains an independently designed backend framework. The control plane in this directory governs project execution only; it is not part of the framework's runtime architecture.

## v0.1 acceptance outcomes

1. **Install and operate:** one documented installation command; one CLI for check, run, inspect, worker, and audit.
2. **Service independence:** services are loaded from a directory/manifest; adding a declarative service does not require editing the core.
3. **Useful agent authority:** read and write operations can be proposed, validated, and planned through explicit effects and capabilities.
4. **Separated mutation authority:** agent identity cannot apply; an independent controller can apply only in development after hash, conformance, and health gates.
5. **Recoverability:** publication is atomic; failed health checks restore the previous known-good version; audit and failure semantics are tested.
6. **Evidence and limits:** clean-environment quickstart, security model, compatibility/versioning rules, reproducible tests, and explicit non-goals/limitations.

## Explicit non-goals

Production deployment, multi-node operation, a selected production database/broker/runtime, E-011 inter-service transport, and production-grade identity are outside v0.1 unless a recorded decision changes scope.

## Principles

- Evidence before claims; preserve negative results.
- Default deny; no prompt-only security.
- Keep agent proposal and trusted apply authority separate.
- Prefer small independently reviewable changes over broad rewrites.
- Progress is acceptance criteria satisfied by reproducible evidence, not commits, files, or prose volume.
