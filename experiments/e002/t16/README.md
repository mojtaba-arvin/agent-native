# T16 controlled-host preparation

This directory contains T16 preparation tooling, the PostgreSQL product contract,
Go and Rust candidate product paths, and a deterministic open-loop workload
generator. It does not claim a benchmark result until the controlled-host matrix runs.

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

With a reachable PostgreSQL service, `psql` installed, and the DSN exported, invoke:

```bash
export AGENT_NATIVE_E002_POSTGRES_DSN="postgresql://USER:PASSWORD@HOST:5432/agent_native"
```



```bash
python3 experiments/e002/t16/preflight.py \
  --attestation /secure/path/t16-host-attestation.json \
  --source-sha "$(git rev-parse HEAD)" \
  --command "python3 experiments/e002/t16/run.py --source-sha $(git rev-parse HEAD)"
```

After a complete run, publish the evidence bundle as a GitHub Release
asset bound to the exact source commit. The PR acceptance workflow downloads
`t16-evidence-<source-sha>`, verifies every SHA-256 entry and the PR-head
binding, then runs the unchanged `acceptance/T16.sh`. This keeps raw evidence
out of Git history while making it available to the protected acceptance gate.

```bash
SOURCE_SHA="$(git rev-parse HEAD)"
test "$(python3 -c 'import json; print(json.load(open("experiments/e002/t16/prereg.json"))["source_sha"])')" = "$SOURCE_SHA"
gh release create "t16-evidence-$SOURCE_SHA" \
  experiments/e002/t16/t16-evidence.tar.gz \
  --target "$SOURCE_SHA" \
  --title "T16 controlled-host evidence $SOURCE_SHA" \
  --notes "Controlled-host evidence for T16 source $SOURCE_SHA"
```

The output directory is `experiments/e002/t16/` and contains the immutable
pre-registration, host manifest, and protocol. `run.py` verifies the checked-out
source SHA and clean tracked worktree before building the candidates. CI covers
unit, PostgreSQL, container-build, and candidate conformance checks; none of
those shared-runner checks is a controlled-host capacity result. Do not commit
generated evidence.



### Runner security and no-cost execution

Standard GitHub-hosted runners are free for public repositories, but they are
fresh VMs (and the one-CPU `ubuntu-slim` option is a container on a shared VM),
not a dedicated physical benchmark host. Do not treat their measurements as
T16 capacity evidence.

Do not attach a self-hosted runner to this public repository for T16. The strict
acceptance contract rejects every `GITHUB_ACTIONS=true` execution, including
self-hosted and JIT runners, so a dedicated runner would still be ineligible.
GitHub also warns that public-repository pull requests can execute untrusted
workflow code on self-hosted machines. The practical no-cost route is to run
this script manually from a trusted, clean checkout on a dedicated physical
Linux host that is not registered as a GitHub Actions runner.

## Authentication and authorization contract

Both language candidates verify HMAC-SHA256 bearer tokens before accessing the
PostgreSQL product function. Tokens carry a fixed issuer/audience, trusted
issue/expiry times (maximum 15-minute lifetime), principal, tenant, and
capability grants with resource prefixes. The benchmark issuer creates fresh
10-minute tokens per repetition: the reader has `catalog.read`
scoped to `/v1/records/fixture-0001` and `jobs.create` scoped to
`/v1/jobs`; the denial principal has only the catalog-read grant. The signing key is generated per controlled run and passed
only through the candidate environment; bearer values are passed to the
load-generator environment and excluded from raw traces. Missing, malformed,
tampered, expired, wrong-tenant, missing-capability, and out-of-scope requests
fail closed.

## Controlled-host setup and execution

The host must be a dedicated physical Linux machine with at least three
available CPUs, cgroup v2, Docker, taskset, and psql. The PostgreSQL container
uses `--pid=host` so `pg_backend_pid()` can be mapped to the host cgroup for
separate-dependency verification. Reserve one CPU each for
the candidate, load generator, and PostgreSQL. Start PostgreSQL on the third
CPU in its own one-CPU cgroup before preflight:

