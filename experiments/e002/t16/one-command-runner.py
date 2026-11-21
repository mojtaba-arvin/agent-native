#!/usr/bin/env python3
"""Controlled-host T16 execution and immutable publication of its evidence."""
import datetime as dt
import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import time
import uuid
import tarfile
import urllib.request
import urllib.error
from pathlib import Path

REPO = "mojtaba-arvin/agent-native"
TOKEN = os.environ["GH_TOKEN"]
SOURCE_SHA = os.environ["T16_SOURCE_SHA"]
IMAGE_REF = os.environ["T16_IMAGE_REF"]
IMAGE_NAME = "ghcr.io/mojtaba-arvin/agent-native-t16"
API = "https://api.github.com"


def run(args, check=True, capture=False, env=None, cwd=None):
    return subprocess.run(args, check=check, text=True, env=env, cwd=cwd,
                           stdout=subprocess.PIPE if capture else None,
                           stderr=subprocess.STDOUT if capture else None)


def git_auth_env():
    import base64
    env = os.environ.copy()
    encoded = base64.b64encode(("x-access-token:" + TOKEN).encode()).decode()
    env.update({"GIT_CONFIG_COUNT": "1",
                "GIT_CONFIG_KEY_0": "http.https://github.com/.extraheader",
                "GIT_CONFIG_VALUE_0": "AUTHORIZATION: basic " + encoded})
    return env


