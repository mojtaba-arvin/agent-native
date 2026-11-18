# E-007 Ollama CPU-only inference and prompt-prefill baseline

**Date:** 18 November 2026  
**Scope:** infrastructure review of retained Ollama daemon logs for workflows [44149712970](https://github.com/mojtaba-arvin/agent-native/actions/runs/44149712970) and [44189163401](https://github.com/mojtaba-arvin/agent-native/actions/runs/44189163401).  
**Classification:** initial infrastructure evidence / threat to validity. This is not a model-capability benchmark.

## 1. Execution hardware and backend

Both workflows ran on GitHub-hosted ubuntu-latest, not on a GPU runner.

| Run | CPU reported by Ollama | Backend | Model threads | Model buffer |
|---|---|---|---:|---|
| 44149712970 | AMD EPYC 9V74 80-Core Processor | ggml-cpu-zen4 | 2 (of 4 visible) | CPU / CPU_REPACK |
| 44189163401 | AMD EPYC 7763 64-Core Processor | ggml-cpu-haswell | 2 (of 4 visible) | CPU |

The startup logs show CPU backend loading and CPU model buffers. No CUDA/ROCm/Vulkan backend or GPU model buffer was loaded. The workflow does not provision a GPU runner. This is direct evidence that these two Qwen3 trials used CPU inference; it is not merely an assumption based on the runner label.

The standard hosted runner exposed four logical CPUs to the process environment, while llama.cpp selected two model threads. The exact VM is ephemeral and differs between runs; these measurements must not be compared as a controlled hardware benchmark.

## 2. Correct interpretation of the 1,800-second run

The 1,800-second wall budget covered the entire agent run, including 15 completed model requests, tool dispatch, inspection, proposal repair, and generation. It was not 1,800 seconds available to the final prefill request.

The final request had:
- prompt length: 7,734 tokens;
- context: 8,192 tokens;
- cached prefix: 764 tokens;
- uncached prompt remainder: approximately 6,970 tokens;
- global wall time remaining when this request started: approximately 240 seconds;
- prompt progress at cancellation: 4,860 total prompt tokens, or 4,096 newly evaluated tokens after the cached prefix.

The daemon log records these prefill rates during that request:

| Newly evaluated tokens | Elapsed prompt time | Rate |
|---:|---:|---:|
| 1,024 | 50.97 s | 20.09 tok/s |
| 2,048 | 107.51 s | 19.05 tok/s |
| 3,072 | 170.23 s | 18.05 tok/s |
| 4,096 | 240.39 s | 17.04 tok/s |

The request was cancelled at the already-exhausted global 1,800-second deadline. The prompt had not completed, and no assistant decoding or service.validate tool call was recorded.

### Important correction: 2.38 tok/s was generation, not prefill

The preceding Ollama request reports 863 generated tokens in 362.45 seconds, approximately 2.38 generated tokens/second. That is decode throughput (eval time / tg), not prompt-prefill throughput. Dividing 4,860 prompt tokens by the full 1,800-second agent wall time and calling the result prefill speed is invalid because it mixes multiple completed requests and tool work.

The observed prefill rate for the final request was approximately 17–20 tokens/second, declining to 17.04 at the last recorded checkpoint. The uncached remainder was about 2,874 tokens; extrapolating the last observed rate suggests roughly 169 additional seconds of prefill under the same conditions. This is only a rough diagnostic extrapolation, not a measured completion time. The global wall budget had already expired, so the run did not provide that time.

## 3. The 3,000-second/context-16,384 run

The second log independently shows CPU-only inference on an AMD EPYC 7763 with two model threads. Its first prompt had 2,653 tokens and prefill completed at 11.71 tok/s; the next request processed 116 new tokens at 10.43 tok/s. The agent failed after two identical empty-argument service.inspect calls, after 267.785 seconds. This run does not provide a comparable long-prompt prefill observation because the agent never reached the inspection/proposal sequence.

## 4. What this evidence does and does not establish

**Established:**
- Both retained real-model trials ran on CPU-only GitHub-hosted workers.
- Both runs used a CPU-only inference path with two model threads; the performance impact relative to a GPU or higher-thread host is not quantified.
- In the 1,800-second run, the final prompt prefill remained incomplete at the global wall deadline; the model did not reach a decoding opportunity to choose service.validate.
- The 2.38 tok/s figure is decode throughput from the preceding request, not prefill.

**Not established:**
- That 17–20 prefill tokens/second is unusually slow for this exact CPU, quantization, Ollama build, and context configuration; no controlled hardware baseline exists.
- That GPU inference would complete the task or produce a valid validation/plan sequence.
- That the model would or would not call service.validate after completing prefill.
- A fixed 1,000-token isolated prefill benchmark. The daemon log provides useful request-level measurements but is not a preregistered standalone benchmark.

**Threat to validity:** the CPU-only two-thread hosted environment and the global wall budget confound any interpretation of the 1,800-second run as an agent decision failure. The artifact supports a valid proposal and an incomplete post-proposal prompt prefill; it does not support a conclusion about the model's ability to select validation. The 3,000-second run is a separate tool-argument adherence failure and should not be explained away as prefill.

## 5. Prompt-context growth and implementation response

The final prompt was 7,734/8,192 tokens, leaving little context headroom. The adapter previously replayed the full assistant/tool message history on every turn. The retained Ollama log also shows that only a 764-token prefix was reusable for the final request, despite the preceding prompt being 8,035 tokens; the generated assistant/tool history changed the prefix and limited KV-cache reuse.

A deterministic compaction path has now been added to experiments/e009/local_agent.py. After each tool batch it replaces the repeated assistant/tool transcript with:
- the original system/task/session-surface messages;
- the exact service-level inspection result;
- the exact inspected operation declarations, keyed by operation name;
- the complete tool sequence;
- compact recent tool outcomes, including validation/plan semantics and actionable Gateway diagnostics.

Raw provider responses and the append-only tool trace remain preserved as evidence. The compaction is therefore a prompt-construction optimization, not deletion of the forensic trace or relaxation of Gateway policy. A provider-double test checks that exact inspection declarations and latest diagnostics survive compaction. It does not establish real-model behavior; a real model probe is still required after deterministic CI.

## 6. Next bounded checks

1. Complete deterministic CI for the compaction helper and full E-009 suite.
2. Add/run a short-context, single-turn Qwen3 schema probe for the upfront service.inspect tool schema. This distinguishes a schema/tool-call problem from long-history effects; it is not a lifecycle eval.
3. Run a small, separately labelled infrastructure benchmark with a fixed approximately 1,000-token prompt, multiple repetitions, and provider-reported prompt-eval duration/count. Do not infer this baseline from decode throughput.
4. Do not dispatch another full Qwen3 lifecycle attempt or increase its budgets until the compacted prompt and short schema probe are validated. Keep every IR, preservation, same-hash validation, plan-safety, and no-apply gate unchanged.

## 7. Decision

Treat CPU-only inference and prompt-prefill completion as an explicit E-007 threat-to-validity factor. Keep the raw historical provider_transport_failure unchanged. For this artifact, record the evidence-derived diagnostic label prefill_not_completed_at_wall_deadline; do not generalize that label from a provider transport code alone. The runner cannot independently know prefill phase without correlated Ollama server telemetry, so the runtime failure class remains a wall-deadline resource stop while the forensic analysis adds the more specific phase observation.

No further Qwen3 budget increase is authorized. The next work is prompt compaction, deterministic schema checks, and a bounded infrastructure baseline—not another full real-agent run.
