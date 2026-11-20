# T16 controlled-host preparation

This directory contains T16 preparation tooling and a deterministic open-loop
product workload generator. It does not implement the Rust/Go product request
path or claim a benchmark result.

## Pre-registration

On the dedicated Linux host, create an operator attestation JSON file:

```json
{
  "dedicated_physical_host": true,
  "host_id": "your-host-inventory-id",
  "attested_by": "operator",
  "attested_at": "2026-11-20T12:00:00Z"
}
```

The statement must be truthful: a cgroup or a GitHub-hosted VM is not proof of
exclusive physical-host tenancy. Do not create this file for a shared runner.

With a reachable PostgreSQL service and `psql` installed, invoke:

```bash
python3 experiments/e002/t16/preflight.py \
  --attestation /secure/path/t16-host-attestation.json \
  --source-sha "$(git rev-parse HEAD)" \
  --command python3 experiments/e002/t16/run.py \
  --postgres-dsn "$AGENT_NATIVE_E002_POSTGRES_DSN"
```

The output directory is `experiments/e002/t16/` and contains the immutable
pre-registration, host manifest, and protocol. The command above is a future
runner entry point: `run.py` is intentionally not present until the product
request path and candidate parity implementation exist. Do not run this
example as a benchmark or commit generated evidence.

## Open-loop request generator

The Go module in `loadgen/` schedules arrivals at a fixed 100 requests/second,
caps in-flight requests at 32, and deterministically shuffles the exact
60/20/10/10 request mix. It keeps expected 403 capability denials in completed
throughput, while treating transport errors and malformed response envelopes
as failures. Each JSONL record retains request metadata/body and response
metadata/body, but never stores bearer-token values.

The expected candidate HTTP contract is:

- `GET /v1/records/fixture-0001` → 200 with `request_id` and
  `data.id=fixture-0001`.
- `POST /v1/operations/validate` → 200 with `request_id` and
  `decision=allow`.
- `POST /v1/jobs` with the authorized fixture → 202 with `request_id`,
  non-empty `job_id`, and `status=queued`.
- `POST /v1/jobs` with the insufficient-capability fixture → 403 with
  `request_id` and `error.code=CAPABILITY_DENIED`.

Run generator unit tests with:

```bash
cd experiments/e002/t16/loadgen
go test ./...
go vet ./...
go build -o /tmp/t16-loadgen .
```

The generator's workload protocol is implemented; the candidate endpoints are
not. In particular, the existing Rust and Go E-002 servers remain toy
`/health`, `/work`, and `/stream` implementations. The generator therefore
cannot yet produce valid T16 candidate runs.

## Current evidence boundary

- `preflight.py` rejects GitHub Actions runners, requires Linux/cgroup v2,
  Docker, taskset, at least two host CPUs, a reachable PostgreSQL dependency,
  and an explicit operator attestation.
- The generated host manifest deliberately records
  `postgres_separate_from_candidate_cgroup: false`. A preflight cannot prove
  that the database is outside the candidate cgroup before the candidate is
  launched. A future runner must verify and update this only from observed
  process/cgroup data.
- The Rust and Go E-002 executables still implement the toy `/health`,
  `/work`, and `/stream` contract. They do not yet implement the product
  lifecycle, trusted tenant identity, capability checks, durable audit, or
  PostgreSQL-backed admission. The load generator does not disguise that gap.
- Shared GitHub-hosted CI is suitable for deterministic unit tests and
  compilation only; its measurements cannot satisfy the dedicated-host gate.
