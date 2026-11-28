#!/usr/bin/env python3
"""Validate commit authors, committers, and co-author trailers for a GitHub PR."""
import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.request

NAME = "Mojtaba Arvin"
EMAIL = "m.arvin@live.com"
MARKER = "<!-- maintainer-directed-ai-work -->"
AUTO_LABEL = "allow-automation-commits"
AUTO_LOGINS = {"github-actions[bot]", "dependabot[bot]"}
BOT_MARKERS = (
    "[bot]", "ai agent", "ai-agent", "agent bot", "copilot", "claude",
    "cursor", "windsurf", "codex", "chatgpt", "gemini", "openai", "gpt",
    "ai assistant", "assistant bot", "anthropic", "devin", "swe-agent",
    "aider", "cline", "roo code", "deepseek", "qwen",
)


def is_bot(name, email, login=None, account_type=None):
    if (account_type or "").lower() == "bot":
        return True
    if login and login.lower().endswith("[bot]"):
        return True
    value = (name + " " + email + " " + (login or "")).lower()
    return any(marker in value for marker in BOT_MARKERS)


def approved_automation(item, allow_auto):
    """Require matching, allowlisted bot author and committer metadata."""
    author_account = item.get("author") or {}
    committer_account = item.get("committer") or {}
    commit = item.get("commit") or {}
    author = commit.get("author") or {}
    committer = commit.get("committer") or {}
    login = author_account.get("login")
    return (
        allow_auto
        and login in AUTO_LOGINS
        and author_account.get("type") == "Bot"
        and committer_account.get("login") == login
        and committer_account.get("type") == "Bot"
        and bool(author.get("name"))
        and bool(author.get("email"))
        and bool(committer.get("name"))
        and bool(committer.get("email"))
        and author.get("name") == committer.get("name")
        and author.get("email", "").lower() == committer.get("email", "").lower()
    )


def validate(pr, commits):
    errors = []
    labels = {x.get("name", "") for x in pr.get("labels", [])}
    allow_auto = AUTO_LABEL in labels
    maintainer_work = MARKER in (pr.get("body") or "")
    maintainer_commit_seen = False

    for item in commits:
        commit = item.get("commit") or {}
        author = commit.get("author") or {}
        committer = commit.get("committer") or {}
        author_account = item.get("author") or {}
        committer_account = item.get("committer") or {}
        name, email = author.get("name") or "", author.get("email") or ""
        login, account_type = author_account.get("login"), author_account.get("type")
        committer_login = committer_account.get("login")
        committer_type = committer_account.get("type")
        sha = (item.get("sha") or "unknown")[:12]

        if not name or not email:
            errors.append(sha + ": missing author name/email")
        if not committer.get("name") or not committer.get("email"):
            errors.append(sha + ": missing committer name/email")

        author_is_bot = is_bot(name, email, login, account_type)
        committer_is_bot = is_bot(
            committer.get("name") or "",
            committer.get("email") or "",
            committer_login,
            committer_type,
        )
        automation_allowed = approved_automation(item, allow_auto)
        if author_is_bot and not automation_allowed:
            errors.append(
                f"{sha}: bot/agent author rejected or automation provenance incomplete: "
                f"{name!r} <{email}> login={login!r}"
            )
        if committer_is_bot and not automation_allowed:
            errors.append(
                f"{sha}: bot/agent committer rejected or automation provenance incomplete: "
                f"{committer.get('name')!r} <{committer.get('email')}> "
                f"login={committer_login!r}"
            )

        if login and login.lower() == "mojtaba-arvin":
            maintainer_commit_seen = True
            if name != NAME or email.lower() != EMAIL.lower():
                errors.append(
                    f"{sha}: maintainer account must use {NAME} <{EMAIL}>, "
                    f"got {name!r} <{email}>"
                )
        elif email.lower() == EMAIL.lower():
            errors.append(
                f"{sha}: maintainer email must resolve to mojtaba-arvin, "
                f"not {login!r}"
            )

        for line in (commit.get("message") or "").splitlines():
            if re.match(r"^\s*Co-authored-by\s*:", line, re.IGNORECASE):
                identity = line.split(":", 1)[1].strip()
                if is_bot(identity, ""):
                    errors.append(
                        f"{sha}: bot/AI Co-authored-by trailer rejected: {identity!r}"
                    )

    if maintainer_work and not maintainer_commit_seen:
        errors.append(
            "maintainer-directed AI work marker requires at least one commit "
            "authored by mojtaba-arvin"
        )
    return errors


def get_json(url, token):
    req = urllib.request.Request(url, headers={
        "Accept": "application/vnd.github+json",
        "Authorization": "Bearer " + token,
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "commit-identity-policy-check"})
    with urllib.request.urlopen(req, timeout=30) as response:
        return json.loads(response.read().decode())


