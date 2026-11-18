# Execution scorecard — 2026-11-18

This scorecard separates implemented code, executed tests, measured product behavior, and open acceptance gates. A design artifact or green unrelated workflow is never counted as product completion.

## Measurement rules

- **Implemented:** code is committed on `research/reboot-core`.
- **Executed:** the relevant workflow/job completed and its logs show the command ran.
- **Measured:** raw output or an artifact contains the metric, workload, source revision, environment, and failure count.
- **Accepted:** every preregistered acceptance invariant passes. A successful smoke does not imply acceptance.
- Unknown values remain **not measured**; they are not imputed as zero or converted into speculative percentages.

## E-007 — real Agent lifecycle

| Metric | Current evidence | Acceptance gate |
|---|---|---|
| Matched factorial cells | A–D implemented and validated by deterministic dispatch tests | 4/4 cells produce complete, provenance-valid artifacts |
| Proposal → validate → plan continuity | No successful real-model lifecycle recorded yet | Exact same 64-character proposal hash in all three events for each accepted cell |
| Trusted base preservation | Independent verifier implemented; no accepted live-model artifact yet | 100% of pre-existing declarations preserved and exactly the requested addition present |
| Plan safety | No accepted live-model plan yet | Every accepted cell: `valid=true`, `will_mutate=false`, `will_deploy=false` |
| Apply | Disabled for this cohort | 0 `service.apply` calls |
| Budget | Existing manifest pinned: Qwen3 8B, one repetition/cell, 120,000 input tokens, 6,000 output tokens, 20 tool calls, 3,000 seconds/run | No ceiling increase; all four traces retained including failures |

A 4/4 single-repetition cohort is feasibility evidence only. It is not a powered comparison or an estimate of general Agent success probability.

**Dispatch recovery:** the workflow retains manual `workflow_dispatch` and now has a narrow push-to-dispatch proxy. Only the exact marker file `experiments/e007/dispatch-request.json` on `research/reboot-core`, combined with the exact commit message `experiment(e007): dispatch one bounded factorial cohort`, may start the expensive job. The workflow validates the marker before model installation. Ordinary pushes do not match its path filter. Marker commit: [49a178c](https://github.com/mojtaba-arvin/agent-native/commit/49a178ced8751e5f9a5edbf96054603a55497532). This commit is a dispatch request, not evidence that the workflow completed.

## E-002 — runtime and storage

| Metric | Current evidence | Acceptance gate |
|---|---|---|
| Candidate build/conformance | Latest inspected run [44299814251](https://github.com/mojtaba-arvin/agent-native/actions/runs/44299814251): Go, Rust, WASI P2, BEAM jobs all successful | All four pass the same semantic suite at pinned revisions |
| Durable adapter conformance | No shared E-002 adapter implemented | 100% mandatory atomicity, idempotency, audit, recovery and crash-injection cases pass |
| Product workload | Not yet implemented across all runtime candidates | 60% authorized reads, 20% validate/plan, 10% durable job admission, 10% expected denial |
| Capacity target | No controlled product result yet | 100 completed requests/s, concurrency 32, p99 ≤100 ms, CPU ≤50%, measured under dedicated cgroup v2 |
| Decision-grade repetitions | Benchmark matrix remains skipped | 10 randomized repetitions × 5,000 requests per candidate after conformance; publish raw JSONL and summaries |

The existing process-tree sampler is diagnostic only. It is not a substitute for dedicated cgroup v2 CPU accounting. No runtime or storage engine is selected.

## E-009 — integrated kernel, trust and performance

| Metric | Current evidence | Acceptance gate |
|---|---|---|
| Kernel tests | [Run 44299814465](https://github.com/mojtaba-arvin/agent-native/actions/runs/44299814465): 110 E-009 tests passed | Keep regression suite green |
| E-010 tests | Same run: 3 E-010 tests passed | Keep demo limitations explicit; no arbitrary callback isolation claim |
| Client identity injection | Trusted identity is constructed by host fixture; no production identity adapter | 100% of attempts to submit principal, tenant or grants from client input are rejected |
| Runtime publication | Defensive ownership implemented; publication race contract not implemented | No request may observe a mixed runtime revision under concurrent publication |
| Product-path performance | [Run 44304494521](https://github.com/mojtaba-arvin/agent-native/actions/runs/44304494521), [artifact 14427192929](https://github.com/mojtaba-arvin/agent-native/actions/runs/44304494521/artifacts/14427192929): 5×1,000 requests, client concurrency 32/server cap 64; 1,090.21 req/s; p50 5.41 ms, p95 115.42 ms, p99 333.51 ms, max 835.82 ms; 0 unexpected statuses | **Harness passed; latency gate failed** (p99 target ≤100 ms, observed 3.3×). Preserve SQLite FULL audit durability; next isolate synchronous audit commit/group-commit cost |
| Controlled capacity | Not measured | Dedicated host/cgroup, warm-up, 10 repetitions, source and environment pinned |

The E-009 smoke is a real HTTP/SQLite/worker/relay workload on a shared CI runner. An initial 1k run had 12/1,000 503s; a 5k repeated run still had rare transport resets. The root cause was the TCP listen backlog being set after socket activation. Moving the backlog assignment before `super().__init__` removed transport errors in the next 5k run and improved p99 from ~1.07 s to 333.51 ms (about 69% lower). p99 remains 3.3× the 100 ms target and p95 is 115.42 ms. FULL-durability audit writes remain enabled. This is not a controlled capacity claim, cross-runtime comparison, or isolated CPU/memory accounting.

## E-011 — inter-service semantics

| Metric | Current evidence | Acceptance gate |
|---|---|---|
| Deterministic model | [Run 44303882125](https://github.com/mojtaba-arvin/agent-native/actions/runs/44303882125): **11/11 tests passed**, including seeded 10,000-transition state-machine exercise and idempotency outcome defensive-copy regression | Continue property-based transition sequences; distributed semantics still not proved |
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
- Added PostgreSQL 16.4 reference adapter with pinned psycopg 3.2.9; its 9-test suite passed in [workflow 44341683697](https://github.com/mojtaba-arvin/agent-native/actions/runs/44341683697), including 32-way idempotency races, process crash after commit/before response, audit outage and outbox fencing. Both SQLite (24 tests) and PostgreSQL (9 tests) pass independent single-node suites. Five deterministic 60-operation traces (300 operations total) now run against both engines; the suite compares status sequences, replay/conflict, record counts, outbox claim/ack and canonical digests. Four injected pre-commit failures also yield matching zero-state rollback. [Workflow 44344048163](https://github.com/mojtaba-arvin/agent-native/actions/runs/44344048163) passed. Broader property-based generation and crash/lease fault parity remain open. No runtime-candidate adapter parity, power-loss certification or product storage selection is claimed.

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
