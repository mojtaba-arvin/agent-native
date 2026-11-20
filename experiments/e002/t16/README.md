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


## Controlled-host setup and execution

The host must be a dedicated physical Linux machine with at least three
available CPUs, cgroup v2, Docker, taskset, and psql. Reserve one CPU each for
the candidate, load generator, and PostgreSQL. Start PostgreSQL on the third
CPU in its own one-CPU cgroup before preflight:

```bash
eval "$(python3 - <<'PY'
import os
cpus = sorted(os.sched_getaffinity(0))
if len(cpus) < 3:
    raise SystemExit("T16 needs at least three available CPUs")
print(f"CANDIDATE_CPU={cpus[0]}")
print(f"LOADGEN_CPU={cpus[1]}")
print(f"POSTGRES_CPU={cpus[2]}")
PY
)"
docker run --detach --name t16-postgres --network host \
  --cpus=1 --cpuset-cpus="$POSTGRES_CPU" --memory=2g \
  --env POSTGRES_HOST_AUTH_METHOD=trust \
  --env POSTGRES_DB=agent_native \
  postgres:16.4 -c listen_addresses=127.0.0.1

export AGENT_NATIVE_E002_POSTGRES_DSN='postgresql://postgres@127.0.0.1:5432/agent_native?sslmode=disable'
```

Create the operator attestation file securely, then preregister the exact
checked-out commit and execution command:

```bash
SOURCE_SHA="$(git rev-parse HEAD)"
python3 experiments/e002/t16/preflight.py \
  --attestation /secure/path/t16-host-attestation.json \
  --source-sha "$SOURCE_SHA" \
  --command "python3 experiments/e002/t16/run.py --source-sha $SOURCE_SHA"

python3 experiments/e002/t16/run.py --source-sha "$SOURCE_SHA"
bash acceptance/T16.sh
```

The matrix runner builds both candidate images from the checked-out source,
verifies the PostgreSQL and candidate cgroups are separate and CPU-pinned,
runs product conformance before measurement, then executes ten randomized
5,000-request repetitions per candidate. Each repetition gets a fresh
one-vCPU/one-GiB candidate container, a 250-request warm-up, a measured
open-loop run, cgroup CPU/memory/OOM accounting, a raw JSONL trace, and a
ledger record. It writes `ledger.jsonl`, `results.json`, and `report.md`
only after the corresponding evidence is collected. Stop the PostgreSQL
container after preserving the generated evidence:

```bash
docker rm --force t16-postgres
```

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
- T16 now adds a separate authenticated product API to both candidate binaries. The
  original E-002 `/health`, `/work`, and `/stream` toy routes remain for the
  earlier experiments. The product API uses the same PostgreSQL transaction
  function and persistent psql client pool in both runtimes; candidate and
  PostgreSQL processes are accounted in separate cgroups. CI verifies the Go
  HTTP path and Rust PostgreSQL pool, while the controlled-host runner performs
  end-to-end conformance against both candidates before measuring.
- Shared GitHub-hosted CI is suitable for deterministic unit tests and
  compilation only; its measurements cannot satisfy the dedicated-host gate.
