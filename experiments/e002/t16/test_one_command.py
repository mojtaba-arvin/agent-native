import unittest
from pathlib import Path
from one_command_common import validate_lock


class OneCommandTests(unittest.TestCase):
    def valid_lock(self):
        digest = "sha256:" + "b" * 64
        name = "ghcr.io/mojtaba-arvin/agent-native-t16"
        return {"source_sha": "a" * 40, "image_name": name, "image_digest": digest,
                "image_ref": name + "@" + digest, "image_tag": "a" * 40,
                "dockerfile_path": "experiments/e002/t16/Dockerfile"}

    def test_accepts_exact_digest_and_source(self):
        self.assertEqual(validate_lock(self.valid_lock(), "a" * 40)["source_sha"], "a" * 40)

    def test_rejects_mutable_reference(self):
        lock = self.valid_lock()
        lock["image_ref"] = lock["image_name"] + ":latest"
        with self.assertRaises(RuntimeError):
            validate_lock(lock, "a" * 40)

    def test_rejects_wrong_source_sha(self):
        with self.assertRaises(RuntimeError):
            validate_lock(self.valid_lock(), "c" * 40)

    def test_rejects_unexpected_package(self):
        lock = self.valid_lock()
        lock["image_name"] = "ghcr.io/somewhere/else"
        with self.assertRaises(RuntimeError):
            validate_lock(lock, "a" * 40)

    def test_controller_shares_tmp_with_host_docker_daemon(self):
        source = Path(__file__).with_name("one-command.py").read_text()
        self.assertIn('"--volume", "/tmp:/tmp"', source)
        self.assertIn("bind-mount sources", source)


if __name__ == "__main__":
    unittest.main()
