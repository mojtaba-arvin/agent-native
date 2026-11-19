# Branch and unique-artifact inventory

**Inventory date:** 2026-11-19  
**Comparison base:** research/reboot-core@23f9c77d8ce9a8d55895c6c4903a4ff409ba5781  
**Method:** GitHub branch enumeration plus commit-graph comparisons against the comparison base. Ahead/behind values below are relative to research/reboot-core. No branch or tag was deleted, rewritten, or force-pushed.

## Current refs

The current branch enumeration returned 27 refs. The earlier inventory's nine snapshot-named refs are not present in this enumeration: no current branch name contains `snapshot` or `archive`. This is a state observation, not an assertion about who deleted them or when.

| Branch | Tip SHA | Relation to research/reboot-core | Classification |
|---|---|---:|---|
| `research/reboot-core` | `23f9c77d8ce9a8d55895c6c4903a4ff409ba5781` | baseline | Active v0.1 source of truth |
| `main` | `da3736c7ea4d239d1ea520d8b56025b4e3251b33` | 0 ahead / 969 behind | Stale visitor branch; do not merge into it |
| `research/ci-policy-staging` | `982c675c5d8e6b49e837c14d88b3a6cbb3d24fd8` | 179 ahead / 37 behind | Diverged staging candidate; do not merge wholesale |
| `ci/m2-fast-pipeline` | `5ee970076d320ae81a54c15ffa301401a1eed765` | 187 ahead / 37 behind | PR #63 staging candidate; selected CI work was ported separately to PR #65 |
| `docs/paper-evidence-skeleton` | `900a802c0ae082eee5e1dd23b463ed741624446f` | 113 ahead / 221 behind | Preserve unique paper/evidence and diagnostics artifacts |
| `feature/e007-compaction-opt-in` | `2db6f4230d6cce7f6f0b519663610708bfbebfd4` | 107 ahead / 221 behind | Preserve E-007 compaction/evaluator changes |
| `fix/e007-absolute-request-deadline` | `f7e919872587aa2970af0281e62284803b0d9a5b` | 107 ahead / 221 behind | Preserve deadline/evaluator branch history; shares evaluator blob with compaction branch |
| `research/e007-post-proposal-failure-analysis` | `38177736906d2801a0bb988faf6c987cb1f6a77f` | 115 ahead / 221 behind | Preserve failure analysis, paper notes, and first-Light runner |
| `fix/e010-apply-contract-binding` | `74d2d8c3513253f77cddd2eff23c5a15cf5547a8` | 5 ahead / 186 behind | Diverged; preserve apply-contract changes |
| `fix/agent-inspection-progression` | `cdaec4443c0977ce95cdf6fca39fea6c416a5570` | 8 ahead / 185 behind | Diverged; preserve Gateway/local-agent progression changes |
| `fix/provider-absolute-deadline` | `e0336e7d91b6d5bd7d338f7356e3fa663c3e6621` | 2 ahead / 220 behind | Diverged; preserve provider deadline changes |
| `integration/e009-prevalidation` | `9cab3e5b7609a01b864537f0da15334761b14b1e` | 1 ahead / 221 behind | Diverged; preserve prevalidation changes |
| `chore/e007-second-light-preflight` | `7b6dcca1599a866c79b03a6f6ff27c2f121a3853` | 1 ahead / 220 behind | Diverged; preserve second-Light preflight runner |
| `chore/refresh-real-agent-pins-after-squash` | `4180894efa2d651a8a10f0b8da86c3b96da636c1` | 4 ahead / 184 behind | Diverged; preserve refreshed real-agent pins/dispatch changes |
| `decision/e002-agent-control-plane` | `6ee9496c6114569163201d72991cb8ac06315483` | 1 ahead / 220 behind | Diverged; preserve E-002 decision records |
| `docs/commit-history-review-self-corrections` | `f5ff0bfb25c4532e3cf5a06cbd7b0bfb255a63dd` | 1 ahead / 169 behind | Diverged; preserve commit-history review corrections |
| `fix/e007-hard-deadline-reboot-core` | `f08d970c3dc8025e570eecb3d744fdec8f2d7565` | 1 ahead / 216 behind | Diverged; sampled diagnostics/test blobs match the base; full unique commit still needs diff review |
| `feat/e010-isolated-sandbox-apply` | `021460587ab17c69cfcaa874c8a5c575e3adae1e` | 0 ahead / 196 behind | Fully reachable from base |
| `feat/e010-real-agent-runner` | `36ba08c49447ee55ace87823a6f9658d2eb7876d` | 0 ahead / 192 behind | Fully reachable from base |
| `fix/bounded-inspection-repeat` | `a69b7874c7a2880b0164b7e57aa265e0fcc1582c` | 0 ahead / 173 behind | Fully reachable from base |
| `fix/e007-operation-catalog-guard-second-light` | `62819125ce941d32145cc1cb86869dda10dc3f52` | 0 ahead / 211 behind | Fully reachable from base |
| `fix/e009-prompt-state-and-operation-guard` | `789edba33fae037ddb96fc0e00d5d83adaa7155b` | 0 ahead / 203 behind | Fully reachable from base |
| `feat/project-control-plane` | `56237edb1d8ce5b0c7e1d47eace0bebd224d3402` | 61 ahead / 0 behind | PR #64 head; stacked on reboot-core |
| `ci/unified-workflow` | `840f56cd3b663baa1063f36d2f0354fa4208ead8` | 116 ahead / 0 behind | PR #65 head; stacked on PR #64 |
| `feat/evidence-claims-gates` | `0f2bf986e407270db43f5df7fe60f2151eedd27d` | 119 ahead / 0 behind | Closed/superseded PR #66 branch; preserve, do not merge |
| `feat/evidence-claims-gates-v2` | `a143f31db94fe09572e885a549e770e5795c1150` | 120 ahead / 0 behind | Closed/superseded PR #67 branch; preserve, do not merge |
| `feat/evidence-claims-gates-v3` | `eec74b44322868bf4b99675387be76dbf4d431d9` | 161 ahead / 0 behind | PR #68 head; stacked on PR #65 |

