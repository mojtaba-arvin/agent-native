# E-009 — Integrated framework-kernel vertical slice

**Status:** executable reference prototype; not a production framework and not a technology selection.

E-001 through E-008 proved useful pieces independently. E-009 connects the smallest meaningful backend slice into one process:

`service contract -> canonical IR -> route/input binding -> trusted authorization -> handler -> tenant-scoped durable repository -> durable job -> worker lease/fencing -> transactional outbox -> idempotent inbox -> HTTP response`.

It is deliberately implemented with the Python standard library as a semantic reference host. This does **not** select Python, the E-001 text syntax, SQLite, or HTTP/1.1 as Agent Native's final language, service representation, persistence substrate, or transport.

## What is integrated

- **Service model:** E-001 parser and semantic IR validator compile `catalog.an` into the runtime's immutable operation/route table.
- **Generic execution:** the kernel does not branch on operation names. It resolves a contract, binds typed path/query/header/body inputs, runs declared validation rules, authorizes effects, calls an injected operation handler, and validates the declared output record.
- **Authority:** E-004's default-deny policy model is enforced before application handlers run. The identity provider is a separate trusted dependency. Client request bodies and headers cannot supply principal, tenant, or grants.
- **Persistence:** a file-backed SQLite repository persists items and schema version. Queries are tenant-scoped in SQL, not filtered after retrieval.
- **Write safety:** item creation and idempotency record insertion commit in one transaction. Reusing an idempotency key with a different payload is a conflict; exact replay returns the original result.
- **Durable work:** `POST /items/rebuild` submits a tenant-scoped idempotent job. The job and `work.submitted` outbox event commit together. Jobs carry deadlines, attempt limits, leases, and monotonically increasing fencing tokens.
- **Cancellation and recovery:** cancelling a running job requests stop but does not release its lease. The worker/supervisor must acknowledge stop before the job can be requeued or become terminal. Expired relay leases are reclaimed with higher fencing tokens.
- **External-effect boundary:** job completion and its outbox event commit together. The relay uses at-least-once delivery; the SQLite inbox and consumer state change atomically so redelivery of the same event does not double-apply the local consumer effect.
- **HTTP host:** the standard-library host enforces a body-size limit, strict JSON, duplicate-header rejection, loopback binding, request IDs, bounded concurrent admission, and 503 load shedding.
- **Audit:** every capability decision is sent to an injected trusted audit sink before application code is called. Audit-sink failure is fail-closed.

## Run tests

From the repository root:

```sh
python -m unittest discover -s experiments/e009 -v
```

The suite covers service parsing, handler registration, typed input/output contracts, capability denial, audit failure, persistence across reopen, tenant isolation, duplicate idempotency, conflicting idempotency payloads, concurrent duplicate create, HTTP authentication, strict body parsing, and bounded admission. Durable-work tests cover idempotent job submission, lease fencing, retry limits, deadlines, stop acknowledgements, outbox lease reclamation, inbox conflict detection, consumer deduplication, HTTP job submission, real worker completion, redelivery, and the full single-process HTTP/worker/relay lifecycle. The local Agent runner's bounded task, proposal correlation, preservation checks, and no-apply gate have separate tests. A deterministic HTTP provider double exercises the full Ollama-to-Gateway adapter protocol; this is wiring evidence only, not a real model run.

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

## Let an agent inspect and propose service changes

The integrated Agent Gateway is a separate stdio process backed by the same `catalog.an` contract and E-005 validation/plan implementation. It supports the progressive or upfront disclosure arm and exposes only the E-005 inspect/propose/validate/plan tools. The common dispatch function is `agent.invoke`; no shell, arbitrary filesystem/network, secrets, deployment, or apply capability is exposed.

Start a session:

```sh
python experiments/e009/agent_gateway.py --arm progressive
```

The first NDJSON line is the session manifest. Send a tool call on stdin:

```json
{"type":"tool_call","request_id":"inspect-001","tool":"service.inspect","arguments":{"service_id":"catalog"}}
```

To discover one tool's exact input schema in the progressive arm:

```json
{"type":"tool_call","request_id":"describe-001","tool":"interface.describe","arguments":{"name":"service.propose"}}
```

An agent may then submit an immutable proposal against the inspected revision, validate it, and inspect its no-side-effect plan. The gateway does not apply a proposal; `service.apply` remains disabled. The session's arm changes only initial schema disclosure, not the operation catalog or dispatcher. This is an integrated control-surface prototype, not a final public protocol selection or a production authorization channel.

## Submit and process durable work

The demo server now exposes a job-submission operation protected by the `jobs.submit` capability. The idempotency key is required and belongs to the durable submission envelope:

