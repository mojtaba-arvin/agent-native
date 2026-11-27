# Commit identity and attribution: evidence and decision

## Research question

How can maintainer-directed AI-assisted implementation use a stable human maintainer identity without misattributing genuine human contributors or disguising independent automation?

## Observed repository evidence

The portfolio scan found concrete bot attribution in two repositories:
- `ai-service-marketplace` contains a workflow that configures Git as `github-actions[bot]`; a historical commit also contains a GitHub Actions `Co-authored-by` trailer.
- `health-monitoring-helmet` has historical commits with GitHub Actions as a co-author while the primary author remains the maintainer.
- The sampled latest commits in the remaining repositories were associated with the maintainer's GitHub account. This is not a full historical audit.

## Technical findings

1. A Git commit stores separate author and committer identities. The author is contribution attribution; the committer records who created the Git object. Repository history contains a maintainer-associated author with `web-flow` as committer; the identities are distinct and must not be conflated.
2. Git author name and email are configurable metadata. Global/local Git configuration is a convenience, not an enforcement mechanism, and environment variables or API-created commits can override it.
3. GitHub associates commits with accounts using email identity. The configured maintainer email must be verified/associated with the maintainer's GitHub account before relying on profile attribution.
4. A commit signature proves possession/use of a signing key; it does not prove that a human physically wrote the code.
5. PR validation can inspect commit metadata and co-author trailers. It can reject known bot/agent identities, require at least one maintainer-authored commit in explicitly marked AI-assisted PRs, validate every commit attributed to the maintainer, and preserve other human contributors.
6. A failing CI check is only a hard merge gate when repository rules require it. A workflow alone does not enforce branch protection.

## Decision

- Owner-authorized AI-assisted implementation commits use `Mojtaba Arvin <m.arvin@live.com>`, conditional on that email being verified on the GitHub account.
- PRs containing this work carry `<!-- maintainer-directed-ai-work -->`; the validator requires at least one commit authored by `mojtaba-arvin` and validates every commit attributed to that account against the exact maintainer name/email. Other human contributor commits remain attributed to their real authors.
- Preserve all external human contributor authorship. Never amend or rewrite another person's commits as the maintainer; add separate maintainer-authored commits for AI-assisted changes.
- Reject known AI/agent/bot authors and bot `Co-authored-by` trailers on ordinary implementation PRs.
- Candidate automation exceptions are limited to `github-actions[bot]` and `dependabot[bot]`. The validator requires an explicit `allow-automation-commits` label, the same allowlisted GitHub Bot account as both commit author and committer, and matching non-empty Git author/committer names and emails. Human-author/bot-committer and bot-author/human-committer combinations fail. Bot co-author trailers remain prohibited. The label and commit metadata are not proof that a workflow actually generated the commit or who applied the label; this remains a documented manual provenance boundary, and the exception must be used only after independently confirming the originating automation.
- Disclose AI assistance in the PR body. The human commit identity represents maintainer ownership/responsibility, not a claim that the maintainer personally typed each line.
- Do not rewrite historical commits. Apply the policy prospectively.

## Validation design

`scripts/check_commit_identity.py` checks the complete PR commit list from the GitHub API, including paginated results. Its fixture tests cover maintainer identity, an external human contributor sharing a marked PR, a marker without a maintainer commit, mismatched maintainer metadata, prohibited bot authors, prohibited bot co-author trailers, and the explicit automation exception. The PR workflow uses read-only contents/pull-request permissions, no secrets, and no write access; it checks out the PR head.

## Limitations and residual risks

Commit metadata is self-asserted. A malicious or careless agent can choose a human-looking name/email, and no Git metadata check can prove who physically authored the code. The policy therefore combines verified account email, a PR marker, metadata validation, transparent AI disclosure, and required branch-protection checks. Human-looking metadata must not be used to overwrite a real contributor's identity.

## Primary references

- GitHub: [Setting your commit email address](https://docs.github.com/en/account-and-profile/how-tos/email-preferences/setting-your-commit-email-address)
- GitHub: [About commit signature verification](https://docs.github.com/en/authentication/managing-commit-signature-verification/about-commit-signature-verification)
- GitHub: [About rulesets](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-rulesets/about-rulesets)


## Repository workflow observations (2026-11-28)

- The authenticated GitHub account is `mojtaba-arvin` (account ID 6056661), matching the repository owner and PR author.
- The current PR head's GitHub-associated author and committer are both `mojtaba-arvin`; its Commit identity workflow passed against that head. The validator's API-side check also requires the exact configured author name/email for this account.
- A sampled historical repository commit (fb4f163e397cbb8bd01bdd620cd539901e16fca7) resolves to author `mojtaba-arvin` and committer `web-flow`. This is a real workflow distinction, not evidence that the author is a bot.
- Searches for commit messages containing `Co-authored-by` and `dependabot` returned no matches in the sampled history; this is not a complete historical audit. A `github-actions` message search returned a commit whose author resolved to `mojtaba-arvin`, not an automation author.
- No sampled commit establishes a genuine `github-actions[bot]` or `dependabot[bot]` author exception. The allowlist is therefore prospective and narrowly constrained; its label is not a provenance attestation.

These observations are limited to the queried history and current PR. They do not prove the full historical absence of bot attribution or authenticate the private verified-email settings.
