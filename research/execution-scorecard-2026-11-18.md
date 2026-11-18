# Execution scorecard — 2026-11-18

This scorecard separates implemented code, executed tests, measured product behavior, and open acceptance gates. A design artifact or green unrelated workflow is never counted as product completion.

## Measurement rules

- **Implemented:** code is committed on the explicitly named branch and source SHA is recorded.
- **Executed:** the relevant workflow/job completed and its logs show the command ran.
- Evidence from `research/reboot-core` and `research/ci-policy-staging` is reported separately; the branches are divergent and are not treated as one integrated revision.
- **Measured:** raw output or an artifact contains the metric, workload, source revision, environment, and failure count.
- **Accepted:** every preregistered acceptance invariant passes. A successful smoke does not imply acceptance.
- Unknown values remain **not measured**; they are not imputed as zero or converted into speculative percentages.

## E-007 — real Agent lifecycle

| Metric | Current evidence | Acceptance gate |
|---|---|---|
| Dispatch capability | Solved: a one-shot marker-gated push route launched the real Qwen3 workflow; manual dispatch remains available | Exact branch, marker, request ID and commit subject validated before model provisioning |
| Real factorial cells | Run [44337025030](https://github.com/mojtaba-arvin/agent-native/actions/runs/44337025030), artifact [14444849207](https://github.com/mojtaba-arvin/agent-native/actions/runs/44337025030/artifacts/14444849207): C and A executed; D and B were not started after shared provider failure | 4/4 complete, provenance-valid cells |
| Agent task success | C failed with `proposal_repair_budget_exceeded`; A failed with `provider_http_500`; 0 accepted cells | At least one complete accepted lifecycle per cell for feasibility; later powered comparison requires repeated cohorts |
| Proposal → validate → plan continuity | No accepted real-model lifecycle; the A/C traces show proposal failures and incomplete provenance | Exact same 64-character proposal hash in proposal, validation and plan |
| Trusted base preservation / safe plan | No accepted real-model artifact | 100% trusted base preserved; valid plan with `will_mutate=false`, `will_deploy=false` |
| Apply | No apply occurred | 0 `service.apply` calls |
| Budget | Existing Qwen3 8B settings unchanged: 1 repetition/cell, 120,000 input tokens, 6,000 output tokens, 20 tool calls, 3,000 seconds/run | No ceiling increase; retain every failure artifact |

**Failure diagnosis:** the Ollama server log records HTTP 500 after 10m10s for the failing A-cell request; the CPU runner had generated near the 2,048-token per-call ceiling at about 3.45 tokens/s. The exact server error body was not captured, so OOM, timeout, or malformed output is not asserted. A bounded provider error-detail capture and regression test were added on `research/reboot-core`; [E-009 PR workflow 44353796608](https://github.com/mojtaba-arvin/agent-native/actions/runs/44353796608) passed 116 E-009 tests and 3 E-010 tests.

A separate one-cell A diagnostic has been staged with the same model settings and unchanged ceilings to capture the exact provider error before another full factorial. It is not a factorial acceptance run. No successful real-agent lifecycle is claimed yet.

## E-002 — runtime and storage

| Metric | Current evidence | Acceptance gate |
|---|---|---|
| Candidate build/conformance | [Workflow 44345013099](https://github.com/mojtaba-arvin/agent-native/actions/runs/44345013099): Go, Rust, WASI P2 and BEAM all passed | All candidate arms pass the same semantic suite at pinned revisions |
| SQLite reference storage | 24-test reference suite passed in the E-002 storage workflow | Mandatory atomicity, idempotency, audit, recovery and crash-injection cases pass |
| PostgreSQL reference storage | PostgreSQL 16.4 / psycopg 3.2.9; 9 conformance tests passed | Same mandatory contract; no production selection from CI alone |
| Cross-engine semantic parity | Same workflow passed 3 parity tests in [run 44356165574](https://github.com/mojtaba-arvin/agent-native/actions/runs/44356165574): 25 seeds × 60 generated operations = 1,500 operations per engine; identical normalized traces/digests; four pre-commit fault boundaries; expired-lease reclaim and stale-ack fencing; crash-after-commit reconciliation | Keep the same generated trace and fault suite green on both engines |
| Product workload / capacity | No cross-runtime product workload yet | 100 completed req/s, concurrency 32, p99 ≤100 ms, CPU ≤50%, measured under equivalent cgroup v2 limits |
| Decision-grade runtime repetitions | Benchmark matrix remains skipped | 10 randomized repetitions × 5,000 requests per candidate after runtime adapter conformance |

The two storage engines now have executable single-node conformance and cross-engine semantic parity. This does not certify power-loss behavior, replication, multi-node linearizability, production backup/restore, or runtime-candidate adapter parity. No storage or runtime winner is selected.

## E-009 — integrated kernel, trust and performance

| Metric | Current evidence | Acceptance gate |
|---|---|---|
| Kernel tests | On `research/ci-policy-staging`, [workflow 44355460886](https://github.com/mojtaba-arvin/agent-native/actions/runs/44355460886): 129 E-009 tests passed, including three new capacity-gate tests | Keep regression suite green |
| E-010 tests | Same run: 3 E-010 tests passed | Keep demo limitations explicit; no arbitrary callback isolation claim |
| Client identity injection | Six HTTP regression cases cover spoofed body claims, untrusted headers, unauthenticated requests and tenant isolation. `MemoryIdentityProvider` is explicitly a test/demo fixture, not production authentication | A production host-supplied identity provider must authenticate the bearer token and construct `RequestContext`; client principal, tenant and grants never become authority |
| Runtime publication | `RuntimeRegistry` atomically publishes monotonic frozen `RuntimeSnapshot` records; each request captures one snapshot. HTTP tests cover publication during an in-flight request and single-revision request handling | No request observes a mixed runtime revision; reject non-monotonic revisions |
| Product-path performance | 2 ms cgroup cohort [44355728291](https://github.com/mojtaba-arvin/agent-native/actions/runs/44355728291): 100.002 req/s, p99 252.021 ms; gate failed (9/10 reps >100 ms). 0.5 ms cgroup cohort [44357166863](https://github.com/mojtaba-arvin/agent-native/actions/runs/44357166863): 100.018 req/s, p99 27.465 ms, all 10 reps ≤69.714 ms, CPU 22.46%, peak memory 37.30 MiB; all capacity checks passed | 0.5 ms profile is a promising passing sample; **repeat it independently before selecting the audit window or claiming repeatable p99 compliance** |
| Controlled capacity / soak | Single shared GitHub host and one E-009 SQLite process; no cross-runtime or 30-minute soak | Paired randomized storage/runtime cohorts, then 30-minute soak and crash/recovery |

The 2 ms profile failed the p99 gate (252.021 ms, 9/10 reps >100 ms); a subsequent 0.5 ms cgroup profile passed (27.465 ms aggregate p99, all 10 reps ≤69.714 ms). The 0.5 ms profile is not selected yet: repeat it once more under the same cgroup settings. Telemetry shows no CPU quota throttling in that passing cohort, with measurable I/O pressure. The full comparison is in [E-009 performance evidence](../experiments/e009/performance-evidence-2026-11-18.md).

## E-011 — inter-service semantics

| Metric | Current evidence | Acceptance gate |
|---|---|---|
| Deterministic model | [Run 44337266191](https://github.com/mojtaba-arvin/agent-native/actions/runs/44337266191): **13/13 tests passed**, including seeded 10,000-transition state-machine exercise and idempotency outcome defensive-copy regression | Continue property-based transition sequences; distributed semantics still not proved |
| Retry and unknown outcome | Same-key reconciliation is modelled | No timeout after dispatch may be treated as proof of non-execution |
| Idempotency | In-memory tenant/operation/key model | Across two processes and durable restart, 100 concurrent duplicate requests yield exactly one logical admission |
| Capability attenuation | Audience, operation, resource and expiry escalation rejected by deterministic tests | Property tests find zero accepted escalation cases |
| Two-process transport | Not implemented | Separate processes and stores; fault injection at commit, response loss, delivery and restart; no transport selected before semantic tests pass |

## Repository state

- Working branch: `research/reboot-core`.
- Latest verified E-009 server/CI fix commit: `b7fe2cafc084e46c30ce1ef6819d1f7d5357a43e`; E-011 semantic hardening commit: `70d8de4a970f44fe8f15c3c62f9e4009d54a8f3a`; one-shot E-007 dispatch marker commit: `49a178ced8751e5f9a5edbf96054603a55497532`.
- `main` remains at `da3736c7ea4d239d1ea520d8b56025b4e3251b33`.
- PR #6 remains Open/Draft; no merge is authorized.
- E-009 CI now cancels stale branch runs and only executes its five-repetition performance workload when a pull-request head commit has the explicit subject `perf(e009): request five-run product-path measurement`; ordinary code/docs updates still run correctness tests but skip the expensive load test. The Actions connector does not expose push-triggered E-007 run listing; its marker commit is recorded as a dispatch request, not a verified model result.


## E-009 audit group-commit experiment — first controlled smoke requested

A bounded synchronous group-commit path has been implemented in `experiments/e009/audit.py`. Concurrent callers may share one SQLite WAL transaction, but each caller waits for the FULL-synchronous commit before dispatch can reach its application handler. The batch is bounded to 32 events and a 2 ms collection window by default. Commit failure is propagated to every caller in the batch; no caller is acknowledged on queue insertion alone.

New deterministic concurrency tests cover shared commits, read-after-return visibility, and fail-closed behavior when the batch commit fails. This is an implementation under test, not yet a measured performance improvement. The next five-repetition HTTP run will determine whether audit commit amortization materially reduces p95/p99 while preserving zero unexpected outcomes. If it does not, revert or redesign rather than relaxing durability.


## Supplemental execution evidence — 18 November 2026

This section supersedes older status snapshots above where they conflict. New work is split across two research branches; do not assume it is already included in PR #6.

### E-007 — live matched Agent execution

- Corrected run_factorial_pilot.sh: all 14 malformed doubled command-continuation backslashes were repaired; TSV parsing now uses positional cut -f1..15 so empty columns cannot shift fields.
- Added regression checks for exact one-backslash continuations and all 15 TSV columns. The corrected E-007 corpus workflow [44336919390](https://github.com/mojtaba-arvin/agent-native/actions/runs/44336919390) passed **94 tests**.
- One-shot retry-1 workflow [44337025030](https://github.com/mojtaba-arvin/agent-native/actions/runs/44337025030), pinned to corrected commit  b05ee81c6e995b9b58160bfc5ea140c3a39163e5, passed marker validation, factorial preflight, Ollama installation and Qwen3 model pull. The matched A-D model step was still running at the latest inspection. **No model acceptance is claimed until all four artifacts are inspected.**
- The run's pinned workflow revision did not yet include actions:read for the final run/artifact publication API. That permission was added on the branch after dispatch; if publication fails, inspect the uploaded artifact directly and correct the workflow before the next run.
- Current research/reboot-core head: ffede9c75014d10809986f110539ff88e70a6c9e. The in-flight run remains pinned to its recorded commit; do not silently substitute a newer branch head.

### E-002 — executable storage conformance

- Added SQLite reference adapter using a file-backed WAL database with synchronous=FULL, a versioned canonical request hash, and one transaction for job + outbox + idempotency + audit.
- The suite now includes pre-commit fault injection at every logical write boundary, audit-outage fail-closed behavior, same-key replay/conflict, tenant+operation scope, 32-way same-hash and different-hash races, process termination after commit/before response, append-only audit, and outbox lease fencing/stale-ack rejection.
- [E-002 workflow 44339334484](https://github.com/mojtaba-arvin/agent-native/actions/runs/44339334484): 24 Python conformance tests passed; Go, Rust, WASI P2 and BEAM jobs all passed their existing build/test/HTTP conformance and CPU sampler checks. The ten-repetition cross-runtime benchmark matrix remained skipped.
- Added PostgreSQL 16.4 reference adapter with pinned psycopg 3.2.9; its 9-test suite passed in [workflow 44341683697](https://github.com/mojtaba-arvin/agent-native/actions/runs/44341683697), including 32-way idempotency races, process crash after commit/before response, audit outage and outbox fencing. Both SQLite (24 tests) and PostgreSQL (9 tests) pass independent single-node suites. 25 deterministic 60-operation traces (1,500 operations per engine) now run against both engines; the suite compares status sequences, replay/conflict, record counts, outbox claim/ack, expired-lease reclaim, stale-ack fencing and canonical digests. Four injected pre-commit failures yield matching zero-state rollback, and real subprocess termination after commit/before response reconciles identically after reopen. [Workflow 44356165574](https://github.com/mojtaba-arvin/agent-native/actions/runs/44356165574) passed. Broader property-based generation and power-loss/replication remain open. No runtime-candidate adapter parity, power-loss certification or product storage selection is claimed.

### E-009 — product-path load and trust boundary

- [Five-repetition open-loop run 44338389527](https://github.com/mojtaba-arvin/agent-native/actions/runs/44338389527): 5,000 requests at 100 offered req/s; achieved 100.05 req/s; aggregate p99 11.13 ms; zero unexpected outcomes; server CPU 18.6% of one pinned core; FULL audit durability retained.
- [Ten-repetition open-loop run 44339252987](https://github.com/mojtaba-arvin/agent-native/actions/runs/44339252987): 10,000 requests; achieved 100.06 req/s; aggregate p99 73.82 ms; CPU 16.1%; zero unexpected outcomes. However, 2/10 repetitions had p99 above 100 ms (187.41 and 147.41 ms), and max latency was 275.56 ms. Aggregate target passes; repeatability gate does not.
- Both runs used a shared GitHub runner, one-core CPU affinity, and 5 ms /proc process-tree sampling. cgroup cpu.max was unlimited; neither is a controlled production-capacity certification.
- The ten-repetition 2 ms audit-window comparison [44339771024](https://github.com/mojtaba-arvin/agent-native/actions/runs/44339771024) completed 10,000 requests at 100.04 req/s, aggregate p99 7.85 ms, all ten repetition p99 values 6.70–8.29 ms, zero unexpected outcomes, and CPU 20.3%. But it produced 9,010 audit batches for 9,091 events versus 8,724 batches at 0.5 ms; CPU also rose from 16.1% to 20.3%. Do not attribute the lower tail to group-commit efficiency or change the default. A ten-repetition 0.5 ms replication [44340325781](https://github.com/mojtaba-arvin/agent-native/actions/runs/44340325781) is pending.
- Client identity spoofing tests reject body-supplied principal/tenant/grants and ignore identity headers when a valid authenticated token is present. RuntimeRegistry now publishes monotonic frozen runtime snapshots; each HTTP request pins one revision. [E-009 workflow 44341003787](https://github.com/mojtaba-arvin/agent-native/actions/runs/44341003787) passed **124 E-009 tests**, plus 39 E-001, 21 E-004 and 3 E-010 tests.

### E-011 — semantics hardening

- Capability envelope construction now rejects empty identity fields, non-frozenset or malformed authority collections, and non-integer/negative expiry; attenuation validates inputs before subset checks.
- [E-011 workflow 44337266191](https://github.com/mojtaba-arvin/agent-native/actions/runs/44337266191) passed compilation and **13 deterministic tests**. The workflow branch filter now includes all research branches.
- Still not implemented: persistent idempotency, cryptographic capabilities, cross-process cancellation, a real transport, or two-process crash/recovery evidence. E-007 acceptance remains the gate for the two-process slice.

### Branch and integration policy

- main remains unchanged at da3736c7ea4d239d1ea520d8b56025b4e3251b33.
- PR #6 remains Open/Draft with base main and head research/reboot-core; no merge was performed.
- Parallel implementation and measurements are on research/ci-policy-staging (latest at the time of this update: fba992195d2166c667c74f9051dcab33b31a7641). This branch is diverged from research/reboot-core (75 commits ahead, 8 behind). Do not merge it wholesale: it contains stale E-007 file versions. Reconcile only reviewed E-002/E-009/E-011 changes into the primary research branch after the in-flight experiments finish.


CI execution policy: E-002 and E-009 now set cancel-in-progress=false so a later commit does not terminate an active conformance or long-running performance cohort. The newest pending run may still replace an older pending run, but an in-progress experiment is preserved.


## Latest verified update — 18 November 2026, 20:53 local

This addendum supersedes conflicting older snapshots in the supplemental section above.

- **E-007:** the marker-gated route did execute the real Qwen3 workflow. [Run 44337025030](https://github.com/mojtaba-arvin/agent-native/actions/runs/44337025030) failed; artifact [14444849207](https://github.com/mojtaba-arvin/agent-native/actions/runs/44337025030/artifacts/14444849207) shows cell C failed with `proposal_repair_budget_exceeded`, cell A failed with `provider_http_500`, and D/B were not started after infrastructure abort. Zero accepted cells; no apply. The exact Ollama HTTP 500 response body was not captured in that run. Provider error detail capture plus a regression test is now on `research/reboot-core`; [PR CI 44353796608](https://github.com/mojtaba-arvin/agent-native/actions/runs/44353796608) passed 116 E-009 and 3 E-010 tests. A bounded one-cell A reproduction with unchanged Qwen3 settings is queued as [run 44354856148](https://github.com/mojtaba-arvin/agent-native/actions/runs/44354856148); it is diagnostic only, not a factorial acceptance result.
- **E-002:** [run 44356165574](https://github.com/mojtaba-arvin/agent-native/actions/runs/44356165574) passed Go/Rust/WASI P2/BEAM baseline jobs, 9 PostgreSQL 16.4 storage tests, and 3 cross-engine parity tests. 25 deterministic seeds × 60 operations were replayed against both SQLite and PostgreSQL (1,500 operations per engine) with matching semantic traces; four pre-commit fault points rolled back identically, expired-lease reclaim and stale-ack fencing matched, and post-commit process-crash reconciliation matched. The randomized cross-runtime benchmark matrix remains skipped.
- **E-009:** [run 44345238807](https://github.com/mojtaba-arvin/agent-native/actions/runs/44345238807) completed 10×1,000 open-loop requests at 100 req/s in a one-CPU/1-GiB cgroup-limited server container: 100.044 req/s, p99 6.536 ms, 21.66% of one core, 35.18 MiB peak cgroup memory, zero unexpected outcomes. FULL SQLite audit durability remained enabled. This passes the current single-node threshold, not a production or cross-runtime capacity claim.
- **E-011:** [run 44337266191](https://github.com/mojtaba-arvin/agent-native/actions/runs/44337266191) passed 13 deterministic tests, including seeded transition fuzzing and idempotency defensive-copy checks. Two-process persistence/transport remains unimplemented.
- **Branch separation:** `research/reboot-core` contains the E-007/E-009 diagnostic change and is the head of PR #6. `research/ci-policy-staging` contains the E-002/E-009 measurement work and remains divergent; these are not yet one integrated source revision. `main` remains unchanged at `da3736c7ea4d239d1ea520d8b56025b4e3251b33`; PR #6 remains Open/Draft.


- **E-009 repeatability correction:** the enforced [run 44355728291](https://github.com/mojtaba-arvin/agent-native/actions/runs/44355728291) completed 10,000 requests at 100.002 req/s with zero unexpected outcomes, but aggregate p99 was 252.021 ms; 9/10 repetition p99 values exceeded 100 ms. The capacity gate failed on p99 only. This supersedes any interpretation that the first cgroup cohort alone established repeatable target compliance. Cgroup CPU/I/O pressure telemetry has been added for the next diagnosis.

- **E-009 0.5 ms cgroup result:** [run 44357166863](https://github.com/mojtaba-arvin/agent-native/actions/runs/44357166863) passed all seven capacity checks: 10,000 requests, 100.018 req/s, p99 27.465 ms, every repetition p99 8.671–69.714 ms, 22.46% one-core CPU, 37.30 MiB peak memory, zero unexpected outcomes. Cgroup telemetry recorded zero CPU throttling, ~3.59 s full I/O pressure and zero memory pressure over ~100 seconds. Repeat this exact profile before changing the default or claiming stable SLO compliance.


## Integrated primary-branch verification — 18 November 2026

The reviewed E-002/E-009/E-011 files were selectively ported from the divergent staging branch onto the PR branch, preserving the newer E-007 and provider-diagnostic commits. Integration commit: 84da4f9430b34fa3b5fbddfdbdc99f989e7d6b2a.

All three integrated workflow suites passed on that commit:
- [E-002 run 44357946246](https://github.com/mojtaba-arvin/agent-native/actions/runs/44357946246): Go, Rust, WASI P2, BEAM and PostgreSQL jobs passed; 9 PostgreSQL conformance tests and 3 parity tests passed, with 25 seeds × 60 operations (1,500 operations per engine).
- [E-009 run 44357946247](https://github.com/mojtaba-arvin/agent-native/actions/runs/44357946247): 130 E-009 tests and 3 E-010 tests passed, including identity spoofing, runtime publication and capacity-gate regressions.
- [E-011 run 44357946328](https://github.com/mojtaba-arvin/agent-native/actions/runs/44357946328): 13 deterministic semantics tests passed.

The E-009 0.5 ms cgroup capacity cohort [44357166863](https://github.com/mojtaba-arvin/agent-native/actions/runs/44357166863) also passed on the verified source before selective port; an independent repeat [44358347560](https://github.com/mojtaba-arvin/agent-native/actions/runs/44358347560) is in progress. The E-007 single-cell provider reproduction [44354856148](https://github.com/mojtaba-arvin/agent-native/actions/runs/44354856148) is also in progress; it has not produced acceptance evidence yet.

main remains unchanged at da3736c7ea4d239d1ea520d8b56025b4e3251b33. PR #6 remains Open/Draft. No merge or apply was performed.

