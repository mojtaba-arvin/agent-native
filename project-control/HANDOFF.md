# Execution handoff

## Resume protocol

1. Read AGENTS.md and this directory's README.md.
2. Run `python project_control.py validate`, `status`, `self-test`, and `resume`.
3. Run `python scripts/check_claims.py` and `python scripts/check_preregistrations.py`.
4. Inspect current branch, base, open PRs, diffs, and latest workflow runs.
5. Continue only active tasks whose dependencies are complete.
6. If blocked, record the blocker and continue independent work.
7. Record acceptance commands and recovery routes before implementation.
8. Run acceptance and regression checks before updating task/evidence state.
9. Do not merge to main, deploy, release, change security settings, or perform destructive actions without explicit owner authorization.

## Current checkpoint — 2026-11-19

- C0, C1, M0, M1, and C2 are complete and integrated into `research/reboot-core`.
- CP-009 dependency-aware scheduling/recovery is complete through PR #84.
- M2-001 ServiceRegistry, M2-002 generic declarative CRUD/list/job/event dispatch, M2-003 Service-independent Gateway, and M2-004 multi-service proof are integrated. M2 is complete on `research/reboot-core@0e8e8fe67f410add6d851584eeb7434f2f707aa8`.
- PR #81 passed Layer 0 and Layer 1 on head `0e53539ac8652a79bd831c4883ec9ff26ebf411c`; it was integrated under the repository owner's exact-head waiver. The waiver is not peer review. PR #82 passed Layer 0 and Layer 1 on head `1607feafeea17b3d7dfcd1e51f8a3ec5544731ec` and was integrated. The integrated merge commit also passed push CI run #44491048454.
- PR #90's owner-waiver CI path is historical and has been retired. Code integration now uses implementer self-review and exact-head evidence gates; C3 remains pending until its updated technical evidence criteria are met.
- PR #89 hardened E-007 evaluator filesystem-custody preflight: symlink and hard-link rejection, owner/mode checks, and no oracle path in the public evidence object. These checks are not OS/container/network isolation.
- M3 is now the current milestone. M3-000 topology smoke is complete. M3-001 remains blocked because no qualifying free/open-weight model cohort or protected hidden-oracle custody path has been demonstrated. The owner authorized zero paid spend, limited to GitHub Actions free usage for this public repository. No paid API/GPU call or hidden-oracle cohort has been run.
- The manual Qwen3 CPU workflow remains exploratory only and cannot satisfy M3 acceptance. The cohort remains draft and non-executable.
- BLK-001 (main branch protection/integration authority), BLK-004 (qualifying zero-cost model and protected hidden-oracle path), and BLK-007 (C3 peer review) remain open; BLK-007 does not block M3 preparation.
- No main merge, production deployment, paid provider call, paid GPU evaluation, or destructive branch operation has been performed as of this historical handoff entry.

## Next actions

1. M3-000 is complete. PR #93 integrated runtime probes; push CI run #44494715310 passed Layer 0/Layer 1, and post-merge topology run #44494715332 passed on `research/reboot-core@ec3975ff11f33516e0d98e349283cbf7b3f19789`. Both separate jobs reported UID 1001, read-only root, noexec /tmp, NoNewPrivs, zero CapEff, blocked outbound networking, 2 GiB memory, 1 CPU, and 64 PIDs. The agent artifact contained only candidate/trace; the evaluator artifact contained only score.json. The smoke used a deterministic stub and synthetic oracle only. The synthetic smoke verifies separate jobs and the configured container restrictions; it does not establish production-grade tenant isolation or actual hidden-oracle custody.
2. Investigate and pin a free-tier model cohort that can meet the preregistered quality requirements. Keep CPU-only Qwen3 diagnostics exploratory; if no free path is decision-grade, preserve the blocker rather than lowering acceptance.
3. Keep the M3 cohort non-executable until hidden-oracle custody, sandbox separation, model identity, task fixtures, and preregistration hashes are verified.
4. Do not seek or fabricate a second-human approval for ordinary code PRs. Complete C3 through documented self-review, source-level threat analysis, security regression coverage, exact-head CI, resolved threads, and merge-base freshness.
5. Do not deploy production or incur paid API/GPU spend without the applicable authorization.


## 19 November 2026 — M3 provider-schema integration

