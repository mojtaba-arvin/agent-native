# T16 controlled-host preparation

This directory contains preparation tooling for the T16 measurement. It does
not implement the product workload or claim a benchmark result.

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
  PostgreSQL-backed admission. The preflight does not disguise that gap.
- Shared GitHub-hosted CI is suitable for deterministic unit tests and
  compilation only; its measurements cannot satisfy the dedicated-host gate.
