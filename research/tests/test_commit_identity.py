import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

from check_commit_identity import (
    AUTO_LABEL,
    EMAIL,
    MARKER,
    NAME,
    validate,
)


def commit(name, email, login, account_type, message="feat: fixture",
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


class CommitIdentityPolicyTests(unittest.TestCase):
    def test_owner_authorized_ai_work_uses_maintainer_identity(self):
        pr = {"body": MARKER, "labels": []}
        self.assertEqual(validate(pr, [commit(NAME, EMAIL, "mojtaba-arvin", "User")]), [])

    def test_external_human_contributor_identity_is_preserved(self):
        pr = {"body": "", "labels": []}
        self.assertEqual(
            validate(pr, [commit("External Contributor", "dev@example.org", "contributor", "User")]),
            [],
        )

    def test_web_flow_committer_is_distinct_from_human_author(self):
        pr = {"body": "", "labels": []}
        human = commit(
            "External Contributor", "dev@example.org", "contributor", "User",
            committer_login="web-flow", committer_type="User",
            committer_name="GitHub", committer_email="noreply@github.com",
        )
        self.assertEqual(validate(pr, [human]), [])

    def test_bot_author_is_rejected_without_automation_label(self):
        pr = {"body": "", "labels": []}
        errors = validate(
            pr,
            [commit("github-actions[bot]", "bot@users.noreply.github.com",
                    "github-actions[bot]", "Bot")],
        )
        self.assertTrue(any("bot/agent author rejected" in error for error in errors))

    def test_bot_coauthor_trailer_is_rejected(self):
        pr = {"body": "", "labels": []}
        message = (
            "feat: fixture\n\n"
            "Co-authored-by: Copilot <copilot[bot]@users.noreply.github.com>"
        )
        errors = validate(
            pr,
            [commit("Human", "human@example.org", "human", "User", message)],
        )
        self.assertTrue(any("Co-authored-by" in error for error in errors))

    def test_genuine_automation_requires_matching_bot_author_and_committer(self):
        pr = {"body": "", "labels": [{"name": AUTO_LABEL}]}
        for login in ("github-actions[bot]", "dependabot[bot]"):
            with self.subTest(login=login):
                automation = commit(
                    login, "automation@example.org", login, "Bot",
                )
                self.assertEqual(validate(pr, [automation]), [])

    def test_bot_coauthor_remains_rejected_on_automation_commit(self):
        pr = {"body": "", "labels": [{"name": AUTO_LABEL}]}
        automation = commit(
            "github-actions[bot]", "automation@example.org",
            "github-actions[bot]", "Bot",
            message=(
                "chore: generated version update\n"
                "Co-authored-by: Copilot <copilot[bot]@users.noreply.github.com>"
            ),
        )
        errors = validate(pr, [automation])
        self.assertTrue(any("Co-authored-by" in error for error in errors))

    def test_automation_label_alone_does_not_authorize_bot_commit(self):
        pr = {"body": "", "labels": [{"name": AUTO_LABEL}]}
        bot_with_human_committer = commit(
            "github-actions[bot]", "bot@users.noreply.github.com",
            "github-actions[bot]", "Bot",
            committer_login="mojtaba-arvin", committer_type="User",
            committer_name=NAME, committer_email=EMAIL,
        )
        errors = validate(pr, [bot_with_human_committer])
        self.assertTrue(any("automation provenance incomplete" in error for error in errors))

    def test_human_author_with_bot_committer_is_rejected(self):
        pr = {"body": "", "labels": []}
        commit_with_bot_committer = commit(
            "Human", "human@example.org", "human", "User",
            committer_login="github-actions[bot]", committer_type="Bot",
            committer_name="github-actions[bot]",
            committer_email="bot@users.noreply.github.com",
        )
        errors = validate(pr, [commit_with_bot_committer])
        self.assertTrue(any("bot/agent committer rejected" in error for error in errors))

    def test_external_human_is_preserved_in_maintainer_ai_pr(self):
        pr = {"body": MARKER, "labels": []}
        commits = [
            commit(NAME, EMAIL, "mojtaba-arvin", "User"),
            commit("Other Human", "other@example.org", "other-human", "User"),
        ]
        self.assertEqual(validate(pr, commits), [])

    def test_maintainer_marker_requires_maintainer_commit(self):
        pr = {"body": MARKER, "labels": []}
        errors = validate(
            pr,
            [commit("Other Human", "other@example.org", "other-human", "User")],
        )
        self.assertTrue(any("requires at least one commit" in error for error in errors))

    def test_maintainer_account_requires_exact_identity(self):
        pr = {"body": "", "labels": []}
        errors = validate(
            pr,
            [commit("Wrong Name", "wrong@example.org", "mojtaba-arvin", "User")],
        )
        self.assertTrue(any("maintainer account must use" in error for error in errors))

    def test_maintainer_email_must_resolve_to_maintainer_account(self):
        pr = {"body": "", "labels": []}
        errors = validate(
            pr,
            [commit(NAME, EMAIL, "different-account", "User")],
        )
        self.assertTrue(any("maintainer email must resolve" in error for error in errors))


if __name__ == "__main__":
    unittest.main()