def github_login():
    import urllib.request
    request = urllib.request.Request(API + "/user", headers={
        "Authorization": "Bearer " + TOKEN,
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28"})
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.load(response)["login"]


def choose_physical_cores():
    selected, seen = [], set()
    for cpu in sorted(os.sched_getaffinity(0)):
        topology = Path("/sys/devices/system/cpu/cpu%d/topology" % cpu)
        key = (int((topology / "physical_package_id").read_text()),
               int((topology / "core_id").read_text()))
        if key not in seen:
            selected.append(cpu)
            seen.add(key)
        if len(selected) == 3:
            break
    if len(selected) != 3:
        raise RuntimeError("T16 requires three distinct physical CPU cores available to this host.")
    return selected


def wait_postgres(dsn):
    deadline = time.monotonic() + 120
    while time.monotonic() < deadline:
        result = run(["psql", dsn, "-X", "-A", "-t", "-c", "SELECT 1"], check=False, capture=True)
        if result.returncode == 0 and result.stdout.strip() == "1":
            return
        time.sleep(2)
    raise TimeoutError("T16 PostgreSQL container failed readiness checks.")


def stream_process(args, log_path, cwd=None):
    with log_path.open("w", encoding="utf-8") as log:
        process = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                   text=True, bufsize=1, cwd=cwd)
        for line in process.stdout:
            safe = re.sub(r"(T16_READ_TOKEN|T16_DENY_TOKEN)=[^ '\"]+", r"\1=[REDACTED]", line)
            print(safe, end="", flush=True)
            log.write(safe)
        return process.wait()


def github_api(method, path, payload=None, content_type="application/vnd.github+json"):
    data = json.dumps(payload).encode() if payload is not None else None
    request = urllib.request.Request(API + path, data=data, method=method, headers={
        "Authorization": "Bearer " + TOKEN, "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28", "Content-Type": content_type})
    try:
        with urllib.request.urlopen(request, timeout=180) as response:
            body = response.read()
            return json.loads(body) if body else {}
    except urllib.error.HTTPError as exc:
        detail = exc.read(2000).decode("utf-8", "replace")
        raise RuntimeError("GitHub API %s %s failed (%s): %s" % (method, path, exc.code, detail))


def resolve_build_run(source_sha):
    branch = github_api("GET", "/repos/%s/commits?sha=task/T16-image-digest-pipeline&per_page=1" % REPO)
    if not branch or branch[0].get("sha") != source_sha:
        raise RuntimeError("Pulled image revision is not the current T16 branch head.")
    runs = github_api("GET", "/repos/%s/actions/workflows/t16-image.yml/runs?branch=task/T16-image-digest-pipeline&event=push&per_page=50" % REPO)
    match = next((item for item in runs.get("workflow_runs", [])
                  if item.get("head_sha") == source_sha and item.get("status") == "completed"
                  and item.get("conclusion") == "success"), None)
    if not match:
        raise RuntimeError("No successful immutable-image workflow exists for this source SHA.")
    return int(match["id"]), match["html_url"]


def publish_evidence(evidence, run_id, source_sha, image_ref, build_run_id, build_url):
    archive_fd, archive_name = tempfile.mkstemp(prefix="t16-evidence-", suffix=".tar.gz")
    os.close(archive_fd)
    archive_path = Path(archive_name)
    checksums = []
    for item in sorted(evidence.rglob("*")):
        if item.is_file() and item.name != "checksums.sha256":
            checksums.append("%s  %s" % (hashlib.sha256(item.read_bytes()).hexdigest(), item.relative_to(evidence)))
    (evidence / "checksums.sha256").write_text("\n".join(checksums) + "\n")
    with tarfile.open(archive_path, "w:gz", compresslevel=6) as archive:
        archive.add(evidence, arcname="T16/" + run_id)
    asset_name = "t16-evidence-" + run_id + ".tar.gz"
    tag = "t16-run-" + run_id
    try:
        release = github_api("POST", "/repos/%s/releases" % REPO, {
            "tag_name": tag, "target_commitish": source_sha,
            "name": "T16 controlled-host run " + run_id,
            "body": "Source: %s\nImage: %s\nBuild: %s\nInspect execution-metadata.json in the attached archive." % (source_sha, image_ref, build_url),
            "draft": False, "prerelease": False})
        upload_url = release["upload_url"].split("{", 1)[0] + "?name=" + asset_name
        archive_size = archive_path.stat().st_size
        asset = None
        last_error = None
        for attempt in range(1, 4):
            request = urllib.request.Request(upload_url, data=archive_path.read_bytes(), method="POST", headers={
                "Authorization": "Bearer " + TOKEN, "Accept": "application/vnd.github+json",
                "Content-Type": "application/octet-stream"})
            try:
                with urllib.request.urlopen(request, timeout=900) as response:
                    asset = json.loads(response.read())
                break
            except (urllib.error.HTTPError, urllib.error.URLError) as exc:
                last_error = exc
                if attempt < 3:
                    time.sleep(attempt * 3)
        if asset is None:
            raise RuntimeError("Release asset upload failed after 3 attempts: %s" % last_error)
        if asset.get("state") != "uploaded" or asset.get("name") != asset_name or int(asset.get("size", -1)) != archive_size:
            raise RuntimeError("GitHub accepted an evidence upload but its asset metadata failed verification.")
        return asset.get("browser_download_url") or release["html_url"]
    finally:
        archive_path.unlink(missing_ok=True)



def validate_completed_results(results, evidence, source_sha, image_ref):
    records = results.get("runs", [])
    completed = sum(1 for item in records if item.get("status") == "completed")
    candidate_counts = {
        name: sum(1 for item in records if item.get("candidate") == name and item.get("status") == "completed")
        for name in ("go-net-http", "rust-tokio-hyper")
    }
    if len(records) != 20 or completed != 20 or candidate_counts != {"go-net-http": 10, "rust-tokio-hyper": 10}:
        raise RuntimeError("T16 matrix incomplete or imbalanced: %d records, %d completed, cohorts=%s." %
                           (len(records), completed, candidate_counts))
    if results.get("source_sha") != source_sha or results.get("image_ref") != image_ref:
        raise RuntimeError("Results metadata does not match the executed source and image digest.")
    if not (evidence / "report.md").is_file() or not (evidence / "ledger.jsonl").is_file():
        raise RuntimeError("T16 report or append-only ledger is missing.")
    missing_traces = [item.get("raw_trace") for item in records
                      if not item.get("raw_trace") or not (evidence / item["raw_trace"]).is_file()]
    if missing_traces:
        raise RuntimeError("T16 raw request traces are missing: %s" % missing_traces[:3])
    ledger_records = [line for line in (evidence / "ledger.jsonl").read_text().splitlines() if line.strip()]
    if len(ledger_records) != 20:
        raise RuntimeError("T16 append-only ledger does not contain exactly 20 attempts.")
    return sum(1 for item in records if item.get("slo_pass") is True)

def main():
    if platform.system() != "Linux" or os.getenv("GITHUB_ACTIONS", "").lower() == "true":
        raise RuntimeError("Only a non-GitHub-Runner Linux host is accepted.")
    if platform.machine().lower() not in {"x86_64", "amd64"}:
        raise RuntimeError("The published T16 image currently targets linux/amd64; this host is not x86_64.")
    sha = SOURCE_SHA
    if not re.fullmatch(r"[0-9a-f]{40}", sha) or not re.fullmatch(
            r"ghcr\.io/mojtaba-arvin/agent-native-t16@sha256:[0-9a-f]{64}", IMAGE_REF):
        raise RuntimeError("Invalid source SHA or immutable image reference.")
    image_info = run(["docker", "image", "inspect", "--format", "{{json .RepoDigests}}", IMAGE_REF], capture=True)
    if IMAGE_REF not in json.loads(image_info.stdout):
        raise RuntimeError("Controller image is not the exact local RepoDigest.")
    build_run_id, build_run_url = resolve_build_run(sha)
    lock = {"schema_version": 1, "source_sha": sha, "image_name": IMAGE_NAME,
            "image_ref": IMAGE_REF, "image_digest": IMAGE_REF.rsplit("@", 1)[1],
            "build_run_url": build_run_url, "build_run_id": build_run_id}

    root = Path(tempfile.mkdtemp(prefix="agent-native-t16-")) / "source"
    run(["git", "clone", "--depth", "1", "--branch", "task/T16-image-digest-pipeline", "https://github.com/%s.git" % REPO, str(root)], env=git_auth_env())
    run(["git", "-C", str(root), "checkout", "--detach", sha])
    if run(["git", "-C", str(root), "rev-parse", "HEAD"], capture=True).stdout.strip() != sha:
        raise RuntimeError("Checked-out source SHA differs from image lock.")
    sys.path.insert(0, str(root / "experiments/e002/t16"))
    import preflight

    _, _, postgres_cpu = choose_physical_cores()
    run_id = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:8]
    evidence = root / "experiments/e002/t16/evidence" / run_id
    evidence.mkdir(parents=True)
    (evidence / "image-lock.json").write_text(json.dumps(lock, indent=2, sort_keys=True) + "\n")
    machine_id = Path("/host-machine-id").read_text().strip() if Path("/host-machine-id").exists() else platform.node()
    host_id = hashlib.sha256(machine_id.encode()).hexdigest()[:24]
    operator = github_login()
    attestation = {"dedicated_physical_host": True, "host_id": host_id, "attested_by": operator,
                   "attested_at": dt.datetime.now(dt.timezone.utc).isoformat(),
                   "attestation_basis": "operator declaration for this one-command invocation"}
    attestation_path = Path(tempfile.mkdtemp(prefix="t16-attestation-")) / "host.json"
    attestation_path.write_text(json.dumps(attestation, indent=2) + "\n")
    (evidence / "operator-attestation.json").write_text(json.dumps(attestation, indent=2, sort_keys=True) + "\n")
    pg_image = IMAGE_REF
    pg_name = "t16-postgres-" + uuid.uuid4().hex[:10]
    dsn = "postgresql://postgres@127.0.0.1:5432/agent_native?sslmode=disable"
    pg_started = False
    status = "failed"
    try:
        run(["docker", "pull", pg_image])
        run(["docker", "run", "--detach", "--name", pg_name, "--pid=host", "--network=host", "--entrypoint", "/usr/local/bin/docker-entrypoint.sh",
             "--cpus=1", "--cpuset-cpus=%d" % postgres_cpu, "--memory=2g",
             "--env", "POSTGRES_HOST_AUTH_METHOD=trust", "--env", "POSTGRES_DB=agent_native",
             pg_image, "-c", "listen_addresses=127.0.0.1"])
        pg_started = True
        wait_postgres(dsn)
        runner = ["python3", str(root / "experiments/e002/t16/run.py"), "--output", str(evidence),
                  "--source-sha", sha, "--image-ref", IMAGE_REF,
                  "--build-run-url", build_run_url, "--postgres-dsn", dsn]
        prereg_command = " ".join(subprocess.list2cmdline([arg]) for arg in runner)
        pre = run(["python3", str(root / "experiments/e002/t16/preflight.py"),
                   "--attestation", str(attestation_path), "--output", str(evidence),
                   "--source-sha", sha, "--image-ref", IMAGE_REF, "--image-tag", sha,
                   "--build-run-url", build_run_url, "--postgres-dsn", dsn,
                   "--command", prereg_command], check=False, capture=True, cwd=str(root))
        (evidence / "preflight.log").write_text(pre.stdout or "")
        if pre.returncode:
            raise RuntimeError("Preflight failed; diagnostics will be published.")
        result_code = stream_process(runner, evidence / "execution.log", cwd=str(root))
        if result_code:
            raise RuntimeError("T16 runner failed; partial evidence will be published.")
        results_file = evidence / "results.json"
        if not results_file.is_file():
            raise RuntimeError("Runner did not produce results.json.")
        results = json.loads(results_file.read_text())
        slo_passed = validate_completed_results(results, evidence, sha, IMAGE_REF)
        status = "completed"
        print("T16 matrix completed: 20/20 attempts recorded.", flush=True)
        print("T16 per-attempt SLO result: %d/20 passed; see report.md for cohort details." % slo_passed, flush=True)
    finally:
        if pg_started:
            run(["docker", "rm", "--force", "--volumes", pg_name], check=False)
        metadata = {"status": status, "source_sha": sha, "image_ref": IMAGE_REF,
                    "build_run_url": build_run_url, "build_run_id": build_run_id,
                    "host_attestation": attestation, "finished_at": dt.datetime.now(dt.timezone.utc).isoformat()}
        if status == "completed" and (evidence / "results.json").is_file():
            result_data = json.loads((evidence / "results.json").read_text())
            metadata["attempts_recorded"] = len(result_data.get("runs", []))
            metadata["slo_passed_attempts"] = sum(1 for item in result_data.get("runs", []) if item.get("slo_pass") is True)
            metadata["benchmark_slo"] = "passed" if metadata["slo_passed_attempts"] == 20 else "failed"
        (evidence / "execution-metadata.json").write_text(json.dumps(metadata, indent=2, sort_keys=True) + "\n")
        try:
            url = publish_evidence(evidence, run_id, sha, IMAGE_REF, build_run_id, build_run_url)
            print("T16 evidence: " + url, flush=True)
            print("T16 status: " + status.upper(), flush=True)
        finally:
            shutil.rmtree(root.parent, ignore_errors=True)
            shutil.rmtree(attestation_path.parent, ignore_errors=True)
    return 0 if status == "completed" else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print("T16 controller failed: %s: %s" % (type(exc).__name__, exc), file=sys.stderr, flush=True)
        raise SystemExit(1)