- PR #102 merged as `3ac47aeb0aa4c1ad8763396e5dffc956483a71e5`. The provider now receives each discovered Gateway tool as a native function with its exact schema. Progressive discovery starts with `interface.describe`; upfront mode exposes the complete declared schema set. Native calls still map through the trusted Gateway envelope; disabled apply is not exposed.
- Exact PR-head CI run [44538804299](https://github.com/mojtaba-arvin/agent-native/actions/runs/44538804299) passed Layer 0 (143 E-009 tests) and Layer 1 (Go, Rust, WASI P2, BEAM, PostgreSQL/cross-engine parity, and cgroup-v2 smoke).
- M3-003 is complete as a bounded negative feasibility evaluation: the pre-fix locked run [44529848174](https://github.com/mojtaba-arvin/agent-native/actions/runs/44529848174) had 0/6 full lifecycle completions; no Granite tier was qualified.
- M3-004 is complete. M3-005 is running as [workflow 44539287065](https://github.com/mojtaba-arvin/agent-native/actions/runs/44539287065), rerunning the unchanged six-cell CPU matrix on the provider-native schema adapter. Preserve all raw outcomes; do not qualify a model unless it completes inspect/propose/validate/plan and local verification.
- M3-001 remains blocked until a qualifying model and protected evaluator-only oracle custody are demonstrated. No paid API/GPU, apply, or hidden oracle is used.
- Storage note: the repository already has a PostgreSQL 16.4 reference adapter and conformance tests; cross-engine trace, rollback, and crash-reconciliation evidence exists. Oracle Database is not a current E-002 candidate and has no demonstrated requirement. Keep PostgreSQL as the primary storage candidate; final product selection remains evidence-gated against the product workload.


## Alternative CPU model research — 19 November 2026

M3-006 is complete. If the active M3-005 Granite 4.0 rerun remains negative, a separate candidate pool is ready for M3-007: `qwen3:1.7b` (1.4 GB), `granite4.2:3b` (2.2 GB), and `qwen3:4b` (2.5 GB), with `gemma4:e2b` (4.6–7.5 GB) held as a higher-memory reserve. Official Ollama library metadata advertises tool support for Qwen3 and agentic/tool use for Gemma 4; Granite 4.2 explicitly lists function-calling tasks and Apache 2.0. The size labels are not performance rankings. No tags have been pulled, locked, preregistered, or executed in this research task. See `research/M3_ALTERNATIVE_MODEL_SHORTLIST.md`.


## M3 workflow trigger optimization — 19 November 2026

CP-011 is complete. The expensive six-cell M3 workflow no longer triggers on edits to its own workflow YAML or the M3 report; executable harness, candidate, and sandbox inputs remain triggers, and `workflow_dispatch` remains available. The workflow-definition update commit `280b32e3` produced ordinary CI run [44541307333](https://github.com/mojtaba-arvin/agent-native/actions/runs/44541307333) without starting another M3 model run.

One unplanned duplicate, [44541147095](https://github.com/mojtaba-arvin/agent-native/actions/runs/44541147095), had already started from the preceding report-only update before the filter was narrowed. Preserve it as an unplanned repeatability observation, not as part of the preregistered M3-005 cohort. Keep it separate from primary run [44539287065](https://github.com/mojtaba-arvin/agent-native/actions/runs/44539287065); do not pool their results.


## M3-005 result and next harness fix — 19 November 2026

M3-005 is complete as a bounded negative feasibility rerun. Primary run [44539287065](https://github.com/mojtaba-arvin/agent-native/actions/runs/44539287065), artifact #14538178152 (SHA-256 `94d2d6d3ddee3f5a11467601bacbbe5619a7dda95f603f9022846718c2f6c8d4`), produced 0/6 full lifecycle completions. Provider telemetry proves native tool definitions were exposed correctly. Progressive 1B/3B repeated `interface.describe`; upfront 3B reached successful validation but exceeded the fixed 12,000-token budget before planning. No model qualifies.

M3-008 is active: add runner-side duplicate discovery/inspection handling and deduplicate compacted outcomes without changing budgets or the model lock. M3-007 (alternate model cohort) is deferred until M3-008 completes. The separate unplanned docs-triggered run #44541147095 is retained but not pooled.
