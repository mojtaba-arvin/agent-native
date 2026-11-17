# E-009 — Integrated framework-kernel vertical slice

**Status:** executable reference prototype; not a production framework and not a technology selection.

E-001 through E-008 proved useful pieces independently. E-009 connects the smallest meaningful backend slice into one process:

`service contract -> canonical IR -> route/input binding -> trusted authorization -> handler -> tenant-scoped durable repository -> HTTP response`.

It is deliberately implemented with the Python standard library as a semantic reference host. This does **not** select Python, the E-001 text syntax, SQLite, or HTTP/1.1 as Agent Native's final language, service representation, persistence substrate, or transport.

## What is integrated

- **Service model:** E-001 parser and semantic IR validator compile `catalog.an` into the runtime's immutable operation/route table.
- **Generic execution:** the kernel does not branch on operation names. It resolves a contract, binds typed path/query/header/body inputs, runs declared validation rules, authorizes effects, calls an injected operation handler, and validates the declared output record.
- **Authority:** E-004's default-deny policy model is enforced before application handlers run. The identity provider is a separate trusted dependency. Client request bodies and headers cannot supply principal, tenant, or grants.
- **Persistence:** a file-backed SQLite repository persists items and schema version. Queries are tenant-scoped in SQL, not filtered after retrieval.
- **Write safety:** item creation and idempotency record insertion commit in one transaction. Reusing an idempotency key with a different payload is a conflict; exact replay returns the original result.
- **HTTP host:** the standard-library host enforces a body-size limit, strict JSON, duplicate-header rejection, loopback binding, request IDs, bounded concurrent admission, and 503 load shedding.
- **Audit:** every capability decision is sent to an injected trusted audit sink before application code is called. Audit-sink failure is fail-closed.

## Run tests

From the repository root:

```sh
python -m unittest discover -s experiments/e009 -v
```

The suite covers service parsing, handler registration, typed input/output contracts, capability denial, audit failure, persistence across reopen, tenant isolation, duplicate idempotency, conflicting idempotency payloads, concurrent duplicate create, HTTP authentication, strict body parsing, and bounded admission.

## Run the local demo

Use a sufficiently long development-only token. The sample host binds only to loopback.

```sh
export AGENT_NATIVE_DEMO_TOKEN='replace-with-a-long-random-local-development-token'
python experiments/e009/serve.py --database /tmp/agent-native-e009.sqlite3 --port 8080
```

Create an item (the idempotency key is a declared required header):

```sh
curl -i -X POST http://127.0.0.1:8080/items \
  -H "Authorization: Bearer $AGENT_NATIVE_DEMO_TOKEN" \
  -H "Content-Type: application/json" \
  -H "Idempotency-Key: create-item-0001" \
  -d '{"name":"Desk lamp"}'
```

Read it by ID or name using the `id` or `name` returned in the response.

## Evidence boundary

This integrated slice proves only that the selected reference contracts can be composed in one runnable backend path. The demo identity provider is an in-memory fixture; there is no cryptographic workload identity, key rotation, distributed revocation, or production token validation. SQLite is single-node. The HTTP host is a bounded development host, not a hardened internet-facing server. The audit sink contract is fail-closed but does not itself provide durable remote audit storage. There is no distributed service discovery, inter-service transport, streaming, background-worker integration, migrations/rollback beyond the initial schema version, or production deployment story yet.

These limitations are now integration work in one kernel path rather than disconnected prose-only gaps. Any replacement language/runtime/database/transport candidate must pass the same black-box semantics before a product decision is made.
