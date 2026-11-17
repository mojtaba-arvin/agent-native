# E-007 prefill, CPU-thread, and KV-cache diagnostic protocol

**Status:** protocol implemented; this matrix has not yet been executed.  
**Classification:** bounded infrastructure diagnostic, not model-capability or lifecycle acceptance evidence.

## Why the previous probe is insufficient

The earlier standalone probe sent `keep_alive=0` for each request. Ollama documents zero as immediate model unload, so those repetitions cannot measure warm prompt/KV-cache reuse across requests. The old script also did not set `num_thread` explicitly and did not record cgroup CPU quota or process affinity. Its timing observations remain useful as isolated cold-request diagnostics, but not as a cache-reuse comparison or controlled thread-count experiment.

The historical 64-core EPYC model string is host hardware metadata, not the CPU allocation visible to the process. The earlier runner exposed four logical CPUs. A request for 16 inference threads therefore tests oversubscription; it does not grant the job 16 physical or quota-backed cores.

## Preregistered bounded matrix

The updated diagnostic runner will execute one nested prompt-growth curve for each requested thread setting:

| Requested threads | Interpretation |
|---:|---|
| 2 | Historical model-thread setting |
| 4 | Matches the previously observed process-visible CPU count, subject to cgroup quota |
| 16 | Oversubscription stress arm only; not a 16-core comparison |

For each arm, the runner sends prompts targeting 1k, 2k, 4k, and 8k repeated words. The exact token count is taken from Ollama telemetry, not inferred from word count. Each prompt extends the previous exact prefix and is then sent a second time unchanged. The model remains loaded with `keep_alive=10m`.

This sequence distinguishes:
- cold/initial prefill at the first prompt;
- incremental prefill when a longer prompt preserves an earlier prefix;
- exact warm-repeat cache reuse for an unchanged prompt.

The run records requested `num_thread`, logical CPU count, process affinity, cgroup `cpu.max`, effective cpuset, `prompt_eval_count`, `prompt_eval_cached_count`, uncached token count, prefill duration/rate, load duration, decode telemetry, and wall time. Missing cache telemetry is recorded as unknown, never zero.

## Interpretation rules

1. Compare 2 versus 4 threads as the primary within-run CPU allocation comparison; interpret it only alongside recorded quota and affinity.
2. Treat 16 threads as an oversubscription stress observation. Do not describe it as using 16 cores.
3. Use Ollama's reported cached-token count to assess cache reuse. A model remaining loaded is necessary but does not by itself prove a cache hit.
4. Calculate uncached prefill throughput as `(prompt_eval_count - prompt_eval_cached_count) / prompt_eval_duration`, only when both counts and duration are present and valid.
5. A single curve is exploratory infrastructure evidence, not a statistically stable benchmark. Repeat only if this bounded run reveals a material thread/cache effect and the expected resource cost is justified.
6. Do not launch another full agent lifecycle attempt or increase its wall/context/token budgets based solely on an infrastructure speedup. First validate deterministic prompt compaction and short-schema behavior; keep all Gateway, IR, hash, validation, plan-safety, and no-apply gates unchanged.

## Implementation references

- Runner: [ollama_diagnostics.py](../ollama_diagnostics.py)
- Regression tests: [test_ollama_diagnostics.py](../test_ollama_diagnostics.py)
- Workflow: [e007-inference-diagnostics.yml](../../../.github/workflows/e007-inference-diagnostics.yml)

