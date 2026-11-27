import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from check_commit_identity import (
    AUTO_LABEL,
    EMAIL,
    MARKER,
    NAME,
    validate,
)


def commit(name, email, login, account_type, message="feat: fixture"):
    return {
        "sha": "a" * 40,
        "commit": {
            "author": {"name": name, "email": email},
            "message": message,
        },
        "author": {"login": login, "type": account_type},
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

    def test_bot_author_is_rejected(self):
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

    def test_approved_genuine_automation_requires_explicit_label(self):
        pr = {"body": "", "labels": [{"name": AUTO_LABEL}]}
        self.assertEqual(
            validate(
                pr,
                [commit("github-actions[bot]", "bot@users.noreply.github.com",
                        "github-actions[bot]", "Bot")],
            ),
            [],
        )

    def test_maintainer_marker_rejects_other_human_identity(self):
        pr = {"body": MARKER, "labels": []}
        errors = validate(
            pr,
            [commit("Other Human", "other@example.org", "other-human", "User")],
        )
        self.assertTrue(any("expected Mojtaba Arvin" in error for error in errors))


if __name__ == "__main__":
    unittest.main()
