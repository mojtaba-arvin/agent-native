# E-011 — Executable semantics and multi-process failure model

This directory contains:
- A deterministic, transport-neutral model of call lifecycle, retry classification, remaining-deadline propagation, capability attenuation, and idempotency replay/conflict.
- A two-process loopback HTTP fixture: the test runner is one process and the receiver is an independently started process with a durable SQLite idempotency/effect ledger.

Run:

```sh
python -m unittest discover -s experiments/e011 -v
```

The multi-process tests cover concurrent duplicate invocations, same-key/different-payload conflict, tenant/capability rejection, a receiver crash after durable commit but before response, restart and same-key reconciliation, and rollback on injected pre-commit failure.

**Evidence boundary:** this proves process isolation and durable reconciliation on one host with a shared SQLite database. It does not prove multi-node consensus, replicated storage, production credentials/workload identity, distributed cancellation, exactly-once external effects, or a production RPC choice. The receiver's headers are deterministic test fixtures, not an authentication implementation. E-011 does not replace E-008 outbox/inbox tests or E-002 storage conformance. E-007 real-agent lifecycle acceptance remains a separate promotion gate.
