# E-011 — Executable semantics model

This directory contains a deterministic, transport-neutral model of call lifecycle, retry classification, remaining-deadline propagation, capability attenuation, and idempotency replay/conflict.

Run:

```sh
python -m unittest discover -s experiments/e011 -v
```

The model is intentionally not a transport adapter, credential implementation, persistent idempotency store, concurrent/linearizable database, distributed cancellation mechanism, or two-process proof. In particular, the in-memory ledger does not prove atomicity or race safety. It exists to make protocol invariants executable before choosing a wire protocol.

The model is not a replacement for E-008 outbox/inbox tests or E-002 storage conformance. The two-process experiment remains gated on E-007 real-agent lifecycle acceptance.