```sh
curl -i -X POST http://127.0.0.1:8080/items/rebuild \
  -H "Authorization: Bearer $AGENT_NATIVE_DEMO_TOKEN" \
  -H "Idempotency-Key: rebuild-catalog-0001"
```

A new submission returns HTTP 202 and a durable ticket. Repeating the same request with the same tenant/key returns the original ticket; reusing the key with a different task payload returns a conflict. The ticket can be inspected through `GET /jobs/{id}`:

```sh
curl -i http://127.0.0.1:8080/jobs/<task-id> \
  -H "Authorization: Bearer $AGENT_NATIVE_DEMO_TOKEN"
```

Cancel a queued or running job through `POST /jobs/{id}/cancel`. A running job returns `cancellation_requested`; its lease is retained until the worker or supervisor acknowledges that it has stopped:

```sh
curl -i -X POST http://127.0.0.1:8080/jobs/<task-id>/cancel \
  -H "Authorization: Bearer $AGENT_NATIVE_DEMO_TOKEN"
```

Run one worker iteration and one outbox relay iteration. A worker claims a lease, runs the registered `catalog.rebuild` handler against only the job's tenant, and commits completion together with its outbox event:

```sh
python experiments/e009/work_cli.py --database /tmp/agent-native-e009.sqlite3 worker-once --worker-id worker-1
python experiments/e009/work_cli.py --database /tmp/agent-native-e009.sqlite3 relay-once --relay-id relay-1
```

Operations for stuck/deadline work are explicit. Request cancellation/stop for expired jobs, then acknowledge only after the worker process has actually stopped:

```sh
python experiments/e009/work_cli.py --database /tmp/agent-native-e009.sqlite3 request-stops
python experiments/e009/work_cli.py --database /tmp/agent-native-e009.sqlite3 worker-stopped \
  --task-id '<task-id>' --worker-id '<lease-owner>' --lease-token '<fencing-token>'
```

Inspect a job without exposing other tenants:

```sh
python experiments/e009/work_cli.py --database /tmp/agent-native-e009.sqlite3 job-show \
  --tenant-id demo-tenant --task-id '<task-id>'
```

All commands use the same SQLite database as the HTTP kernel. The worker and relay CLIs run one iteration. The HTTP host also starts one local worker loop and one outbox relay loop and joins both during graceful shutdown; this remains a single-process reference supervisor, not a distributed scheduler. The demo identity provider is in-memory and is intentionally not reusable as a production identity system.

## Run a bounded local Agent trial

The provider-neutral gateway can be driven by a real local Ollama model using the experimental adapter. This task asks the model to inspect every existing operation, propose exactly one read-only operation, validate and plan it, and return a content-addressed candidate. The runner independently checks that existing service definitions were preserved and that no apply call occurred.

Install/start Ollama separately and make the selected model available locally. Then run from the repository root:

```sh
python experiments/e009/local_agent.py --model qwen3-8b-local
```

The default endpoint is strictly limited to an HTTP loopback IP. Results are written under `/tmp/agent-native-e009-runs`, outside the checkout, with private directory/file permissions. Override the model, disclosure arm, or resource budgets explicitly when needed:

```sh
python experiments/e009/local_agent.py \
  --model qwen3:8b \
  --arm progressive \
  --max-input-tokens 24000 \
  --max-output-tokens 6000 \
  --max-tool-calls 20 \
  --max-wall-seconds 600
```

The run record includes provider-reported input/output token counts, tool-call count, duration, candidate path, and local verification result. The local verifier checks the inspected base revision, complete preservation of existing types/operations, exact requested operation, proposal hash correlation, successful validation, safe plan, and absence of apply. The JSONL trace contains tool requests/results but not model hidden reasoning. Input-token usage is checked after each provider response, so a single response can cross the configured aggregate input ceiling before the runner stops. This adapter is for a bounded local feasibility trial; it is not the E-007 benchmark runner or a private acceptance oracle. A locally verified candidate is not evidence of production correctness.

## Evidence boundary

This integrated slice proves only that the selected reference contracts can be composed in one runnable backend path. The demo identity provider is an in-memory fixture; there is no cryptographic workload identity, key rotation, distributed revocation, or production token validation. SQLite is single-node. The HTTP host is a bounded development host, not a hardened internet-facing server. The audit sink contract is fail-closed but does not itself provide durable remote audit storage. The worker/relay are single-node process prototypes; there is no distributed scheduler, authenticated remote worker identity, broker, multi-node consensus, worker kill escalation, schema rollback, distributed service discovery, inter-service transport, streaming, or production deployment story yet.

These limitations are now integration work in one kernel path rather than disconnected prose-only gaps. Any replacement language/runtime/database/transport candidate must pass the same black-box semantics before a product decision is made.
