# E-007 diagnostic workflow 44193765741: cold prefill and schema-probe review

**Workflow:** [44193765741](https://github.com/mojtaba-arvin/agent-native/actions/runs/44193765741)  
**Artifact:** [14378248130](https://github.com/mojtaba-arvin/agent-native/actions/runs/44193765741/artifacts/14378248130)  
**Classification:** infrastructure observation with a probe-design defect; not model-capability or lifecycle acceptance evidence.

## 1. Host and runtime facts

- Host CPU model string: AMD EPYC 7763 64-Core Processor.
- The GitHub-hosted VM exposed **4 logical CPUs** (lscpu: CPUs 0–3); this is the relevant visible allocation, not the host model's 64-core product name.
- Ollama loaded the ggml-cpu-haswell backend and CPU model buffers. nvidia-smi was unavailable; no GPU backend/model buffer appears in the retained daemon log.
- Ollama selected n_threads=2, n_threads_batch=2 out of 4 visible CPUs.
- Ollama client version: 0.40.16.

The workflow did not set num_thread explicitly, did not capture cgroup CPU quota/affinity, and did not compare thread counts. Therefore this artifact cannot establish whether 2, 4, or 16 requested inference threads is optimal. A 16-thread request on this four-CPU runner would be an oversubscription stress test, not a 16-core experiment.

## 2. Isolated cold-prefill result

The old diagnostic runner sent the same nominal 1,000-word prompt three times. Ollama reported 1,008 prompt tokens in each run:

| Repetition | Prompt tokens | Prefill duration | Prefill rate | Model load duration | Request wall time |
|---:|---:|---:|---:|---:|---:|
| 1 | 1,008 | 78.905 s | 12.77 tok/s | 5.31 s | 84.55 s |
| 2 | 1,008 | 79.219 s | 12.72 tok/s | 6.00 s | 85.24 s |
| 3 | 1,008 | 79.371 s | 12.70 tok/s | 6.00 s | 85.39 s |

These are cold/unloaded repetitions, not a warm-cache curve. The request explicitly set keep_alive=0, which unloads the model after each request. The repeated load durations and daemon logs corroborate that the model was reloaded. The result is a useful cold-prefill observation for this exact hosted runner, Ollama build, model quantization, and settings; it is not a general hardware performance baseline.

## 3. The previous short-schema probe is invalid as a schema-adherence test

The probe prompt was 264 tokens. Ollama reported:
- prompt prefill: 20.545 s / 12.85 tok/s;
- generation: 32 tokens / 6.506 s / 4.76 tok/s;
- returned tool call: agent.invoke with nested arguments: {};
- probe result: rejected by the diagnostic's expected-call assertion.

However, forensic review found a probe-construction defect: it sent the generic agent.invoke dispatch JSON Schema but omitted the actual Gateway session surface from the model messages. In this architecture, the dispatch function schema defines only the outer envelope. The tool-specific schemas (including the required service_id field for service.inspect) are delivered separately in the session surface. The production local_agent.py includes that surface in its base messages; the short probe did not.

Therefore the empty-arguments response cannot be interpreted as evidence that Qwen3 fails the actual upfront schema or that short context does not solve the issue. The probe tested an incomplete prompt. Its timing is still a valid short-request CPU observation, but its schema outcome is **invalid/inconclusive**.

The probe has been corrected to include the exact live Gateway surface JSON, following the production adapter's upfront-disclosure message structure. A regression test now prevents the surface from being omitted.

## 4. Cache interpretation

The historical 7,734-token lifecycle prompt reported 764 cached prefix tokens. That count alone does not show that Ollama caching is disabled or broken. Prefix reuse depends on the exact shared token prefix; changing the dynamic assistant/tool-history suffix can limit reuse even while the model remains loaded.

The old standalone probe cannot answer the cache question because keep_alive=0 deliberately unloads the model between repetitions, and it did not record prompt_eval_cached_count. The updated protocol now:
- keeps the model loaded with keep_alive=10m;
- measures nested 1k/2k/4k/8k prompt growth with exact shared prefixes;
- repeats each exact prompt unchanged to measure warm reuse;
- records provider-reported cached and uncached token counts;
- compares requested num_thread values 2, 4, and 16;
- records process CPU affinity and cgroup quota/cpuset.

The 16-thread arm is explicitly labelled oversubscription stress when the visible allocation is four CPUs. The updated matrix is not yet executed.

## 5. Implementation and validation state

Updated:
- ollama_diagnostics.py: explicit thread settings, nested prompt curve, keep-alive cache measurements, cgroup/affinity telemetry, and correct upfront session-surface injection in the schema probe.
- test_ollama_diagnostics.py: tests prefix growth, warm cache accounting, unknown cache telemetry, and inclusion of the live tool surface.
- e007-inference-diagnostics.yml: runs the diagnostic unit tests before installing/running Ollama; bounded job timeout raised to 45 minutes for the expanded matrix.
- [Benchmark protocol](2026-11-18-prefill-cache-thread-benchmark-plan.md): preregistered interpretation and stop rules.

The updated tests have not yet run in GitHub Actions. The next dispatch is gated by those tests. No full E-007 lifecycle attempt or resource-budget increase is authorized by this diagnostic.

## 6. Decision

This artifact establishes CPU-only cold-prefill at approximately 12.7 tokens/second on a four-logical-CPU GitHub-hosted VM with two Ollama model threads. It does **not** establish a 16-thread benefit, warm-cache behavior, or model inability to follow the actual upfront schema. The short-schema test must be repeated with the complete Gateway surface before interpreting empty tool arguments.

The 764/7,734 cache observation remains a trace fact, not a causal diagnosis. The new cache curve is designed to distinguish prefix-cache capability from the effect of changing conversation suffixes. No conclusions about Agent Native lifecycle competence are warranted from this infrastructure-only run.
