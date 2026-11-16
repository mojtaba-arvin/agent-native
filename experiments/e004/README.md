# E-004 security and capability model — executable reference prototype

This is a provisional reference model for trusted runtime enforcement. It is not a production security implementation and does not make the system secure by itself.

## Security invariants under test

- Default deny; authority exists only in explicit grants passed in the request context.
- Every operation declares a required capability and an allowed effect set.
- Runtime checks requested effects against the operation contract before performing effects.
- Grants are principal-bound, tenant-bound, capability-bound, optionally resource-scoped, and optionally time-bounded.
- Resource scopes use path-segment boundaries, not unsafe string-prefix matching.
- Delegation can only attenuate: it cannot change tenant/capability, widen resource scope, extend expiry, or exceed delegation depth.
- Every decision produces a structured audit event with a stable reason code.
- Missing identity, tenant, grant, or a matching policy is denied.

## Run

```sh
python -m unittest discover -s experiments/e004 -v
```

## Explicit limitations

- Grants are in-memory data structures, not cryptographically authenticated capability tokens.
- No key management, revocation distribution, policy compilation, network identity, workload identity, or secure audit transport is implemented.
- No proof of non-interference or isolation is claimed.
- The reference model tests policy semantics only; the eventual compiler/runtime must enforce these checks at every effect boundary, not rely on generated prompts or agent discipline.
