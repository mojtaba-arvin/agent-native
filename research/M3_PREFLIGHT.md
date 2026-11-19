# M3 research execution preflight

**Status:** preparation only; no model cohort dispatched.  
**Baseline:** `research/reboot-core@0e8e8fe67f410add6d851584eeb7434f2f707aa8`  
**Purpose:** remove repository-side uncertainty while staying within the owner's zero-paid-spend ceiling (GitHub Actions free usage only).

## Current verified state

| Area | Observed state | M3 consequence |
|---|---|---|
| Existing E-007 pilot | `dispatch.json` is preregistered as `ready_for_manual_dispatch`, `no_apply=true`; Qwen3 8B, one repetition, four matched A–D cells | Feasibility pilot only; not a three-tier evaluation |
| Task coverage | The frozen pilot still uses one task (`e009-add-readonly-operation`); PR #74 adds three public draft tasks for operation addition, backward-compatible field addition, and tenant isolation | Public task prompts now exist; hidden evaluator oracles, pinned baseline fixtures, and independent scoring contracts remain outstanding |
| Model coverage | One local model ID, `qwen3:8b` | Strong/medium/weak tiers and immutable provider/model versions remain unselected |
| Cost telemetry | Case manifests use `unpriced_local`; monetary prices and cost ceilings are null | Cannot produce decision-grade cost-per-accepted-task comparisons |
| Agent/oracle separation | PR #89 hardens preflight: rejects symlinks/hard links, verifies oracle file/parent ownership and owner-only permissions, and removes the oracle path from public evidence objects | These checks are defense-in-depth only; disposable agent and evaluator process/filesystem/network sandboxes are still not implemented |
| Execution route | `.github/workflows/ci.yml` has manual CPU diagnostics explicitly labeled not M3 acceptance; `e007-provider-diagnostic.yml` is a one-cell Qwen3 diagnostic | Neither is the M3 acceptance runner |
| Dispatch guard | The factorial runner pins the revision, validates the four-cell manifest before provisioning, enforces no-apply, and is restricted to `research/reboot-core` | Preserve this boundary; do not dispatch from a feature branch |

## Work required before M3 can be called decision-grade

1. **Task corpus:** three public task prompts are now drafted under `experiments/e007/tasks/` and recorded in the unregistered `experiments/e007/m3-cohort-draft.json`. Still required: immutable baseline fixtures, hidden evaluator oracles stored outside the agent workspace, candidate contracts, explicit failure classes, and stable task/candidate identities.
2. **Cohort design:** preregister strong, medium, and weak model tiers; exact provider/model version or immutable model digest; sampling parameters; repetitions; randomized order; per-run and cohort-level token/tool/time ceilings; abort rules; and exclusion rules. Keep each model tier separately scored.
3. **Cost accounting:** pin input/output tariffs or declare the run self-hosted with measured hardware/energy cost. Unknown prices must remain unknown, never zero. Establish per-run and total spend ceilings before credentials are used.
4. **Isolation:** implement a disposable agent execution boundary with CPU, memory, process, disk, and wall-clock limits; deny network by default; export only the candidate and raw telemetry; destroy the agent environment; then evaluate the candidate read-only in a separate sandbox with oracle access. A subprocess or separate directory is not sufficient.
5. **Evidence integrity:** pin source revision, task/case manifests, model identity, runtime image/tool versions, oracle revision, and all artifact hashes. Proposal, validation, and safe plan must carry the exact same candidate hash. Preserve failures, timeouts, infrastructure-invalid trials, and missing telemetry.
6. **Runner:** create a dedicated manual-only M3 workflow that validates all frozen manifests and approval inputs before provisioning. It must not be reachable from ordinary PR, push, or scheduled CI events.
7. **Acceptance:** run deterministic validators and isolation negative tests before any model request; then independently inspect the complete raw artifact. A green workflow alone is not acceptance.

## Remaining protected setup

- The repository owner has authorized a zero-paid-spend ceiling, limited to GitHub Actions free usage for this public repository. Paid API/GPU workloads are not authorized.
- A protected GitHub Environment and evaluator-only oracle custody are still required. The current GitHub integration cannot create or write protected Environment secrets, so this administrative setup remains unavailable through the current connection.
- Prefer a qualifying open-weight/free-tier model path. Do not treat the existing CPU-only Qwen3 diagnostic as M3 acceptance.

## Safety and dispatch decision

No paid API/GPU workload has been started. No oracle cohort has been executed. The existing Qwen3 pilot remains frozen and unchanged; do not reinterpret it as M3 acceptance. M3-001 remains blocked until a qualifying zero-cost isolated runner/evaluator path and the three-task, three-tier cohort are implemented and verified.

## Immediate next engineering steps

- Build isolated baseline fixtures and hidden evaluator contracts for the three public task drafts without exposing assertions or oracle data to agent workspaces.
- Build and test the sandbox/evaluator separation before connecting any model provider.
- Implement the manual-only M3 dispatch workflow and validate its fail-closed approval/budget gate.
- Do not request or incur paid spend; only proceed with a no-cost path that meets the same isolation and evidence standards.
