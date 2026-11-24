# T16 controlled-host preparation

This directory contains T16 preparation tooling, the PostgreSQL product contract,
Go and Rust candidate product paths, and a deterministic open-loop workload
generator. It does not claim a benchmark result until the controlled-host matrix runs.


## Quickstart: one command on a dedicated Linux host

The recommended operator flow requires only a rootful Docker Engine/CLI on Linux x86_64, curl, and
GH_TOKEN on the host. Do not clone the repository, install Python/Git/gh/psql,
download artifacts, create PostgreSQL, or upload evidence manually.

Set GH_TOKEN to a GitHub personal access token (classic) with public_repo (or
repo) and read:packages scopes, then execute this single command:

    curl -fsSL https://raw.githubusercontent.com/mojtaba-arvin/agent-native/task/T16-image-digest-pipeline/experiments/e002/t16/one-command.sh | bash

The launcher reuses or pulls one digest-pinned T16 image, runs the complete
controlled-host matrix, and publishes one compressed evidence archive as a
GitHub Release asset. The image contains the complete E-002/T16 runtime source
bundle and all runtime dependencies; after the image pull, the controller does
not clone the repository or install packages. GitHub API/Release traffic is
still required for provenance checks and evidence publication.

The launcher writes a timestamped transcript to
`/tmp/agent-native-t16-<UTC timestamp>/launcher.log`. Controller progress is
streamed to the terminal and retained in the same host directory, including
`controller.log`, `execution.log`, `preflight.log`, and the evidence
directory. On failure, partial evidence is retained there for diagnosis.
Results are not committed to Git or stored on result branches.

## Legacy manual preparation notes (historical; do not use for current runs)

The following manual instructions describe the earlier runner interface and are retained only as historical context. They are not a supported execution path for the current digest-pinned runner. Use the one-command launcher above.

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

### Legacy manual controlled-host setup (historical only)

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

The launcher uses only the host's existing Docker Engine/CLI and curl. It does
not install packages, start a helper image, or download separate PostgreSQL or
Docker CLI images. It resolves the current branch SHA through the GitHub API,
reuses a matching local T16 image when available, otherwise pulls the single
T16 image, then runs the controller by its immutable RepoDigest. The same image
digest is reused for PostgreSQL, candidate runtimes, and the load generator.
Subsequent runs against the same source SHA reuse cached layers; Docker checks
the registry manifest but does not redownload unchanged layers.

The host must be Linux x86_64 with rootful Docker, the local Docker socket,
curl, and GH_TOKEN. The token requires public_repo and read:packages. No
Python, Git, jq, gh, psql, taskset, Go, Rust, or package manager is needed on
the host.

Run:

    curl -fsSL https://raw.githubusercontent.com/mojtaba-arvin/agent-native/task/T16-image-digest-pipeline/experiments/e002/t16/one-command.sh | bash

The launcher verifies that the image revision equals the current source branch
head and runs it by digest. The controller checks the successful Actions build
for that SHA, verifies the GitHub image attestation through the benchmark
runner, starts PostgreSQL from the same digest, performs preregistration and
all 20 attempts, and uploads one compressed, checksum-manifested evidence
archive to a GitHub Release asset. All execution scripts are loaded from the
source bundle baked into that image; no runtime git clone or package install
is performed.

Results, logs, traces, and reports are not committed to Git and no result
branch is created. The command prints the direct asset URL. Release assets
remain outside the Git object database and can be deleted independently from
source history when the project's evidence-retention policy allows it.