## Verified unique artifacts

The following blob SHAs were fetched directly from their named branch refs. They are content identifiers, not branch-tip SHAs.

| Branch | Artifact | Blob SHA | Preservation note |
|---|---|---|---|
| `docs/paper-evidence-skeleton` | `paper-notes.md` | `da83eecaf66dcf5f6fe5951e1af3017d458d4e73` | Not present on reboot-core |
| `docs/paper-evidence-skeleton` | `experiments/e007/ollama_diagnostics.py` | `55c87efac290fd02dc59d7a703f6744eb9f02c75` | Newer diagnostics implementation than base blob `437bb81f...` |
| `docs/paper-evidence-skeleton` | `experiments/e007/results/2026-11-18-prefill-cache-thread-benchmark-plan.md` | `83f86ced2e24d35656ad9d2ad10b9599d10f39c4` | Not present on reboot-core |
| `feature/e007-compaction-opt-in` | `experiments/e007/eval_runner.py` | `14327ed033ebb03922d7096899718d79a808ac4b` | Differs from base `baee8c31...`; same blob also appears on absolute-deadline branch |
| `research/e007-post-proposal-failure-analysis` | `paper-notes.md` | `a3a30eac779e856580284da51673ce400f3426b0` | Distinct from docs/paper-evidence-skeleton notes |
| `research/e007-post-proposal-failure-analysis` | `experiments/e007/run_first_light.sh` | `cb283e903152adf39dbdf659687b7f5d0f488b19` | Not present on reboot-core |
| `chore/e007-second-light-preflight` | `experiments/e007/run_second_light.sh` | `e7b2977f6c4329db44c1b6c4d29df2c89f98ba0f` | Separate preflight runner |
| `chore/refresh-real-agent-pins-after-squash` | `experiments/e007/run_second_light.sh` | `dde844456d4e481a47084b6e649ad61ad623ebf9` | Different blob from second-Light preflight branch |
| `decision/e002-agent-control-plane` | `experiments/e002/decision-record.md` | `3f7680d248332a640ef81d7396595a681fa1c748` | E-002 decision record |
| `docs/commit-history-review-self-corrections` | `research/commit-history-review-2026-11-18.md` | `8fd6df5fbe89ac6fe147130bf72935995e493687` | Historical commit-review corrections |
| `fix/e010-apply-contract-binding` | `experiments/e010/demo_apply.py` | `09af0d2d1969410029ec9b45351cdc9e9c584c5c` | E-010 apply contract binding |
| `fix/agent-inspection-progression` | `experiments/e009/agent_gateway.py` | `7bd2975ab800787ba992dabaa27de3a3bc8e435f` | Gateway inspection progression |
| `fix/provider-absolute-deadline` | `experiments/e009/local_agent.py` | `ea50b27081d6ad1b887e344144aa7753c7c2657f` | Provider deadline behavior |
| `integration/e009-prevalidation` | `experiments/e009/local_agent.py` | `ab043e5746f16137d205312119645a19aca2d097` | Prevalidation behavior |

## Decisions

1. Preserve all diverged branches above until their unique commits and artifacts have been reviewed and, where appropriate, ported to a reviewable branch. Do not merge any branch wholesale based only on ahead/behind counts.
2. The four research branches sharing merge base `526b07697e591339bf991f73d00ab85da751be0e` are materially diverged from the current base (221 commits behind). Preserve their unique artifacts; port only reviewed changes.
3. `research/ci-policy-staging` and `ci/m2-fast-pipeline` share merge base `aba2a54f05e9e3cace7c004b2b4e520b243cd0fe`. PR #65 is the selected port of the unified workflow; do not merge the staging history wholesale.
4. Five branches are fully reachable from `research/reboot-core` (zero commits ahead). They are candidates for eventual cleanup, but no deletion is authorized or performed.
5. PR #66 and #67 are closed superseded drafts. Their refs remain intact; no deletion or rewrite.
6. The current enumeration does not contain snapshot-named refs. Reconcile this with the older nine-snapshot inventory before any cleanup; do not infer deletion history.
7. `main` is 969 commits behind the active base. Keep it untouched until a separate visitor-facing redirect/snapshot decision is reviewed.

## Verification limits

- Ahead/behind and merge-base values are GitHub compare results against the exact `research/reboot-core` ref at inventory time.
- The file SHAs above identify sampled unique content. They do not replace a full per-branch diff review.
- No branch deletion, tag deletion, force push, history rewrite, or merge was performed.