def self_test():
    def item(name, email, login, account_type, message="feat: test",
             committer_login=None, committer_type=None,
             committer_name=None, committer_email=None):
        return {
            "sha": "a" * 40,
            "commit": {
                "author": {"name": name, "email": email},
                "committer": {
                    "name": committer_name if committer_name is not None else name,
                    "email": committer_email if committer_email is not None else email,
                },
                "message": message,
            },
            "author": {"login": login, "type": account_type},
            "committer": {
                "login": committer_login if committer_login is not None else login,
                "type": committer_type if committer_type is not None else account_type,
            },
        }

    assert not validate(
        {"body": "", "labels": []},
        [item(NAME, EMAIL, "mojtaba-arvin", "User")],
    )
    assert not validate(
        {"body": "", "labels": []},
        [item("External Human", "x@example.org", "human", "User")],
    )
    assert not validate(
        {"body": "", "labels": []},
        [item("External Human", "x@example.org", "human", "User",
              committer_login="web-flow", committer_type="User",
              committer_name="GitHub", committer_email="noreply@github.com")],
    )
    assert validate(
        {"body": "", "labels": []},
        [item("Copilot", "bot@example.org", "copilot[bot]", "Bot")],
    )
    message = (
        "feat: test\n"
        "Co-authored-by: Copilot <copilot[bot]@users.noreply.github.com>"
    )
    assert validate(
        {"body": "", "labels": []},
        [item("Human", "h@example.org", "human", "User", message)],
    )
    assert not validate(
        {"body": MARKER, "labels": []},
        [item(NAME, EMAIL, "mojtaba-arvin", "User")],
    )
    assert not validate(
        {"body": MARKER, "labels": []},
        [
            item(NAME, EMAIL, "mojtaba-arvin", "User"),
            item("Other Human", "x@example.org", "human", "User"),
        ],
    )
    assert validate(
        {"body": MARKER, "labels": []},
        [item("Other Human", "x@example.org", "human", "User")],
    )
    assert validate(
        {"body": "", "labels": []},
        [item("Wrong Name", "wrong@example.org", "mojtaba-arvin", "User")],
    )
    assert validate(
        {"body": "", "labels": []},
        [item(NAME, EMAIL, None, "User")],
    )
    automation = item(
        "github-actions[bot]", "bot@users.noreply.github.com",
        "github-actions[bot]", "Bot",
    )
    assert validate({"body": "", "labels": []}, [automation])
    assert not validate(
        {"body": "", "labels": [{"name": AUTO_LABEL}]},
        [automation],
    )
    mismatched_committer = item(
        "github-actions[bot]", "bot@users.noreply.github.com",
        "github-actions[bot]", "Bot",
        committer_login="mojtaba-arvin", committer_type="User",
        committer_name=NAME, committer_email=EMAIL,
    )
    assert validate(
        {"body": "", "labels": [{"name": AUTO_LABEL}]},
        [mismatched_committer],
    )
    bot_committer = item(
        "Human", "human@example.org", "human", "User",
        committer_login="github-actions[bot]", committer_type="Bot",
        committer_name="github-actions[bot]",
        committer_email="bot@users.noreply.github.com",
    )
    assert validate({"body": "", "labels": []}, [bot_committer])
    print("PASS: commit identity policy self-tests")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--repository", default=os.getenv("GITHUB_REPOSITORY"))
    parser.add_argument("--pr-number", type=int, default=int(os.getenv("PR_NUMBER", "0")))
    parser.add_argument("--token", default=os.getenv("GITHUB_TOKEN"))
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
    if not (args.repository and args.pr_number and args.token):
        if args.self_test and not args.pr_number:
            return 0
        parser.error("--repository, --pr-number and --token are required")

    base = "https://api.github.com/repos/" + args.repository
    pr = get_json(base + "/pulls/" + str(args.pr_number), args.token)
    commits, page = [], 1
    while True:
        batch = get_json(
            base + f"/pulls/{args.pr_number}/commits?per_page=100&page={page}",
            args.token,
        )
        if not isinstance(batch, list):
            raise RuntimeError("GitHub API returned a non-list commit response")
        commits.extend(batch)
        if len(batch) < 100:
            break
        page += 1

    if not commits:
        print("ERROR: empty PR commit list; refusing to pass")
        return 2
    errors = validate(pr, commits)
    print(f"Checked {len(commits)} commits in {args.repository}#{args.pr_number}")
    if errors:
        print("\n".join("ERROR: " + error for error in errors))
        return 1
    print("PASS: no prohibited bot/agent authors, committers, or co-author trailers")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except urllib.error.HTTPError as error:
        print(f"ERROR: GitHub API HTTP {error.code}: {error.reason}", file=sys.stderr)
        sys.exit(2)
    except (urllib.error.URLError, TimeoutError, ValueError, RuntimeError) as error:
        print(f"ERROR: identity validation incomplete: {error}", file=sys.stderr)
        sys.exit(2)
