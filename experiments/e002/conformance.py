#!/usr/bin/env python3
"""Black-box E-002 workload checks shared by all native/runtime candidates."""
from __future__ import annotations

import argparse
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path


BASE = "http://127.0.0.1:8080"


def request(path: str) -> tuple[int, bytes]:
    try:
        with urllib.request.urlopen(BASE + path, timeout=3) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as error:
        return error.code, error.read()


def wait_ready() -> None:
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        try:
            status, body = request("/health")
            if status == 200 and body == b"ok":
                return
        except (OSError, TimeoutError):
            pass
        time.sleep(0.1)
    raise RuntimeError("candidate did not become healthy within 20 seconds")


def verify() -> None:
    checks = [
        ("/health", 200, b"ok"),
        ("/work?ms=20", 200, b"completed:20"),
        ("/work?ms=900", 504, b"deadline exceeded\n" if False else b"deadline exceeded"),
        ("/work?ms=invalid", 400, b"invalid ms"),
    ]
    for path, expected_status, expected_body in checks:
        status, body = request(path)
        if status != expected_status or not body.startswith(expected_body):
            raise AssertionError(
                f"{path}: expected {expected_status}/{expected_body!r}, "
                f"received {status}/{body!r}"
            )

    status, body = request("/stream")
    expected = b"chunk-1\nchunk-2\nchunk-3\n"
    if status != 200 or body != expected:
        raise AssertionError(f"/stream: expected 200/{expected!r}, received {status}/{body!r}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--command", required=True, help="candidate executable command")
    parser.add_argument("--cwd", required=True, help="candidate working directory")
    args = parser.parse_args()
    process = subprocess.Popen(args.command.split(), cwd=Path(args.cwd))
    try:
        wait_ready()
        verify()
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
    print("E-002 black-box conformance: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
