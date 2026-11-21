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
from pathlib import Path

REPO = "mojtaba-arvin/agent-native"
TOKEN = os.environ["GH_TOKEN"]
LOCK = json.loads(os.environ["T16_IMAGE_LOCK_JSON"])
BUILD_RUN_ID = os.environ["T16_BUILD_RUN_ID"]
API = "https://api.github.com"


def run(args, check=True, capture=False, env=None):
    return subprocess.run(args, check=check, text=True, env=env,
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


def stream_process(args, log_path):
    with log_path.open("w", encoding="utf-8") as log:
        process = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                   text=True, bufsize=1)
        for line in process.stdout:
            safe = re.sub(r"(T16_READ_TOKEN|T16_DENY_TOKEN)=[^ '\"]+", r"\1=[REDACTED]", line)
            print(safe, end="", flush=True)
            log.write(safe)
        return process.wait()


def publish_evidence(evidence, run_id, source_sha):
    branch = "t16-results/%s-%s" % (run_id, source_sha[:8])
    staging = Path(tempfile.mkdtemp(prefix="t16-results-"))
    payload = staging / "T16" / run_id
    payload.mkdir(parents=True)
    for item in evidence.iterdir():
        target = payload / item.name
        if item.is_dir():
            shutil.copytree(item, target)
        elif item.is_file():
            shutil.copy2(item, target)
    checksums = []
    for item in sorted(payload.rglob("*")):
        if item.is_file() and item.name != "checksums.sha256":
            checksums.append("%s  %s" % (hashlib.sha256(item.read_bytes()).hexdigest(), item.relative_to(payload)))
    (payload / "checksums.sha256").write_text("\n".join(checksums) + "\n")
    (staging / "README.md").write_text(
        "# T16 controlled-host results\n\n"
        "- Source: %s\n- Image: %s\n- Build: https://github.com/%s/actions/runs/%s\n"
        "- Evidence: T16/%s/\n" % (source_sha, LOCK["image_ref"], REPO, BUILD_RUN_ID, run_id))
    run(["git", "init", "-b", branch, str(staging)])
    run(["git", "-C", str(staging), "config", "user.name", "T16 Results Bot"])
    run(["git", "-C", str(staging), "config", "user.email", "t16-results@users.noreply.github.com"])
    run(["git", "-C", str(staging), "add", "--all"])
    run(["git", "-C", str(staging), "commit", "-m", "results(t16): publish controlled-host run " + run_id])
    run(["git", "-C", str(staging), "remote", "add", "origin", "https://github.com/%s.git" % REPO])
    run(["git", "-C", str(staging), "push", "origin", "HEAD:refs/heads/" + branch], env=git_auth_env())
    return "https://github.com/%s/tree/%s/T16/%s" % (REPO, branch, run_id)


