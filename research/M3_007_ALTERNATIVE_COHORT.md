# M3-007 — Alternative CPU model cohort runbook

**Cohort:** `m3-007-alternative-cpu-v1`  
**Status:** preregistered candidate set; no model is qualified.

This cohort is separate from the historical Granite 4.0 experiments. It must not modify
`model_candidates.json`, `model-lock.json`, E-007 Qwen3 A–D manifests, or their raw
artifacts.

## Fixed candidate set

| Nominal tier | Ollama tag | Quantization |
|---|---|---|
| Weak | `qwen3:1.7b` | Q4_K_M |
| Medium | `granite4.2:3b` | Q4_K_M |
| Strong | `qwen3:4b` | Q4_K_M |
| Reserve only | `gemma4:e2b` | not in this cohort |

Tier labels are size-based only; they do not assert relative task capability. The exact
Ollama runtime and Python container images are pinned in `model_candidates_v2.json`.
The model digests are deliberately absent until a bootstrap run observes them.

## Required sequence

1. **Bootstrap:** manually dispatch the workflow on `research/reboot-core`:
   `gh workflow run m3-007-alternative-models.yml --repo mojtaba-arvin/agent-native --ref research/reboot-core -f phase=bootstrap`.
   This downloads only the three public Ollama tags and uploads
   `bootstrap-observation.json`. It performs no inference.
2. **Seal:** download the `m3-007-bootstrap-<run-id>` artifact and inspect the complete
   observation. Generate the candidate manifest and lock only from that observation:
   ```bash
   SOURCE_SHA="$(jq -r .source_sha bootstrap-observation.json)"
   python3 experiments/e007/m3_alt_model_cohort.py seal \
     --candidates experiments/e007/model_candidates_v2.json \
     --observation bootstrap-observation.json \
     --source-sha "$SOURCE_SHA" \
     --candidates-output /tmp/model_candidates_v2.json \
     --lock-output /tmp/model-lock-v2.json
   ```
   Replace the candidate manifest with the generated file and add
   `experiments/e007/model-lock-v2.json` in the same commit. Never type or infer digest
   values by hand. The lock remains `locked_not_qualified`.
3. **Offline verification:** dispatch on the exact commit containing the sealed
   manifest and lock. This is a fresh hosted runner and a fresh model download; the
   verification container has no network. Preserve the uploaded
   `verification-report.json` and its workflow run ID.
   ```bash
   gh workflow run m3-007-alternative-models.yml --repo mojtaba-arvin/agent-native --ref research/reboot-core -f phase=verify
   ```
4. **Trial:** dispatch on the same sealed commit and provide the successful verification
   run ID. The workflow checks exact source SHA, lock SHA-256, and model set in the prior
   offline report, downloads the models again, verifies the lock offline again, and only
   then starts the no-network Ollama server and real E-009 agent.
   ```bash
   gh workflow run m3-007-alternative-models.yml --repo mojtaba-arvin/agent-native --ref research/reboot-core -f phase=trial -f verification_run_id=<successful-verify-run-id>
   ```
5. Review all six cells (three models × progressive/upfront schema arm), raw traces,
   candidate hashes, resource use, and safety assertions. No selective retry or dropped
   failure is permitted.

The trial preserves the existing E-009 limits: 12,000 cumulative input tokens,
2,048 output tokens per request and total output budget, 20 tool calls, 600 seconds per
model, context 16,384, temperature 0, top-p 1, seed 42. Apply, hidden oracle, paid API,
and GPU remain disabled.

## Lock semantics

- Bootstrap observation is evidence, not a lock and not a qualification.
- The seal utility copies only observed manifest SHA-256, config digest, quantization,
  parameter size, model size, and layer digests into the candidate manifest and lock.
- Offline verification recomputes those values from a second fresh pull and fails closed
  on any difference.
- A verified lock proves artifact identity only. It does not prove model capability.
- A trial can qualify a candidate for further consideration only if the real E-009
  inspect → propose → validate → plan lifecycle completes with exact hash continuity,
  trusted-base preservation, and a valid no-mutation/no-deployment plan. Even that is
  public feasibility evidence, not protected M3 hidden-oracle acceptance.

## Recovery and immutability

Keep every bootstrap, verification, and trial artifact. If any digest, quantization,
runtime, or safety check fails, stop before inference and retain the failed artifact.
Do not overwrite the historical Granite lock or reuse its model runs. A failed cell is
not selectively rerun; diagnose the cause and preregister a new cohort revision if the
protocol itself must change.
