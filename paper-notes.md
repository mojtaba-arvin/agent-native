# Paper notes — Agent Native

This file is the same-day research log for claims that may later enter a paper. Every entry distinguishes observed facts from interpretation and open questions. Do not promote implementation or provider-double results into real-model claims.

## Discoveries

### 2026-11-18 — Semantic contract split across the provider/Gateway boundary

**Observation.** The provider-facing function is the generic `agent.invoke` dispatch envelope. The live Gateway session surface separately exposes tool-specific schemas, including the required `service_id` for `service.inspect`. Therefore, provider-valid JSON at the dispatch-envelope level can still be semantically incomplete for the selected Gateway tool (for example, nested `arguments={}`). The provider schema is not a substitute for the Gateway's per-tool semantic contract.

**Mechanism.** The E-009 local runner now reads the live session surface and prevalidates the nested tool arguments before sending a request across the Gateway boundary. A missing `service.inspect.service_id` returns an actionable message: `service.inspect requires arguments.service_id; provide service_id: "catalog".` One repair is allowed; a repeated invalid request terminates with `prevalidation_repair_failed`. The trace records `execution_origin=runner_prevalidation`, preserving provenance.

**Evidence boundary.** The provider-double regression proves that invalid nested arguments do not reach `gateway_exchange` and that the repair budget is bounded. It does not prove that Qwen3 will always repair correctly. The real short-schema probe did emit the correct `service_id`; it is not evidence of the failure case itself.

**Paper angle.** Treat this as a trust-boundary/contract-alignment problem: the generic provider dispatch schema constrains the outer envelope, while the Gateway owns the selected tool's semantic preconditions. Runner-side prevalidation is a compatibility and containment layer, not a replacement for Gateway validation.

## Failures

### 2026-11-18 — Prior empty-arguments continuation failure

The previous 3,000-second/context-16,384 Qwen3 run emitted two identical `service.inspect` requests with empty arguments and stopped after 267.785 seconds with `ARGUMENTS_REQUIRED`. It did not reach proposal, validation, or plan. Commit B addresses this exact malformed nested-argument path, but no post-Commit-B real lifecycle has yet tested it.

## Evidence

### 2026-11-18 — Phase-1 prefill/cache and schema diagnostics