```bash
eval "$(python3 - <<'PY'
import os
from pathlib import Path
selected, seen = [], set()
for cpu in sorted(os.sched_getaffinity(0)):
    topology = Path(f"/sys/devices/system/cpu/cpu{cpu}/topology")
    key = (
        (topology / "physical_package_id").read_text().strip(),
        (topology / "core_id").read_text().strip(),
    )
    if key not in seen:
        selected.append(cpu)
        seen.add(key)
    if len(selected) == 3:
        break
if len(selected) < 3:
    raise SystemExit("T16 needs three distinct available physical CPU cores")
print(f"CANDIDATE_CPU={selected[0]}")
print(f"LOADGEN_CPU={selected[1]}")
print(f"POSTGRES_CPU={selected[2]}")
PY
)"
docker run --detach --name t16-postgres --pid=host --network host \
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
ledger record. The ledger is appended after each completed or failed attempt,
so a mid-matrix failure does not erase earlier evidence. `results.json`,
`report.md`, and the SHA-256 evidence bundle are emitted after all 20 attempts
have been recorded. The runner exits with status 3 if any attempt failed
functionally; do not publish that partial bundle. Completed runs that miss an
SLO threshold remain valid measurements and are evaluated by the strict
acceptance gate. Stop the PostgreSQL container after preserving the generated
evidence:

```bash
docker rm --force t16-postgres
```

## Open-loop request generator

The Go module in `loadgen/` schedules arrivals at a fixed 100 requests/second,
caps in-flight requests at 32, reuses HTTP/1.1 keep-alive connections, and
deterministically shuffles the exact 60/20/10/10 request mix. Each JSONL record
captures scheduled offset, offered/start/finish timestamps, request metadata/body,
and response metadata/body. It keeps expected 403 capability denials in completed
throughput, while treating transport errors and malformed response envelopes
as failures; bearer-token values are never written to traces. Completed throughput
uses the exact 50-second offer window for 5,000 requests at 100 RPS; final
completion drain is reported separately.

The expected candidate HTTP contract is:

- `GET /v1/records/fixture-0001` → 200 with `request_id` and
  `data.id=fixture-0001`.
- `POST /v1/operations/validate` → 200 with `request_id` and
  `decision=allow`.
- `POST /v1/jobs` with the authorized fixture → 202 with `request_id`,
  non-empty `job_id`, and `status=queued`.
- `POST /v1/jobs` with the insufficient-capability fixture → 403 with
  `request_id` and `error.code=MISSING_CAPABILITY`.

Run generator unit tests with:

```bash
cd experiments/e002/t16/loadgen
go test ./...
go vet ./...
go build -o /tmp/t16-loadgen .
```

The original E-002 `/health`, `/work`, and `/stream` routes remain for earlier
experiments. T16 adds separate authenticated product routes to both candidate
binaries. They share the same PostgreSQL transaction function and use persistent
`psql` client-process pools inside each candidate cgroup, so the client-process
CPU and memory are included in candidate measurements. Both Go and Rust HTTP product paths are integration-tested against the same
PostgreSQL service in CI, including signed-token verification and resource-scope
denials. The controlled-host runner repeats full HTTP conformance against both
candidates before recording measured runs.

## Current evidence boundary

- `preflight.py` rejects GitHub Actions runners, requires Linux/cgroup v2,
  Docker, taskset, at least three host CPUs, a reachable PostgreSQL dependency,
  and an explicit operator attestation.
- The generated host manifest deliberately records
  `postgres_separate_from_candidate_cgroup: false`. A preflight cannot prove
  that the database is outside the candidate cgroup before the candidate is
  launched. `run.py` updates this only after comparing the observed PostgreSQL backend
  and candidate process cgroup paths and verifying their distinct CPU allocations.
- T16 now adds a separate authenticated product API to both candidate binaries. The
  original E-002 `/health`, `/work`, and `/stream` toy routes remain for the
  earlier experiments. The product API uses the same PostgreSQL transaction
  function and persistent psql client pool in both runtimes; candidate and
  PostgreSQL processes are accounted in separate cgroups. CI verifies both candidate HTTP paths against PostgreSQL, while the
  controlled-host runner repeats end-to-end conformance on the attested host before measuring.
- Shared GitHub-hosted CI is suitable for deterministic unit tests and
  compilation only; its measurements cannot satisfy the dedicated-host gate.
