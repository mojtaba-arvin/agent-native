# E-007 future model-cohort and corpus expansion plan

**Status:** future work only — not executed and not current evidence  
**Purpose:** define a bounded path from one fixed-task local-model diagnostic to a broader, independently scored comparison.

## Current limitation

The available real-model cohort consists of one task (E-009 complete-IR proposal), one model family/size (`qwen3:8b`), one local Ollama adapter, and three repetitions at `temperature=0`, `seed=42`. Those three attempts reproduced the same failure path with prompt-cache reuse. They do not estimate model-to-model variance, task-to-task variance, or stochastic success rates.

The public E-007 corpus currently contains ten tasks. It is a useful starting set, not a sufficiently broad distribution for general claims about backend-agent capability.

## Proposed staged design

### Stage A — broaden the task set

Retain all ten existing tasks and add at least twenty new cases, for a target of thirty distinct tasks. Stratify the suite across at least ten backend capability areas (service representation/schema evolution, data correctness, tenant isolation, idempotency, deadlines/retries, streaming/backpressure, durable recovery, capability security, regression repair, safe planning, plus relevant integration/failure scenarios). Each task should have a clear, independently verifiable acceptance oracle.

Tag each task by difficulty (for example, constrained, standard, adversarial) and by risk/effect class. Include both successful-path and failure-recovery cases. Do not count prompt variants of the same underlying task as distinct independent tasks.

### Stage B — compare at least three model capability levels

Use at least three pinned, materially different model capability/size levels:
1. **Constrained/small:** a lower-capacity model with a restricted context/tool budget.
2. **General/mid-tier:** a capable general-purpose coding model.
3. **Advanced/high-capability:** the strongest available coding agent within the research budget.

Exact model identifiers, immutable revisions/digests, quantization, provider/runtime version, context size, sampling options, tool policy, and resource budgets must be pinned before the cohort starts. Do not imply that models from different providers are directly comparable unless the same task environment, tool interface, and acceptance criteria are held constant.

### Stage C — separate deterministic debugging from stochastic evaluation

Keep a deterministic replay condition (temperature zero and fixed seed) for reproducing regressions. For stochastic evaluation, use a pre-registered non-zero temperature (e.g. 0.7 where supported) and a distinct recorded seed for each repetition. Never call repeated same-seed temperature-zero executions independent samples.

Retain the raw run trace, provider usage metadata, model revision, seed, temperature, prompt/tool schema hashes, and termination reason for every run. Explicitly record prompt/KV cache use when the provider exposes it; do not mistake prefix-cache reuse for response-cache replay.

### Stage D — sample-size and analysis plan

A possible exploratory floor is 30 tasks × 3 model levels × 5 seeds = 450 task runs. This is a workload-planning reference, **not a claim that 450 is statistically sufficient**. A confirmatory sample size must be calculated from:
- a pre-registered primary outcome (task acceptance under an independent oracle);
- the smallest practically meaningful between-model difference;
- pilot acceptance rates and task/run variance;
- desired confidence level and statistical power;
- clustering/repeated-measures structure by task and model.

Use task-level paired comparisons where appropriate, stratified bootstrap intervals, and mixed-effects or otherwise cluster-aware analysis rather than treating all repeated runs as unrelated observations. Publish raw counts and uncertainty intervals. Report every failure, budget stop, timeout, and excluded infrastructure-invalid trial.

## Metrics and acceptance

Primary outcome: independently verified task acceptance. Secondary outcomes: input/output tokens, actual provider cost where billed, local compute-cost basis where available, tool calls, repair proposals, validation rejections, elapsed time, human interventions, resource-budget stops, and failure taxonomy.

No model is “better” based only on speed or tokens. Compare total cost per accepted task subject to safety, data-integrity, and runtime/resource hard gates. The scorer/oracle must remain outside the agent-visible task workspace.

## Resource envelope and stop rules

Run a small calibration subset before dispatching the full cohort. Estimate wall time, tokens, artifact volume, and provider charges. Set aggregate per-cohort token, wall-time, and monetary budgets. Stop before launching another run if the worst-case reservation cannot fit; record it as not started and not as an agent failure. Do not cache model weights or expand runner size without a measured benefit and explicit resource review.

## Claim boundary

Until this plan is executed, the repository has no three-tier model cohort, no broad 30-task experimental set, and no confirmatory model-comparison result. The present E-007 evidence is one deterministic failure reproduction across three executions only.
