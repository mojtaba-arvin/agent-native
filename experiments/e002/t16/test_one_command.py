import importlib.util
import io
import json
import os
import sys
import tarfile
import tempfile
import unittest
import urllib.error
from email.message import Message
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
    def test_controller_stream_redacts_signing_key_and_postgres_dsn(self):
        with tempfile.TemporaryDirectory() as directory:
            log_path = Path(directory) / "execution.log"
            output = io.StringIO()
            script = (
                "print('T16_SIGNING_KEY=signing-secret')\n"
                "print('T16_PSQL_DSN=postgresql://user:password@host/db')\n"
                "print('connection failed for postgresql://user:password@host/db')\n"
            )
            with mock.patch("sys.stdout", output):
                status = RUNNER.stream_process([sys.executable, "-c", script], log_path)
            rendered = output.getvalue() + log_path.read_text(encoding="utf-8")
            self.assertEqual(status, 0)
            for secret in ("signing-secret", "password@host"):
                self.assertNotIn(secret, rendered)
            self.assertIn("T16_SIGNING_KEY=[REDACTED]", rendered)
            self.assertIn("T16_PSQL_DSN=[REDACTED]", rendered)
            self.assertIn("postgresql://[REDACTED]", rendered)

    def test_controller_retries_transient_github_api_failures(self):
        headers = Message()
        temporary = urllib.error.HTTPError(
            "https://api.github.com/user", 503, "Service Unavailable",
            headers, io.BytesIO(b"temporary upstream failure"),
        )
        response = mock.MagicMock()
        response.__enter__.return_value.read.return_value = b'{"login":"t16-operator"}'
        with mock.patch.object(
            RUNNER.urllib.request, "urlopen", side_effect=[temporary, response]
        ) as urlopen, mock.patch.object(RUNNER.time, "sleep") as sleep:
            result = RUNNER.github_api("GET", "/user")
        self.assertEqual(result, {"login": "t16-operator"})
        self.assertEqual(urlopen.call_count, 2)
        sleep.assert_called_once_with(5)

    def test_launcher_uses_one_cached_image_without_installing_host_tools(self):
        source = Path(__file__).with_name("one-command.sh").read_text()
        self.assertIn('API="https://api.github.com"', source)
        self.assertIn('"$API/user"', source)
        self.assertIn('s/^[[:space:]]*"login"[[:space:]]*:[[:space:]]*"\\([^" ]*\\)".*/\\1/p', source)
        self.assertIn('s/^[[:space:]]*"sha"[[:space:]]*:[[:space:]]*"\\([0-9a-f]\\{40\\}\\)".*/\\1/p', source)
        self.assertIn('| head -n 1)', source)
        self.assertNotIn("1s/^{", source)
        self.assertIn('s/^[[:space:]]*"login"[[:space:]]*:[[:space:]]*"\\([^"]*\\)".*/\\1/p', source)
        self.assertIn('| head -n 1)', source)
        self.assertNotIn("1s/^{", source)
        self.assertIn('"$API/repos/$REPOSITORY/commits?sha=$BRANCH&per_page=1"', source)
        self.assertIn("set +x", source)
        self.assertIn('IFS= read -r -s GH_TOKEN </dev/tty', source)
        self.assertIn("export GH_TOKEN", source)
        self.assertIn("github_get()", source)
        self.assertIn("--config -", source)
        self.assertNotIn('-H "Authorization: Bearer $GH_TOKEN"', source)
        self.assertIn("public_repo and read:packages scopes", source)
        self.assertIn("RUN-T16-ON-DEDICATED-HOST", source)
        self.assertIn("T16_OPERATOR_ATTESTED=YES", source)
        self.assertNotIn('API="https://api.github.com/repos/$REPOSITORY"', source)
        self.assertIn('docker pull "$IMAGE:t16"', source)
        self.assertNotIn("apk add", source)
        self.assertNotIn("docker:27.5.1-cli", source)
        self.assertIn("RepoDigests", source)
        self.assertIn("T16_IMAGE_REF", source)
        self.assertIn("HOST_LOG=", source)
        self.assertIn("controller.log", source)
        self.assertIn("curl_retry()", source)
        self.assertIn("--retry 5", source)
        self.assertIn("pull_ok=0", source)
        self.assertIn("login_ok=0", source)
        self.assertIn("export GH_TOKEN", source)
        self.assertIn('--volume "$LOG_DIR:/host-t16-logs:rw"', source)
        self.assertIn("$" + "{GH_TOKEN:", source)

    def test_controller_reuses_the_single_pulled_image_for_postgres(self):
        runner = RUNNER_PATH.read_text()
        self.assertIn("T16_SIGNING_KEY|T16_PSQL_DSN", runner)
        self.assertIn("postgres(?:ql)?://", runner)
        self.assertIn("Reusing the already-pulled controller image for PostgreSQL", runner)
        self.assertNotIn('run(["docker", "pull", pg_image])', runner)

    def test_hmac_capability_tokens_are_baked_and_used_by_both_candidates(self):
        root = Path(__file__).resolve().parents[3]
        dockerfile = (root / "experiments/e002/t16/Dockerfile").read_text()
        ignore = (root / "experiments/e002/t16/Dockerfile.dockerignore").read_text()
        runner = (root / "experiments/e002/t16/run.py").read_text()
        go = (root / "experiments/e002/go/product.go").read_text()
        rust = (root / "experiments/e002/rust/src/product.rs").read_text()
        rust_auth = (root / "experiments/e002/rust/src/t16_auth.rs").read_text()
        self.assertIn("!experiments/e002/t16/tokens.py", ignore)
        self.assertIn("tokens.py", dockerfile)
        self.assertIn("libssl-dev", dockerfile)
        self.assertIn("libssl3", dockerfile)
        self.assertIn("issue_benchmark_tokens(signing_key)", runner)
        self.assertIn("T16_SIGNING_KEY=", runner)
        self.assertIn("verifyT16Bearer", go)
        self.assertIn("verify_bearer", rust)
        self.assertIn("HMAC", rust_auth)

    def test_host_attestation_matches_acceptance_contract_and_is_explicit(self):
        source = RUNNER_PATH.read_text()
        launcher = Path(__file__).with_name("one-command.sh").read_text()
        self.assertIn('hexdigest()[:16]', source)
        self.assertIn('"attestation_basis": "operator declaration for this one-command invocation"', source)
        self.assertIn("RUN-T16-ON-DEDICATED-HOST", launcher)
        self.assertIn("T16_OPERATOR_ATTESTED=YES", launcher)

    def test_all_published_dockerfile_base_images_are_required_as_build_arguments(self):
        root = Path(__file__).resolve().parents[3]
        dockerfile = (root / "experiments/e002/t16/Dockerfile").read_text()
        workflow = (root / ".github/workflows/t16-image.yml").read_text()
        for name in ("GO_IMAGE", "RUST_IMAGE", "POSTGRES_IMAGE", "DOCKER_IMAGE"):
            argument = next(line for line in dockerfile.splitlines() if line.startswith("ARG " + name + "="))
            self.assertRegex(argument, r"@sha256:[0-9a-f]{64}$")
            self.assertIn(name + "=${{ needs.validate-and-build.outputs.", workflow)
        self.assertIn("docker:27.5.1-cli", workflow)

    def test_controller_redacts_hmac_signing_key_from_command_logs(self):
        source = RUNNER_PATH.read_text()
        self.assertIn("T16_SIGNING_KEY=", source)
        self.assertIn("T16_PSQL_DSN=", source)
        self.assertIn("[REDACTED]", source)

    def test_controller_uses_baked_source_and_never_clones_at_runtime(self):
        source = RUNNER_PATH.read_text()
        self.assertIn('Path("/opt/t16-source")', source)
        self.assertIn("T16_BAKED_SOURCE_SHA", source)
        self.assertIn('os.getenv("T16_OPERATOR_ATTESTED") != "YES"', source)
        self.assertIn('gh", "attestation", "verify', source)
        self.assertNotIn('["git", "clone"', source)
        self.assertIn('host_log_dir / "evidence" / run_id', source)

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
                        self.assertTrue(any(name.endswith("/evidence-manifest.json") for name in archive.getnames()))
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
