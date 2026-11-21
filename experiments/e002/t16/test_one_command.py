import unittest
from pathlib import Path


class OneCommandTests(unittest.TestCase):
    def test_launcher_uses_one_cached_image_without_installing_host_tools(self):
        source = Path(__file__).with_name("one-command.sh").read_text()
        self.assertIn('docker pull "$IMAGE:t16"', source)
        self.assertNotIn("apk add", source)
        self.assertNotIn("docker:27.5.1-cli", source)
        self.assertIn("RepoDigests", source)
        self.assertIn("T16_IMAGE_REF", source)
        self.assertIn("${GH_TOKEN:", source)

    def test_evidence_is_a_release_asset_not_a_git_branch(self):
        source = Path(__file__).with_name("one-command-runner.py").read_text()
        self.assertIn('"/repos/%s/releases"', source)
        self.assertIn("upload_url", source)
        self.assertIn("tarfile.open", source)
        self.assertNotIn('git", "-C", str(staging), "push"', source)

    def test_postgres_reuses_the_same_digest_pinned_image(self):
        source = Path(__file__).with_name("one-command-runner.py").read_text()
        self.assertIn("pg_image = IMAGE_REF", source)
        self.assertIn('"--entrypoint", "/usr/local/bin/docker-entrypoint.sh"', source)


if __name__ == "__main__":
    unittest.main()
