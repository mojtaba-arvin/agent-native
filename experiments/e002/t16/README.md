# T16 controlled-host preparation

This directory contains T16 preparation tooling, the PostgreSQL product contract,
Go and Rust candidate product paths, and a deterministic open-loop workload
generator. It does not claim a benchmark result until the controlled-host matrix runs.


## Quickstart: one command on a dedicated Linux host

The recommended operator flow requires only Docker Engine/CLI, curl, and
GH_TOKEN on the host. Do not clone the repository, install Python/Git/gh/psql,
download artifacts, create PostgreSQL, or upload evidence manually.

Set GH_TOKEN to a GitHub personal access token (classic) with public_repo (or
repo) and read:packages scopes, then execute this single command:

    curl -fsSL https://raw.githubusercontent.com/mojtaba-arvin/agent-native/task/T16-image-digest-pipeline/experiments/e002/t16/one-command.sh | bash

The script builds or reuses the immutable image, runs the complete controlled
host matrix, and publishes all evidence to a new t16-results branch. It prints
the result URL when finished. Detailed behavior and the evidence layout are
documented in the One-command dedicated Linux execution section below.

## Manual fallback: pre-registration (not needed for the one-command flow)

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

Do not attach a persistent self-hosted runner to this public repository for
benchmarking. GitHub warns that arbitrary pull requests can execute untrusted
workflow code and compromise a persistent self-hosted machine. The safest
no-cost route is to run this script manually on an already available dedicated
physical Linux host from a trusted, clean checkout, without registering that
machine as a repository runner. A disposable ephemeral/JIT runner is an
alternative only if its host is dedicated and destroyed/reimaged after the
single job; do not expose long-lived credentials to it.

## Manual fallback: controlled-host setup (not needed for the one-command flow)

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
so a mid-matrix failure does not erase earlier evidence. `results.json` and
`report.md` are emitted after all 20 attempts have been recorded. Stop the PostgreSQL
container after preserving the generated evidence:

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
completion drain is reported separately. Completed throughput
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
  `request_id` and `error.code=CAPABILITY_DENIED`.

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
CPU and memory are included in candidate measurements. The Go HTTP path is
integration-tested; Rust compilation and PostgreSQL-pool tests are covered by
CI. The controlled-host runner performs full HTTP conformance against both
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


## One-command dedicated Linux execution

The supported operator entry point is one-command.sh. It is designed so the
host needs only a rootful Docker Engine/CLI, curl, and a GitHub token in GH_TOKEN. The current published image targets linux/amd64 (x86_64).
Python, Git, GitHub CLI, psql, taskset, Docker CLI inside the controller,
and PostgreSQL are supplied or launched by disposable containers; nothing is
installed into the host operating system.

Set GH_TOKEN once in the shell using a GitHub personal access token (classic).
For this workflow, grant repository write access (repo scope; public_repo is
sufficient for a public repository) and read:packages. The token is used to
create the build-trigger commit, inspect Actions runs/download the image-lock
artifact, authenticate to GHCR, verify repository attestations, and publish the
results branch. GitHub Packages currently requires a classic PAT for registry
authentication; fine-grained PATs do not support Packages access. Do not paste
the token into the command line or commit it to the repository.

From the dedicated Linux host, run:

    curl -fsSL https://raw.githubusercontent.com/mojtaba-arvin/agent-native/task/T16-image-digest-pipeline/experiments/e002/t16/one-command.sh | bash

The launcher creates a unique, small trigger commit on the T16 work branch.
That push starts the existing image workflow; the launcher waits for both the
image-validation and publish jobs, downloads the resulting image lock, checks
its source SHA and immutable digest, and launches the controller from that
exact image. The controller starts PostgreSQL on a separate physical core,
creates the operator declaration from the authenticated GitHub identity,
runs preflight and the 20-attempt matrix, verifies the image attestation, and
publishes the evidence to a new branch named t16-results/<run-id>-<sha>.

At completion, the command prints a direct link to the evidence directory in
that branch. The directory includes preregistration, host manifest, protocol,
raw request traces, per-attempt ledger, aggregate results, report, execution
logs, metadata, and SHA-256 checksums. Each invocation gets a new branch; prior
results are not overwritten. Failed or partial runs are also published with a
failed status when the controller has reached evidence initialization.

The controller uses the Docker socket and privileged host PID/cgroup access to
measure sibling containers and read host cgroup-v2 accounting. This is
root-equivalent access to the host; run only the reviewed, trusted T16 branch
on the dedicated machine. The host's physical exclusivity is recorded as the
operator's declaration, not represented as a property that software can prove.

The host still must satisfy the actual T16 contract: Linux x86_64, a rootful Docker daemon, cgroup v2 with
CPU/memory/cpuset controllers, at least three available distinct physical CPU
cores, and sufficient memory for a one-GiB candidate plus the separately
limited PostgreSQL container. GitHub Actions runners are explicitly rejected.
