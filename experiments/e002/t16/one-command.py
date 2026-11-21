#!/usr/bin/env python3
"""Dispatch image publication, fetch immutable lock, launch controlled-host controller."""
import datetime as dt
import base64
import json
import os
import subprocess
import sys
import time
import uuid
import zipfile
from io import BytesIO
import requests

API = "https://api.github.com"
REPO = os.environ.get("T16_REPOSITORY", "mojtaba-arvin/agent-native")
BRANCH = os.environ.get("T16_BRANCH", "task/T16-image-digest-pipeline")
TOKEN = os.environ["GH_TOKEN"]
S = requests.Session()
S.headers.update({"Accept": "application/vnd.github+json", "Authorization": "Bearer " + TOKEN,
                  "X-GitHub-Api-Version": "2022-11-28"})


def api(method, path, **kwargs):
    response = S.request(method, API + path, timeout=90, **kwargs)
    if not response.ok:
        raise RuntimeError("GitHub API error %s %s: %s" % (method, path, response.text[:1500]))
    return response


def docker(*args, check=True):
    return subprocess.run(["docker", *args], check=check, text=True)


def validate_lock(lock, sha):
    import re
    if lock.get("source_sha") != sha or not re.fullmatch(r"[0-9a-f]{40}", sha):
        raise RuntimeError("Image-lock source SHA is invalid or inconsistent.")
    name = "ghcr.io/mojtaba-arvin/agent-native-t16"
    digest = lock.get("image_digest", "")
    if lock.get("image_name") != name or not re.fullmatch(r"sha256:[0-9a-f]{64}", digest):
        raise RuntimeError("Image-lock package name or digest is invalid.")
    if lock.get("image_ref") != name + "@" + digest or lock.get("image_tag") != sha:
        raise RuntimeError("Image-lock is not pinned to exact source SHA and digest.")
    if lock.get("dockerfile_path") != "experiments/e002/t16/Dockerfile":
        raise RuntimeError("Unexpected Dockerfile path in image-lock.")
    return lock


def build_and_get_lock():
    login = api("GET", "/user").json()["login"]
    started = dt.datetime.now(dt.timezone.utc)
    trigger_name = ".t16-trigger-" + uuid.uuid4().hex + ".json"
    trigger_content = json.dumps({"requested_at": started.isoformat(), "requested_by": login,
                                  "purpose": "publish immutable T16 benchmark image"}).encode()
    trigger = api("PUT", "/repos/%s/contents/experiments/e002/t16/%s" % (REPO, trigger_name),
                  json={"message": "ci(t16): trigger immutable image publication",
                        "content": base64.b64encode(trigger_content).decode(), "branch": BRANCH}).json()
    trigger_sha = trigger["commit"]["sha"]
    print("Committed a unique T16 build trigger; waiting for GitHub Actions...", flush=True)
    deadline = time.monotonic() + 3600
    run = None
    while time.monotonic() < deadline:
        runs = api("GET", "/repos/%s/actions/workflows/t16-image.yml/runs" % REPO,
                   params={"branch": BRANCH, "event": "push", "per_page": 20}).json()["workflow_runs"]
        fresh = [r for r in runs if r.get("head_branch") == BRANCH and r.get("head_sha") == trigger_sha]
        if fresh:
            run = fresh[0]
            print("Image workflow %s: %s" % (run["id"], run["status"]), flush=True)
            if run["status"] == "completed":
                break
        time.sleep(15)
    if not run or run.get("status") != "completed" or run.get("conclusion") != "success":
        raise RuntimeError("T16 image build/publish workflow did not succeed.")
    jobs = api("GET", "/repos/%s/actions/runs/%s/jobs" % (REPO, run["id"])).json()["jobs"]
    if not any(j.get("name") == "publish" and j.get("conclusion") == "success" for j in jobs):
        raise RuntimeError("The image publication job did not succeed.")
    artifact_name = "t16-image-lock-" + run["head_sha"]
    artifacts = api("GET", "/repos/%s/actions/runs/%s/artifacts" % (REPO, run["id"]),
                    params={"per_page": 100}).json()["artifacts"]
    artifact = next((a for a in artifacts if a["name"] == artifact_name and not a["expired"]), None)
    if not artifact:
        raise RuntimeError("The image-lock artifact is missing.")
    response = S.get(artifact["archive_download_url"], timeout=180)
    response.raise_for_status()
    with zipfile.ZipFile(BytesIO(response.content)) as archive:
        if archive.namelist() != ["image-lock.json"]:
            raise RuntimeError("Unexpected image-lock artifact contents.")
        lock = json.loads(archive.read("image-lock.json"))
    return validate_lock(lock, trigger_sha), int(run["id"]), login


def main():
    lock, build_run_id, username = build_and_get_lock()
    print("Published immutable image: " + lock["image_ref"], flush=True)
    volume = "t16-ghcr-auth-" + uuid.uuid4().hex[:12]
    docker("volume", "create", volume)
    try:
        docker("run", "--rm", "--volume", "/var/run/docker.sock:/var/run/docker.sock",
               "--volume", volume + ":/root/.docker", "--env", "GH_TOKEN",
               "--env", "GH_USERNAME=" + username, "--entrypoint", "sh", "docker:27.5.1-cli",
               "-ec", 'printf "%s" "$GH_TOKEN" | docker login ghcr.io -u "$GH_USERNAME" --password-stdin')
        docker("run", "--rm", "--privileged", "--pid=host", "--cgroupns=host", "--network=host",
               "--volume", "/var/run/docker.sock:/var/run/docker.sock",
               "--volume", "/sys/fs/cgroup:/sys/fs/cgroup",
               "--volume", "/etc/machine-id:/host-machine-id:ro",
               "--volume", volume + ":/root/.docker", "--env", "GH_TOKEN",
               "--env", "T16_IMAGE_LOCK_JSON=" + json.dumps(lock, separators=(",", ":")),
               "--env", "T16_BUILD_RUN_ID=" + str(build_run_id),
               "--entrypoint", "python3", lock["image_ref"], "/usr/local/bin/t16-one-command-runner.py")
    finally:
        docker("volume", "rm", "-f", volume, check=False)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print("T16 one-command failed: %s: %s" % (type(exc).__name__, exc), file=sys.stderr, flush=True)
        raise SystemExit(1)
