# Commit identity and attribution policy

For maintainer-directed AI-assisted implementation, use Git author `Mojtaba Arvin <m.arvin@live.com>` only after confirming this exact email is verified and associated with the maintainer's GitHub account. Do not use model, assistant, AI-agent, Copilot, Claude, Cursor, Codex, Gemini, generic agent, or bot identities as the author. Do not add bot/AI `Co-authored-by` trailers.

Include `<!-- maintainer-directed-ai-work -->` in the PR body for owner-authorized AI-assisted work. This machine-readable marker requires at least one commit whose GitHub-associated author is `mojtaba-arvin` and validates every commit attributed to that account against the exact maintainer name/email; other human contributor identities remain unchanged. Disclose AI assistance in the PR description; the marker does not claim the maintainer personally typed every line.

Preserve every real human contributor's original author name/email. Never relabel another person as the maintainer and never rewrite historical commits.

## Commit author, committer, and automation

Git commit author and committer are separate fields. The author is contribution attribution; the committer records who created the commit object. GitHub's `web-flow` committer is not the author and is not, by itself, a bot-author violation. The repository history includes a maintainer-authored commit with `web-flow` as its committer; this is observed repository evidence, not a reason to rewrite its attribution.

The only candidate bot automation identities are `github-actions[bot]` and `dependabot[bot]`. A bot-authored or bot-committed PR commit is rejected unless the PR has the explicit `allow-automation-commits` label and GitHub's commit API identifies the same allowlisted bot login and account type `Bot` as both author and committer, with matching non-empty Git author/committer names and emails. A human author with a bot committer, a bot author with a human committer, mismatched identities, any other bot account, and bot/AI co-author trailers are rejected.

The label is an explicit per-PR approval signal, not proof of execution provenance. Git metadata and labels alone cannot prove that a workflow generated a commit or who applied the label. Apply the exception only after independently confirming the exact commit came from the corresponding GitHub Actions workflow or Dependabot operation. Do not use the exception for agent-written implementation. If stronger machine-verifiable provenance is required, add a workflow-specific trusted attestation before expanding this allowlist.

## Local convenience and enforcement

Convenience defaults (not enforcement):

```sh
git config --global user.name "Mojtaba Arvin"
git config --global user.email "m.arvin@live.com"
```

`scripts/check_commit_identity.py` checks all paginated PR commits, distinguishes author from committer, rejects known bot/agent authors and committers, rejects bot co-author trailers, permits only the narrowly matched automation case above, and enforces the maintainer identity when the marker is present. The `Commit identity` workflow uses a standard `pull_request` event with read-only contents/pull-request permissions, a concurrency guard, no repository secrets, and no write access. It checks out the exact PR head and validates commit metadata. The research acceptance workflow also runs the test suite. Current enforcement boundary (observed 2026-11-28): the active `Protect research/reboot-core` ruleset requires GitHub Actions checks `gate` and `acceptance`, requires resolved review threads, and requires zero approvals. It does not require the `Commit identity` check. The connected GitHub integration permits ruleset reads but not administration writes, so this change does not modify the ruleset. Consequently, `Commit identity` runs on PRs and reports failures but is not currently a hard merge gate; do not claim otherwise. Making it required needs an authorized repository-administration change.

Git metadata is self-asserted: validation cannot prove who physically typed code or detect every disguised agent identity. The policy therefore combines verified account email, GitHub's author association, explicit AI disclosure, metadata validation, and repository branch/review protections. The validator cannot independently read private verified-email settings or authenticate who applied a label.

Never amend, rebase, or cherry-pick a contributor's work under the maintainer identity. Preserve the contributor's original author fields and add a separate maintainer-authored commit for AI-assisted changes.