def main():
    if platform.system() != "Linux" or os.getenv("GITHUB_ACTIONS", "").lower() == "true":
        raise RuntimeError("Only a non-GitHub-Runner Linux host is accepted.")
    name = "ghcr.io/mojtaba-arvin/agent-native-t16"
    digest = LOCK.get("image_digest", "")
    sha = LOCK.get("source_sha", "")
    if LOCK.get("image_name") != name or LOCK.get("image_ref") != name + "@" + digest:
        raise RuntimeError("Invalid immutable image lock.")
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", digest) or not re.fullmatch(r"[0-9a-f]{40}", sha):
        raise RuntimeError("Invalid image digest or source SHA.")

    root = Path(tempfile.mkdtemp(prefix="agent-native-t16-")) / "source"
    run(["git", "clone", "--no-checkout", "https://github.com/%s.git" % REPO, str(root)], env=git_auth_env())
    run(["git", "-C", str(root), "checkout", "--detach", sha])
    if run(["git", "-C", str(root), "rev-parse", "HEAD"], capture=True).stdout.strip() != sha:
        raise RuntimeError("Checked-out source SHA differs from image lock.")
    sys.path.insert(0, str(root / "experiments/e002/t16"))
    import preflight

    _, _, postgres_cpu = choose_physical_cores()
    run_id = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:8]
    evidence = root / "experiments/e002/t16/evidence" / run_id
    evidence.mkdir(parents=True)
    (evidence / "image-lock.json").write_text(json.dumps(LOCK, indent=2, sort_keys=True) + "\n")
    machine_id = Path("/host-machine-id").read_text().strip() if Path("/host-machine-id").exists() else platform.node()
    host_id = hashlib.sha256(machine_id.encode()).hexdigest()[:24]
    operator = github_login()
    attestation = {"dedicated_physical_host": True, "host_id": host_id, "attested_by": operator,
                   "attested_at": dt.datetime.now(dt.timezone.utc).isoformat(),
                   "attestation_basis": "operator declaration for this one-command invocation"}
    attestation_path = Path(tempfile.mkdtemp(prefix="t16-attestation-")) / "host.json"
    attestation_path.write_text(json.dumps(attestation, indent=2) + "\n")
    (evidence / "operator-attestation.json").write_text(json.dumps(attestation, indent=2, sort_keys=True) + "\n")
    pg_image = LOCK.get("base_images", {}).get("postgres", "")
    if not re.fullmatch(r"postgres:16[.]4@sha256:[0-9a-f]{64}", pg_image):
        raise RuntimeError("Image lock lacks the immutable PostgreSQL 16.4 base image.")
    pg_name = "t16-postgres-" + uuid.uuid4().hex[:10]
    dsn = "postgresql://postgres@127.0.0.1:5432/agent_native?sslmode=disable"
    pg_started = False
    status = "failed"
    try:
        run(["docker", "pull", pg_image])
        run(["docker", "run", "--detach", "--name", pg_name, "--pid=host", "--network=host",
             "--cpus=1", "--cpuset-cpus=%d" % postgres_cpu, "--memory=2g",
             "--env", "POSTGRES_HOST_AUTH_METHOD=trust", "--env", "POSTGRES_DB=agent_native",
             pg_image, "-c", "listen_addresses=127.0.0.1"])
        pg_started = True
        wait_postgres(dsn)
        runner = ["python3", str(root / "experiments/e002/t16/run.py"), "--output", str(evidence),
                  "--source-sha", sha, "--image-ref", LOCK["image_ref"],
                  "--build-run-url", LOCK["build_run_url"], "--postgres-dsn", dsn]
        prereg_command = " ".join(subprocess.list2cmdline([arg]) for arg in runner)
        pre = run(["python3", str(root / "experiments/e002/t16/preflight.py"),
                   "--attestation", str(attestation_path), "--output", str(evidence),
                   "--source-sha", sha, "--image-ref", LOCK["image_ref"], "--image-tag", LOCK["image_tag"],
                   "--build-run-url", LOCK["build_run_url"], "--postgres-dsn", dsn,
                   "--command", prereg_command], check=False, capture=True)
        (evidence / "preflight.log").write_text(pre.stdout or "")
        if pre.returncode:
            raise RuntimeError("Preflight failed; diagnostics will be published.")
        result_code = stream_process(runner, evidence / "execution.log")
        if result_code:
            raise RuntimeError("T16 runner failed; partial evidence will be published.")
        results_file = evidence / "results.json"
        if not results_file.is_file():
            raise RuntimeError("Runner did not produce results.json.")
        results = json.loads(results_file.read_text())
        completed = sum(1 for item in results.get("runs", []) if item.get("status") == "completed")
        if completed != 20:
            raise RuntimeError("T16 matrix incomplete: %d/20 attempts completed." % completed)
        status = "completed"
        print("T16 matrix completed: 20/20 attempts recorded.", flush=True)
    finally:
        if pg_started:
            run(["docker", "rm", "--force", pg_name], check=False)
        metadata = {"status": status, "source_sha": sha, "image_ref": LOCK["image_ref"],
                    "build_run_url": LOCK["build_run_url"], "build_run_id": BUILD_RUN_ID,
                    "host_attestation": attestation, "finished_at": dt.datetime.now(dt.timezone.utc).isoformat()}
        (evidence / "execution-metadata.json").write_text(json.dumps(metadata, indent=2, sort_keys=True) + "\n")
        url = publish_evidence(evidence, run_id, sha)
        print("T16 evidence: " + url, flush=True)
        print("T16 status: " + status.upper(), flush=True)
    return 0 if status == "completed" else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print("T16 controller failed: %s: %s" % (type(exc).__name__, exc), file=sys.stderr, flush=True)
        raise SystemExit(1)
