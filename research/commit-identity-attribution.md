# Commit identity and attribution: evidence and decision

## Research question

How can maintainer-directed AI-assisted implementation use a stable human maintainer identity without misattributing genuine human contributors or disguising independent automation?

## Observed repository evidence

The portfolio scan found concrete bot attribution in two repositories:
- `ai-service-marketplace` contains a workflow that configures Git as `github-actions[bot]`; a historical commit also contains a GitHub Actions `Co-authored-by` trailer.
- `health-monitoring-helmet` has historical commits with GitHub Actions as a co-author while the primary author remains the maintainer.
- The sampled latest commits in the remaining repositories were associated with the maintainer's GitHub account. This is not a full historical audit.

## Technical findings

1. A Git commit stores separate author and committer identities. The author is contribution attribution; the committer records who created the Git object. GitHub Web Flow can therefore appear as committer without being the author.
2. Git author name and email are configurable metadata. Global/local Git configuration is a convenience, not an enforcement mechanism, and environment variables or API-created commits can override it.
3. GitHub associates commits with accounts using email identity. The configured maintainer email must be verified/associated with the maintainer's GitHub account before relying on profile attribution.
4. A commit signature proves possession/use of a signing key; it does not prove that a human physically wrote the code.
5. PR validation can inspect commit metadata and co-author trailers. It can reject known bot/agent identities, preserve other human identities, and require the maintainer identity for explicitly marked owner-authorized AI-assisted PRs.
6. A failing CI check is only a hard merge gate when repository rules require it. A workflow alone does not enforce branch protection.

## Decision

- Owner-authorized AI-assisted implementation commits use `Mojtaba Arvin <m.arvin@live.com>`, conditional on that email being verified on the GitHub account.
- PRs containing this work carry `<!-- maintainer-directed-ai-work -->`; the validator requires every commit author in those PRs to match the maintainer identity.
- Preserve all external human contributor authorship. Never rewrite another person's commits as the maintainer.
- Reject known AI/agent/bot authors and bot `Co-authored-by` trailers on ordinary implementation PRs.
- Genuine GitHub Actions/Dependabot commits may use their own bot identity only when explicitly approved with `allow-automation-commits`; never disguise automation as a human.
- Disclose AI assistance in the PR body. The human commit identity represents maintainer ownership/responsibility, not a claim that the maintainer personally typed each line.
- Do not rewrite historical commits. Apply the policy prospectively.

## Validation design

`scripts/check_commit_identity.py` checks the complete PR commit list from the GitHub API, including paginated results. Its fixture tests cover maintainer identity, an external human contributor, prohibited bot authors, prohibited bot co-author trailers, the explicit automation exception, and maintainer-marker enforcement. The PR workflow uses read-only permissions and trusted base-branch code.

## Limitations and residual risks

Commit metadata is self-asserted. A malicious or careless agent can choose a human-looking name/email, and no Git metadata check can prove who physically authored the code. The policy therefore combines verified account email, a PR marker, metadata validation, transparent AI disclosure, and required branch-protection checks. Human-looking metadata must not be used to overwrite a real contributor's identity.

## Primary references

- GitHub: [Setting your commit email address](https://docs.github.com/en/account-and-profile/how-tos/email-preferences/setting-your-commit-email-address)
- GitHub: [About commit signature verification](https://docs.github.com/en/authentication/managing-commit-signature-verification/about-commit-signature-verification)
- GitHub: [About rulesets](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-rulesets/about-rulesets)
