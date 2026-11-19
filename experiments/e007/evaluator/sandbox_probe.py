"""Runtime attestation for the M3 no-network Docker smoke containers.

This probe is intentionally fail-closed. It verifies the restrictions that the
workflow passes to Docker rather than treating command-line flags as evidence.
It is used only by the synthetic topology smoke; real-agent isolation requires
additional independent review and protected Environment configuration.
"""
from __future__ import annotations

import os
import socket
import tempfile
from pathlib import Path
from typing import Any


class SandboxProbeError(RuntimeError):
    pass


def parse_positive_limit(raw: str, name: str) -> int:
    value = raw.strip()
    if value == "max":
        raise SandboxProbeError(f"{name} is not bounded")
    try:
        parsed = int(value)
    except ValueError as exc:
        raise SandboxProbeError(f"{name} is not an integer limit") from exc
    if parsed <= 0:
        raise SandboxProbeError(f"{name} must be positive")
    return parsed


def parse_cpu_quota(raw: str) -> float:
    parts = raw.strip().split()
    if len(parts) != 2 or parts[0] == "max":
        raise SandboxProbeError("CPU quota is not bounded")
    quota = parse_positive_limit(parts[0], "CPU quota")
    period = parse_positive_limit(parts[1], "CPU period")
    return quota / period


def validate_sandbox_report(report: dict[str, Any]) -> None:
    if not isinstance(report, dict):
        raise SandboxProbeError("sandbox report must be an object")
    if not isinstance(report.get("effective_uid"), int) or report["effective_uid"] == 0:
        raise SandboxProbeError("sandbox must run as a non-root user")
    for field in (
        "root_read_only",
        "tmp_noexec",
        "no_new_privileges",
        "outbound_network_blocked",
        "output_mount_writable",
    ):
        if report.get(field) is not True:
            raise SandboxProbeError(f"sandbox requirement failed: {field}")
    try:
        capabilities = int(str(report.get("effective_capabilities_hex", "")), 16)
    except ValueError as exc:
        raise SandboxProbeError("effective capability mask is missing or invalid") from exc
    if capabilities != 0:
        raise SandboxProbeError("effective Linux capabilities must be zero")
    memory_limit = report.get("memory_limit_bytes")
    cpu_cores = report.get("cpu_quota_cores")
    pids_limit = report.get("pids_limit")
    if not isinstance(memory_limit, int) or not 0 < memory_limit <= 2 * 1024**3:
        raise SandboxProbeError("memory cgroup limit is missing or exceeds 2 GiB")
    if not isinstance(cpu_cores, (int, float)) or not 0 < cpu_cores <= 1.01:
        raise SandboxProbeError("CPU cgroup limit is missing or exceeds one core")
    if not isinstance(pids_limit, int) or not 0 < pids_limit <= 64:
        raise SandboxProbeError("PID cgroup limit is missing or exceeds 64")


def _proc_status() -> dict[str, str]:
    values: dict[str, str] = {}
    for line in Path("/proc/self/status").read_text(encoding="utf-8").splitlines():
        if ":" in line:
            key, value = line.split(":", 1)
            values[key] = value.strip()
    return values


def verify_sandbox(output_dir: str | Path) -> dict[str, Any]:
    if os.name != "posix" or not hasattr(os, "geteuid"):
        raise SandboxProbeError("sandbox attestation requires a POSIX runtime")
    effective_uid = os.geteuid()
    if effective_uid == 0:
        raise SandboxProbeError("container is running as root")

    root_flags = os.statvfs("/")
    readonly_flag = getattr(os, "ST_RDONLY", None)
    if readonly_flag is None or not (root_flags.f_flag & readonly_flag):
        raise SandboxProbeError("container root filesystem is not read-only")

    tmp_flags = os.statvfs("/tmp")
    noexec_flag = getattr(os, "ST_NOEXEC", None)
    if noexec_flag is None or not (tmp_flags.f_flag & noexec_flag):
        raise SandboxProbeError("/tmp is not mounted noexec")

    status = _proc_status()
    if status.get("NoNewPrivs") != "1":
        raise SandboxProbeError("no_new_privileges is not enabled")
    capabilities_hex = status.get("CapEff", "")
    try:
        if int(capabilities_hex, 16) != 0:
            raise SandboxProbeError("container has effective Linux capabilities")
    except ValueError as exc:
        raise SandboxProbeError("effective capability mask is invalid") from exc

    cgroup = Path("/sys/fs/cgroup")
    memory_limit = parse_positive_limit((cgroup / "memory.max").read_text(), "memory.max")
    cpu_cores = parse_cpu_quota((cgroup / "cpu.max").read_text())
    pids_limit = parse_positive_limit((cgroup / "pids.max").read_text(), "pids.max")

    try:
        connection = socket.create_connection(("1.1.1.1", 443), timeout=1.0)
    except OSError:
        outbound_network_blocked = True
    else:
        connection.close()
        raise SandboxProbeError("outbound network unexpectedly reachable")

    output_path = Path(output_dir).resolve(strict=True)
    with tempfile.NamedTemporaryFile(prefix=".sandbox-probe-", dir=output_path, delete=True) as probe:
        probe.write(b"m3-sandbox-output-mount-probe")
        probe.flush()
    report = {
        "effective_uid": effective_uid,
        "root_read_only": True,
        "tmp_noexec": True,
        "no_new_privileges": True,
        "effective_capabilities_hex": capabilities_hex.lower(),
        "outbound_network_blocked": outbound_network_blocked,
        "memory_limit_bytes": memory_limit,
        "cpu_quota_cores": cpu_cores,
        "pids_limit": pids_limit,
        "output_mount_writable": True,
    }
    validate_sandbox_report(report)
    return report
