import importlib.util
import io
import json
import os
import tarfile
import tempfile
import unittest
from pathlib import Path
from unittest import mock

os.environ.setdefault("GH_TOKEN", "unit-test-token")
os.environ.setdefault("T16_SOURCE_SHA", "a" * 40)
os.environ.setdefault("T16_IMAGE_REF", "ghcr.io/mojtaba-arvin/agent-native-t16@sha256:" + "b" * 64)
RUNNER_PATH = Path(__file__).with_name("one-command-runner.py")
SPEC = importlib.util.spec_from_file_location("t16_one_command_runner", RUNNER_PATH)
RUNNER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(RUNNER)


class OneCommandTests(unittest.TestCase):
    def test_launcher_uses_one_cached_image_without_installing_host_tools(self):
        source = Path(__file__).with_name("one-command.sh").read_text()
        self.assertIn('API="https://api.github.com"', source)
        self.assertIn('"$API/user"', source)
        self.assertIn('"$API/repos/$REPOSITORY/commits?sha=$BRANCH&per_page=1"', source)
        self.assertIn("set +x", source)
        self.assertIn('IFS= read -r -s GH_TOKEN </dev/tty', source)
        self.assertIn("export GH_TOKEN", source)
        self.assertIn("public_repo and read:packages scopes", source)
        self.assertNotIn('API="https://api.github.com/repos/$REPOSITORY"', source)
        self.assertIn('docker pull "$IMAGE:t16"', source)
        self.assertNotIn("apk add", source)
        self.assertNotIn("docker:27.5.1-cli", source)
        self.assertIn("RepoDigests", source)
        self.assertIn("T16_IMAGE_REF", source)
        self.assertIn("$" + "{GH_TOKEN:", source)

    def test_evidence_is_a_release_asset_bound_to_the_exact_source_commit(self):
        source = RUNNER_PATH.read_text()
        self.assertIn('"/repos/%s/releases"', source)
        self.assertIn('"target_commitish": source_sha', source)
        self.assertIn("upload_url", source)
        self.assertIn("tarfile.open", source)
        self.assertIn('asset.get("state") != "uploaded"', source)
        self.assertIn("local evidence preserved at:", source)
        self.assertNotIn('git", "-C", str(staging), "push"', source)

    def test_postgres_reuses_the_same_digest_pinned_image(self):
        source = RUNNER_PATH.read_text()
        self.assertIn("pg_image = IMAGE_REF", source)
        self.assertIn('"--entrypoint", "/usr/local/bin/docker-entrypoint.sh"', source)

    def test_result_validator_requires_twenty_balanced_attempts_and_all_traces(self):
        with tempfile.TemporaryDirectory() as directory:
            evidence = Path(directory)
            (evidence / "report.md").write_text("report")
            (evidence / "ledger.jsonl").write_text("\n".join("{}" for _ in range(20)) + "\n")
            records = []
            for candidate in ("go-net-http", "rust-tokio-hyper"):
                for index in range(10):
                    trace = "trace-%s-%02d.jsonl" % (candidate, index)
                    (evidence / trace).write_text("{}\n")
                    records.append({"candidate": candidate, "status": "completed",
                                    "slo_pass": index < 5, "raw_trace": trace})
            results = {"runs": records, "source_sha": "a" * 40,
                       "image_ref": os.environ["T16_IMAGE_REF"]}
            self.assertEqual(RUNNER.validate_completed_results(
                results, evidence, "a" * 40, os.environ["T16_IMAGE_REF"]), 10)
            (evidence / records[0]["raw_trace"]).unlink()
            with self.assertRaisesRegex(RuntimeError, "raw request traces"):
                RUNNER.validate_completed_results(
                    results, evidence, "a" * 40, os.environ["T16_IMAGE_REF"])

    def test_release_upload_verifies_asset_and_anchors_tag_to_source_sha(self):
        with tempfile.TemporaryDirectory() as directory:
            evidence = Path(directory)
            (evidence / "report.md").write_text("measured report")
            source_sha = "c" * 40
            release = {"upload_url": "https://uploads.github.com/repos/example/releases/1/assets{?name,label}",
                       "html_url": "https://github.com/example/releases/tag/t16-test"}
            payload = {"state": "uploaded", "name": "t16-evidence-run.tar.gz",
                       "size": 1, "browser_download_url": "https://github.com/example/archive.tar.gz"}
            response = mock.MagicMock()
            response.__enter__.return_value.read.return_value = json.dumps(payload).encode()
            with mock.patch.object(RUNNER, "github_api", return_value=release) as api, \
                 mock.patch.object(RUNNER.urllib.request, "urlopen", return_value=response) as upload:
                def uploaded(req, timeout):
                    body = req.data
                    payload["size"] = len(body)
                    response.__enter__.return_value.read.return_value = json.dumps(payload).encode()
                    with tarfile.open(fileobj=io.BytesIO(body), mode="r:gz") as archive:
                        self.assertTrue(any(name.endswith("/checksums.sha256") for name in archive.getnames()))
                    return response
                upload.side_effect = uploaded
                url = RUNNER.publish_evidence(
                    evidence, "run", source_sha, os.environ["T16_IMAGE_REF"], 123,
                    "https://github.com/mojtaba-arvin/agent-native/actions/runs/123")
            self.assertEqual(url, payload["browser_download_url"])
            release_payload = api.call_args.args[2]
            self.assertEqual(release_payload["target_commitish"], source_sha)
            self.assertEqual(upload.call_count, 1)


if __name__ == "__main__":
    unittest.main()
