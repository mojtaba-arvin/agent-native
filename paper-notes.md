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