**Artifact:** workflow [44202267381](https://github.com/mojtaba-arvin/agent-native/actions/runs/44202267381), artifact [14382497052](https://github.com/mojtaba-arvin/agent-native/actions/runs/44202267381/artifacts/14382497052).

- Eight observations completed in 632.808 seconds against a 1,200-second total budget.
- Host: Intel Xeon Platinum 8370C, four exposed logical CPUs, CPU-only Ollama; no NVIDIA device was available.
- Cold 1k prompt: 1,012 prompt tokens; prefill 58.528s (2 threads) and 55.922s (4 threads), approximately 17.29 and 18.10 uncached tokens/s.
- Cold 4k prompt: 4,012 prompt tokens; 1,007 cached and 3,005 uncached tokens; prefill 205.067s (2 threads) and 197.044s (4 threads), approximately 14.65 and 15.25 uncached tokens/s.
- Exact warm repeats cached 1,011/1,012 and 4,011/4,012 tokens; request elapsed was 0.306–0.504s for the 2-thread repeats and 0.257–0.435s for 4-thread repeats.
- Live-surface short schema probe passed with 1,419 prompt tokens, 83.510s prompt prefill, 40 output tokens, and a correctly nested `service.inspect` call carrying `service_id="catalog"`.
- Four threads gave a small observed improvement over two threads on this host; the result does not establish a hardware bottleneck or justify 16-thread oversubscription.
- The 1k→4k nested-prefix experiment reused 1,007 tokens. Exact warm repeats reused almost the full prompt. This confirms prefix caching for these controlled prompts, but it does not identify the cause of the earlier post-proposal cache reduction in a real 14-turn history.

**Not established:** no complete `inspect → propose → validate → plan` lifecycle; no human-free lifecycle acceptance; no second repeat; no evidence that compaction is unnecessary.


### 2026-11-18 — Commit B isolated integration passed

The prevalidation change was ported as a single focused commit to `research/reboot-core` via [PR #18](https://github.com/mojtaba-arvin/agent-native/pull/18), then merged after the integrated-kernel check passed. Merge commit: `f41478fb0a7d414f90e2740173347a38a93fe415`. The PR changed only `experiments/e009/local_agent.py` and `experiments/e009/test_local_agent.py`; the CI suite passed 39 E-001 tests, 21 E-004 tests, and 80 integrated E-009 tests. The repeated-invalid-arguments provider-double test passed with the Gateway exchange patched to fail if invoked. This confirms the isolated integration and test wiring, not real Qwen3 repair behavior.

## Paper skeleton — claims and evidence requirements (2026-11-18)

This is an evidence plan, not manuscript prose. A claim may be promoted into the paper only when its required artifact is present and independently reviewable.

| Section | Claim intended for the paper | Evidence currently available | Evidence still missing / measurement required |
|---|---|---|---|
| 1. Problem and motivation | Generic provider function schemas do not fully express the selected Gateway tool's semantic preconditions | Live Gateway surface exposes per-tool schemas; Commit B provider-double verifies nested required-argument prevalidation | A real-model trace in which a provider-valid outer agent.invoke envelope contains semantically invalid nested arguments, followed by successful runner repair and Gateway acceptance |
| 2. Trust-boundary model | The Gateway owns the authoritative semantic contract; provider schema is only an outer dispatch envelope | Captured live surface JSON and E-009 request/response traces | A minimized formal contract diagram and negative/positive contract fixtures across multiple tool types, not only service.inspect |
| 3. Prevalidation and repair | Runner-side prevalidation prevents invalid nested arguments from crossing the Gateway boundary and gives the model an actionable repair | Commit B implementation; provider-double asserts gateway_exchange is never called for invalid required arguments; 80 integrated E-009 tests passed | First real Qwen3 lifecycle showing valid service.inspect(service_id="catalog") and no repeated arguments={}; a controlled malformed-arguments case demonstrating one successful repair |
| 4. Deterministic state compaction | A trusted Gateway-derived state ledger can replace repeated assistant/tool history without inventing state | Existing deterministic ledger helper and preservation/determinism tests; First Light prompt-state artifacts show compact ledger state | A paired real-model comparison (same task/settings, compaction off/on) with exact prompt hashes, cached/uncached token counts, prefill timings, and lifecycle outcomes |
| 5. Lifecycle correctness | A valid proposal must retain identity/hash through successful validation and non-mutating plan, with no apply | Deterministic scorer and provider-double tests; prior real run accepted one exact proposal | Two complete real-Qwen3 inspect → propose → validate → plan runs with matching proposal/validation/plan hash, raw trace, token telemetry, and timing |
| 6. Failure taxonomy | Agent, schema, validation, transport, and resource-budget failures are distinguishable | Existing E-007 failure classification and retained prior run artifacts; First Light classified repeated invalid tool call with two OPERATION_NOT_FOUND Gateway responses | A cross-run adjudication table with raw trace references and independent reviewer agreement; avoid interpreting repeated operation-name hallucination as prefill or validation failure |
| 7. Audit, lease, and fencing architecture | Authorization decisions are durably recorded before handlers, while work ownership is protected by lease/fencing invariants | E-009 SQLite audit, worker/outbox implementation, and 80-test integrated suite | One real HTTP request-to-audit-log demo with request correlation, durable reopen verification, and an exercised lease-expiry/fencing scenario |
| 8. Performance and cache behavior | Prefix stability and deterministic state representation affect prefill/cache reuse | Eight-observation diagnostic matrix; exact warm repeats cached 1,011/1,012 and 4,011/4,012 tokens; First Light per-turn prompt/payload hashes | Real lifecycle paired measurements across turns, cache counts from Ollama, and an attribution analysis for the prior post-proposal cache drop |
| 9. Evaluation protocol and reproducibility | A single script can reproduce the model/Gateway task and preserve all evidence | E-007 runner, pinned First Light settings, benchmark runner and artifact upload | A clean-checkout replay at a single source revision containing both Commit A and Commit B, including dependency/model checksums and artifact verification |
| 10. Limitations and external validity | Current results are prototype evidence, not production readiness or runtime superiority | CPU-only hosted runner context; E-002 diagnostic reports; explicit no-runtime decision | Controlled hardware, representative product workload, complete fault-injection suite, ecosystem/operability assessment, and broader model/task corpus |

### First Light evidence adjudication — 2026-11-18

**Artifact:** [workflow 44245011817](https://github.com/mojtaba-arvin/agent-native/actions/runs/44245011817), [artifact 14401855931](https://github.com/mojtaba-arvin/agent-native/actions/runs/44245011817/artifacts/14401855931).

- Revision: e0facbd737876e1f648303ea5e448cb4994cfd89; one Qwen3 8B run, temperature 0, top_p 1, seed 42, context 16,384, 3,000-second ceiling.
- The service-level inspect succeeded with service_id="catalog".
- The model then called service.inspect for get_item_by_normalized_name, which is the requested new operation and does not yet exist. Gateway returned OPERATION_NOT_FOUND.
- The exact invalid request was repeated; the runner stopped with repeated_invalid_tool_call.
- No proposal, validation, or plan occurred. This is not a validate opportunity and not a prefill failure.
- Provider telemetry: 8,735 input tokens, 159 output tokens; run duration 330.583 seconds. First prompt prefill: 2,690 tokens / 229.524 seconds.
- The prompt-state artifact records a compact Gateway state ledger. Thus compaction was active in this run; this failure does not establish a need to merge the opt-in compaction PR.
- Interpretation: the current failure is a model instruction-following/operation-selection failure at inspection. It is not evidence that Commit B's missing-required-argument path regressed, because no empty-arguments request was made.

**Do not claim:** E-007 acceptance, a successful validation opportunity, a compaction benefit, a provider-schema mismatch reproduction, or a hardware bottleneck from this run.



### 2026-11-18 — Second Light dispatch comparability defect (open)

**Observation.** The first post-First-Light workflow dispatch was triggered by the merge push for revision `6a083d555feea3c440e6544456cb6ce2c6858901` (workflow [44251029459](https://github.com/mojtaba-arvin/agent-native/actions/runs/44251029459)). A final revision audit found that this checkout contained the per-turn payload hash/metadata and provider deadline, but did not contain the deterministic compaction ledger or `prompt-states.jsonl` snapshots that were present in First Light revision `e0facbd`. The local `run_second_light.sh` preflight would have rejected this revision; the push-triggered workflow does not execute that local script.

**Adjudication.** Do not count workflow 44251029459 as a comparable Second Light or as a valid lifecycle repeat, regardless of its eventual agent outcome. Retain its artifact as diagnostic evidence only. It is not evidence about the operation guard's effect under the First Light prompt-state/compaction behavior.

**Correction.** PR [#27](https://github.com/mojtaba-arvin/agent-native/pull/27) selectively ports the deterministic Gateway-derived compaction ledger, per-turn prompt-state snapshots, provider-to-state hash correlation, payload metadata, operation-name guard, and absolute provider deadline onto the integration branch. It does not merge PR #17. A new Second Light dispatch is gated on this PR's complete CI and a verified preflight against the resulting merge SHA.

**Boundary.** No conclusion about Qwen3's repair behavior, validation progress, or lifecycle success is available from this in-progress run. Preserve its raw artifact and classify it separately.

**Corrected dispatch.** The complete instrumentation port was merged as `f86f1709441f65ef358461f242920b82f5d5b671` (PR [#27](https://github.com/mojtaba-arvin/agent-native/pull/27), integrated-kernel CI passed). `run_second_light.sh` is pinned to that exact SHA. The comparable workflow [44252556986](https://github.com/mojtaba-arvin/agent-native/actions/runs/44252556986) was dispatched from the subsequent metadata/workflow commit `a0c3f4c785f16bfa2d4a5667d99b514875e62a78`; the relevant source blobs are identical to the pinned SHA for `local_agent.py`, `eval_runner.py`, `AGENT_TASK.md`, and the eval case. The task and eval-case blob hashes also match First Light exactly. The run is currently in progress; no lifecycle result is claimed yet.


### 2026-11-18 — Absolute request deadline under slow-drip transport

**Observation.** The previous urllib timeout was an inactivity timeout: a peer that emitted response bytes more frequently than the socket timeout could keep a request alive beyond the benchmark's remaining wall budget.

**Correction.** The E-007 diagnostic client now uses a monotonic timer and shuts down the active response-owned socket. The remaining shared benchmark budget is still passed as the per-request deadline; no timeout was increased.

**Regression evidence.** [PR #24](https://github.com/mojtaba-arvin/agent-native/pull/24) merged as 40b9d9f70e32a848d54a8569888d38a332830268. [CI run 44247617828](https://github.com/mojtaba-arvin/agent-native/actions/runs/44247617828) passed. The slow-drip test sends bytes every 50 ms against a 250 ms absolute deadline and verifies interruption within one second.

**Boundary.** This test establishes a hard wall deadline for the diagnostic HTTP request. It does not establish that all subprocess/Gateway IPC or cleanup paths are bounded by the same timer, and it is not a real-model lifecycle result.



### 2026-11-18 — E-010 isolated apply path (in progress)

**Implementation.** PR [#28](https://github.com/mojtaba-arvin/agent-native/pull/28) added an explicitly injected sandbox-apply callback. The default E-009 interface still returns `APPLY_DISABLED`; apply is enabled only when the Gateway is started with `--sandbox-apply` and a private sandbox directory. Apply rechecks the base revision, successful validation, matching plan, approval requirements, and deployment prohibition; change-set replay is idempotent.

**Runtime demonstration.** The E-010 coordinator constructs a new immutable `ServiceRuntime` snapshot with one allowlisted built-in handler, publishes it only inside a temporary SQLite sandbox, executes `GET /items/by-normalized-name/BLUE-LAMP`, and retains the append-only audit database. The integrated Gateway test verifies inspect → propose → validate → plan → apply → runtime request → audit, and verifies that apply before validation/plan fails closed.

**Real-agent run.** PR [#29](https://github.com/mojtaba-arvin/agent-native/pull/29) added the opt-in Qwen3 runner and a gated workflow. Workflow [44254279785](https://github.com/mojtaba-arvin/agent-native/actions/runs/44254279785) is currently executing against pinned source revision `61e848f907a597f1279df6532a6d5e58018d55ff`, with the same per-run model budget as E-007. This is a sandbox-only demonstration; it is not evidence of production deployment or production apply. Record the final trace, runtime response, and SQLite audit artifact before making a lifecycle-success claim.
