"""Pure validation helpers shared by the T16 bootstrap and tests."""
import re


def validate_lock(lock, sha):
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
