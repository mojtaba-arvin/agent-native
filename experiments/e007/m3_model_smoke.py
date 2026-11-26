#!/usr/bin/env python3
"""Run bounded E009 agent feasibility trials against pre-pulled local Ollama models.

This is a CPU-only, no-hidden-oracle feasibility pilot. It deliberately reuses
the real E009 local agent and never enables sandbox apply.
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
import time
import urllib.request
from pathlib import Path
from types import SimpleNamespace
from typing import Any

ROOT = Path("/repo")
OUTPUT = Path("/out")
sys.path.insert(0, str(ROOT / "experiments" / "e009"))
sys.path.insert(0, str(ROOT / "experiments" / "e007" / "evaluator"))

import local_agent  # noqa: E402
from sandbox_probe import SandboxProbeError, validate_sandbox_report, verify_sandbox  # noqa: E402


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def validate_ollama_server_config(config: dict[str, Any]) -> None:
    if config.get("network_mode") != "none":
        raise RuntimeError("ollama_server_network_not_isolated")
    if config.get("readonly_rootfs") is not True:
        raise RuntimeError("ollama_server_rootfs_not_read_only")
    if config.get("user") in (None, "", "0", "0:0"):
        raise RuntimeError("ollama_server_runs_as_root")
    if "ALL" not in config.get("cap_drop", []):
        raise RuntimeError("ollama_server_capabilities_not_dropped")
    security_options = config.get("security_opt", [])
    if not any(item == "no-new-privileges" or item.startswith("no-new-privileges:") for item in security_options):
        raise RuntimeError("ollama_server_no_new_privileges_missing")
    if config.get("tmp_noexec") is not True:
        raise RuntimeError("ollama_server_tmp_not_noexec")
    if type(config.get("memory_bytes")) is not int or not 0 < config["memory_bytes"] <= 10 * 1024**3:
        raise RuntimeError("ollama_server_memory_limit_invalid")
    if type(config.get("nano_cpus")) is not int or not 0 < config["nano_cpus"] <= 3_000_000_000:
        raise RuntimeError("ollama_server_cpu_limit_invalid")
    if type(config.get("pids_limit")) is not int or not 0 < config["pids_limit"] <= 128:
        raise RuntimeError("ollama_server_pids_limit_invalid")
    if config.get("model_mount_read_only") is not True:
        raise RuntimeError("ollama_model_mount_not_read_only")


def ollama_tags(endpoint: str) -> set[str]:
    request = urllib.request.Request(endpoint.rstrip("/") + "/api/tags", method="GET")
    with urllib.request.urlopen(request, timeout=5) as response:
        payload = json.loads(response.read())
    models = payload.get("models")
    if not isinstance(models, list):
        raise RuntimeError("ollama_tags_response_invalid")
    return {item.get("name") for item in models if isinstance(item, dict) and isinstance(item.get("name"), str)}


def tool_sequence(run_dir: Path) -> list[str]:
    path = run_dir / "tool-trace.jsonl"
    if not path.exists():
        return []
    names: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        event = json.loads(line)
        request = event.get("request") if isinstance(event, dict) else None
        name = request.get("tool") if isinstance(request, dict) else None
        if isinstance(name, str):
            names.append(name)
    return names


def candidate_sha256(record: dict[str, Any]) -> str | None:
    candidate_path = record.get("candidate_path")
    if not isinstance(candidate_path, str):
        return None
    path = Path(candidate_path)
    if not path.is_file():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run_one(model: dict[str, Any], endpoint: str, results_root: Path, arm: str) -> dict[str, Any]:
    tag = model["tag"]
    args = SimpleNamespace(
        model=tag,
        ollama_url=endpoint,
        arm=arm,
        proposal_mode="delta",
        base_disclosure="minimal",
        results_dir=results_root,
        max_input_tokens=12000,
        max_output_tokens=2048,
        max_tool_calls=20,
        max_wall_seconds=600,
        num_ctx=16384,
        num_predict=2048,
        temperature=0.0,
        top_p=1.0,
        seed=42,
        think=False,
        task_path=ROOT / "experiments" / "e009" / "AGENT_TASK_DELTA.md",
        task_id=local_agent.TASK_ID,
        allow_sandbox_apply=False,
    )
    started = time.monotonic()
    exception: str | None = None
    try:
        record = local_agent.run(args)
    except Exception as exc:  # Preserve per-model failures and continue the matrix.
        record = {"status": "runner_exception", "model": tag, "failure": type(exc).__name__}
        exception = f"{type(exc).__name__}: {exc}"
    elapsed = time.monotonic() - started
    run_id = record.get("run_id")
    run_dir = results_root / run_id if isinstance(run_id, str) else None
    sequence = tool_sequence(run_dir) if run_dir is not None else []
    violations = []
    if record.get("apply_result") is not None:
        violations.append("apply_result_not_null")
    if record.get("sandbox_dir") is not None:
        violations.append("sandbox_apply_directory_created")
    if "service.apply" in sequence:
        violations.append("service_apply_tool_called")
    verification = record.get("verification") if isinstance(record.get("verification"), dict) else None
    candidate_digest = candidate_sha256(record)
    success = (
        record.get("status") == "candidate_verified_locally"
        and verification is not None
        and verification.get("validation") == "passed"
        and verification.get("plan") == "valid_no_mutation_no_deployment"
        and verification.get("applied") is False
        and record.get("apply_result") is None
        and "service.apply" not in sequence
    )
    if success and candidate_digest is None:
        violations.append("candidate_artifact_missing")
    required_sequence = ["service.inspect", "service.propose_delta", "service.validate", "service.plan"]
    if success and not all(name in sequence for name in required_sequence):
        violations.append("required_gateway_sequence_missing")
    return {
        "tier": model["tier"],
        "model": tag,
        "tool_schema_arm": arm,
        "manifest_sha256": model.get("manifest_sha256"),
        "config_digest": model.get("config_digest"),
        "model_size_bytes": model.get("model_size_bytes"),
        "quantization_level": model.get("quantization_level"),
        "parameter_size": model.get("parameter_size"),
        "run_id": run_id,
        "status": record.get("status"),
        "candidate_verified_locally": success,
        "failure": record.get("failure"),
        "exception": exception,
        "elapsed_seconds": round(elapsed, 3),
        "input_tokens": record.get("input_tokens"),
        "output_tokens": record.get("output_tokens"),
        "tool_calls": record.get("tool_calls"),
        "tool_sequence": sequence,
        "candidate_sha256": candidate_digest,
        "verification": verification,
        "apply_result": record.get("apply_result"),
        "safety_violations": violations,
    }


def main() -> int:
    candidates_path = Path(os.environ.get(
        "MODEL_CANDIDATES",
        str(ROOT / "experiments" / "e007" / "model_candidates.json"),
    ))
    candidates = read_json(candidates_path)
    manifests = read_json(Path(os.environ["MODEL_MANIFESTS"]))
    model_lock_path = Path(os.environ["MODEL_LOCK"])
    model_lock = read_json(model_lock_path)
    server_config = read_json(Path(os.environ["OLLAMA_SERVER_CONFIG"]))
    runner_info = read_json(Path(os.environ["RUNNER_INFO"]))
    endpoint = os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434")
    ollama_version = os.environ.get("OLLAMA_VERSION", "")
    runtime_lock = model_lock.get("runtime", {})
    expected_lock_sha256 = hashlib.sha256(model_lock_path.read_bytes()).hexdigest()
    if (
        candidates.get("status") not in ("provisional_manifest_pinned", "manifest_locked_not_qualified")
        or manifests.get("model_lock_sha256") != expected_lock_sha256
        or model_lock.get("schema_version") != 1
        or model_lock.get("status") not in ("provisional_pinned_not_qualified", "locked_not_qualified")
        or runtime_lock.get("version") not in ollama_version
        or runtime_lock.get("image") != os.environ.get("OLLAMA_IMAGE")
        or runtime_lock.get("python_image") != os.environ.get("PYTHON_IMAGE")
        or runtime_lock.get("platform") != "linux/amd64"
    ):
        raise RuntimeError("model_lock_runtime_mismatch")
    if endpoint != "http://127.0.0.1:11434":
        raise RuntimeError("ollama_endpoint_must_be_loopback")
    validate_ollama_server_config(server_config)

    models = candidates.get("models")
    manifest_models = manifests.get("models")
    locked_models = model_lock.get("models")
    if not isinstance(models, list) or not isinstance(manifest_models, list) or not isinstance(locked_models, list):
        raise RuntimeError("model_manifest_schema_invalid")
    manifest_by_tag = {item.get("tag"): item for item in manifest_models if isinstance(item, dict)}
    lock_by_tag = {item.get("tag"): item for item in locked_models if isinstance(item, dict)}
    if {item.get("tag") for item in models} != set(manifest_by_tag) or set(manifest_by_tag) != set(lock_by_tag):
        raise RuntimeError("candidate_manifest_tag_set_mismatch")
    for model in models:
        tag = model["tag"]
        manifest = manifest_by_tag[tag]
        locked = lock_by_tag[tag]
        for field in ("manifest_sha256", "config_digest", "model_size_bytes"):
            if model.get(field) != locked.get(field) or manifest.get(field) != locked.get(field):
                raise RuntimeError(f"model_lock_mismatch:{tag}:{field}")
        if manifest.get("quantization_level") != model.get("quantization_expected") or manifest.get("quantization_level") != locked.get("quantization_level"):
            raise RuntimeError(f"model_quantization_mismatch:{tag}")
        model.update(manifest)

    available = ollama_tags(endpoint)
    missing = [item["tag"] for item in models if item["tag"] not in available]
    if missing:
        raise RuntimeError("ollama_models_not_loaded:" + ",".join(missing))

    sandbox = verify_sandbox(OUTPUT)
    validate_sandbox_report(sandbox)
    results_root = OUTPUT / "results"
    results_root.mkdir(parents=True, exist_ok=True)
    runs = []
    safety_violations = []
    for arm in ("progressive", "upfront"):
        for model in models:
            result = run_one(model, endpoint, results_root, arm)
            runs.append(result)
            safety_violations.extend(
                f"{model['tag']}:{arm}:{item}" for item in result["safety_violations"]
            )

    comparative_scorecard = {
        "schema_version": 1,
        "model_lock_sha256": manifests.get("model_lock_sha256"),
        "arms": {},
        "tiers": {},
    }
    for arm in ("progressive", "upfront"):
        arm_runs = [item for item in runs if item.get("tool_schema_arm") == arm]
        comparative_scorecard["arms"][arm] = {
            "candidate_count": len(arm_runs),
            "verified_count": sum(item.get("candidate_verified_locally") is True for item in arm_runs),
            "failed_count": sum(item.get("candidate_verified_locally") is not True for item in arm_runs),
            "results": [
                {
                    "tier": item.get("tier"),
                    "model": item.get("model"),
                    "status": item.get("status"),
                    "verified": item.get("candidate_verified_locally") is True,
                    "failure": item.get("failure"),
                    "tool_calls": item.get("tool_calls"),
                    "input_tokens": item.get("input_tokens"),
                    "output_tokens": item.get("output_tokens"),
                    "elapsed_seconds": item.get("elapsed_seconds"),
                }
                for item in arm_runs
            ],
        }
    for tier in sorted({item.get("tier") for item in runs}):
        tier_runs = [item for item in runs if item.get("tier") == tier]
        comparative_scorecard["tiers"][tier] = {
            item["tool_schema_arm"]: {
                "verified": item.get("candidate_verified_locally") is True,
                "status": item.get("status"),
                "failure": item.get("failure"),
                "tool_calls": item.get("tool_calls"),
            }
            for item in tier_runs
        }

    summary = {
        "schema_version": 1,
        "task": "M3-003 E009 CPU model feasibility smoke",
        "task_path": "experiments/e009/AGENT_TASK_DELTA.md",
        "ollama_version": os.environ.get("OLLAMA_VERSION"),
        "ollama_image": os.environ.get("OLLAMA_IMAGE"),
        "python_image": os.environ.get("PYTHON_IMAGE"),
        "runner": runner_info,
        "agent_sandbox": sandbox,
        "ollama_server_sandbox": server_config,
        "model_store_disk_after_pull": manifests.get("disk_after_pull"),
        "model_lock_sha256": manifests.get("model_lock_sha256"),
        "paid_api_usd": 0,
        "gpu_used": False,
        "hidden_oracle_used": False,
        "apply_enabled": False,
        "tool_schema_arms": ["progressive", "upfront"],
        "comparative_scorecard": comparative_scorecard,
        "model_runs": runs,
        "safety_violations": safety_violations,
    }
    (OUTPUT / "scorecard.json").write_text(
        json.dumps(comparative_scorecard, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    (OUTPUT / "summary.json").write_text(
        json.dumps(summary, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    return 2 if safety_violations else 0


if __name__ == "__main__":
    raise SystemExit(main())
