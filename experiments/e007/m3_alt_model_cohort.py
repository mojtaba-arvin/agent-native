#!/usr/bin/env python3
"""Bootstrap and independently verify the M3-007 alternative CPU model cohort.

This utility never runs inference. Bootstrap records facts observed from a freshly
pulled Ollama store; verify compares a fresh store against the committed lock.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import shutil
import sys
from pathlib import Path
from typing import Any


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def model_manifest_path(model_dir: Path, tag: str) -> Path:
    model, version = tag.rsplit(":", 1)
    if "/" in model:
        namespace, name = model.split("/", 1)
    else:
        namespace, name = "library", model
    return model_dir / "manifests" / "registry.ollama.ai" / namespace / name / version


def observed_model(model_dir: Path, model: dict[str, Any], details: dict[str, Any]) -> dict[str, Any]:
    raw = model_manifest_path(model_dir, model["tag"]).read_bytes()
    manifest = json.loads(raw)
    detail = details.get("details", {})
    quantization = detail.get("quantization_level")
    if not isinstance(quantization, str) or quantization != model["quantization_expected"]:
        raise ValueError(f"quantization_mismatch:{model['tag']}:{quantization}")
    layers = [
        {
            "digest": item.get("digest"),
            "size": item.get("size"),
            "media_type": item.get("mediaType"),
        }
        for item in manifest.get("layers", [])
    ]
    if not layers or any(not item["digest"] or type(item["size"]) is not int for item in layers):
        raise ValueError(f"model_layers_invalid:{model['tag']}")
    return {
        "tier": model["tier"],
        "tag": model["tag"],
        "manifest_sha256": hashlib.sha256(raw).hexdigest(),
        "config_digest": manifest["config"]["digest"],
        "quantization_level": quantization,
        "parameter_size": detail.get("parameter_size"),
        "format": detail.get("format"),
        "family": detail.get("family"),
        "model_size_bytes": sum(
            item["size"] for item in layers if isinstance(item["media_type"], str) and "model" in item["media_type"]
        ),
        "layers": layers,
    }


def collect(args: argparse.Namespace) -> int:
    candidates = read_json(args.candidates)
    if candidates.get("schema_version") != 2 or candidates.get("status") != "bootstrap_pending":
        raise ValueError("alternative_candidate_manifest_invalid")
    disk = shutil.disk_usage(args.model_dir)
    mem_total = None
    for line in Path("/proc/meminfo").read_text(encoding="utf-8").splitlines():
        if line.startswith("MemTotal:"):
            mem_total = int(line.split()[1]) * 1024
            break
    runner = {
        "os": platform.platform(),
        "architecture": platform.machine(),
        "logical_cpu_count": os.cpu_count(),
        "memory_total_bytes": mem_total,
        "model_disk_total_bytes": disk.total,
        "model_disk_free_bytes": disk.free,
    }
    models = []
    for item in candidates["models"]:
        details = args.details_dir / (hashlib.sha256(item["tag"].encode()).hexdigest() + ".json")
        models.append(observed_model(args.model_dir, item, read_json(details)))
    if candidates["runtime"]["version"] not in args.ollama_version:
        raise ValueError("ollama_runtime_version_mismatch")
    observation = {
        "schema_version": 1,
        "cohort": candidates["cohort"],
        "source_sha": args.source_sha,
        "bootstrap_run_id": args.run_id,
        "observed_at": args.observed_at,
        "runtime": candidates["runtime"],
        "runtime_observed": args.ollama_version.strip(),
        "runner": runner,
        "models": models,
        "policy": candidates["policy"],
        "note": "Observed bootstrap evidence only; not a model qualification or trial result.",
    }
    write_json(args.output, observation)
    return 0


def verify(args: argparse.Namespace) -> int:
    candidates = read_json(args.candidates)
    lock = read_json(args.lock)
    if candidates.get("schema_version") != 2 or candidates.get("status") != "manifest_locked_not_qualified":
        raise ValueError("candidate_manifest_not_locked")
    if lock.get("schema_version") != 1 or lock.get("status") != "locked_not_qualified":
        raise ValueError("model_lock_status_invalid")
    lock_sha = hashlib.sha256(args.lock.read_bytes()).hexdigest()
    if lock.get("cohort") != candidates.get("cohort"):
        raise ValueError("model_lock_cohort_mismatch")
    if lock.get("runtime") != candidates.get("runtime"):
        raise ValueError("model_lock_runtime_mismatch")
    if candidates["runtime"]["version"] not in args.ollama_version:
        raise ValueError("ollama_runtime_version_mismatch")
    expected = {item["tag"]: item for item in lock.get("models", [])}
    declared = {item["tag"]: item for item in candidates.get("models", [])}
    if not expected or set(expected) != set(declared):
        raise ValueError("model_lock_candidate_set_mismatch")
    observed = []
    for tag, model in declared.items():
        current = observed_model(args.model_dir, model, read_json(
            args.details_dir / (hashlib.sha256(tag.encode()).hexdigest() + ".json")
        ))
        pin = expected[tag]
        for field in ("manifest_sha256", "config_digest", "quantization_level",
                      "parameter_size", "model_size_bytes", "layers"):
            if current[field] != pin.get(field) or model.get(field) != pin.get(field):
                raise ValueError(f"model_lock_mismatch:{tag}:{field}")
        observed.append(current)
    report = {
        "schema_version": 1,
        "status": "verified",
        "cohort": candidates["cohort"],
        "source_sha": args.source_sha,
        "verification_run_id": args.run_id,
        "model_lock_sha256": lock_sha,
        "network_during_verification": "disabled",
        "inference_executed": False,
        "models": observed,
    }
    write_json(args.output, report)
    return 0


def seal(args: argparse.Namespace) -> int:
    candidates = read_json(args.candidates)
    observation = read_json(args.observation)
    if observation.get("cohort") != candidates.get("cohort"):
        raise ValueError("bootstrap_observation_cohort_mismatch")
    if observation.get("source_sha") != args.source_sha:
        raise ValueError("bootstrap_observation_source_sha_mismatch")
    if not observation.get("models") or len(observation["models"]) != len(candidates["models"]):
        raise ValueError("bootstrap_observation_model_count_mismatch")
    by_tag = {item["tag"]: item for item in observation["models"]}
    updated = dict(candidates)
    updated["status"] = "manifest_locked_not_qualified"
    updated["bootstrap_provenance"] = {
        "run_id": observation["bootstrap_run_id"],
        "source_sha": observation["source_sha"],
        "observation_sha256": hashlib.sha256(args.observation.read_bytes()).hexdigest(),
        "observed_at": observation["observed_at"],
    }
    updated["models"] = []
    for item in candidates["models"]:
        observed = by_tag[item["tag"]]
        updated["models"].append({**item, **{
            key: observed[key] for key in (
                "manifest_sha256", "config_digest", "quantization_level",
                "parameter_size", "format", "family", "model_size_bytes", "layers"
            )
        }})
    lock = {
        "schema_version": 1,
        "status": "locked_not_qualified",
        "cohort": candidates["cohort"],
        "provenance": updated["bootstrap_provenance"],
        "runtime": observation["runtime"],
        "runtime_observed": observation["runtime_observed"],
        "runner": observation["runner"],
        "models": observation["models"],
        "policy": observation["policy"],
    }
    write_json(args.candidates_output, updated)
    write_json(args.lock_output, lock)
    return 0


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser()
    sub = root.add_subparsers(dest="command", required=True)
    for command in ("collect", "verify"):
        p = sub.add_parser(command)
        p.add_argument("--candidates", type=Path, required=True)
        p.add_argument("--model-dir", type=Path, required=True)
        p.add_argument("--details-dir", type=Path, required=True)
        p.add_argument("--output", type=Path, required=True)
        p.add_argument("--source-sha", required=True)
        p.add_argument("--run-id", required=True)
        p.add_argument("--ollama-version", required=True)
        if command == "collect":
            p.add_argument("--observed-at", required=True)
        else:
            p.add_argument("--lock", type=Path, required=True)
    p = sub.add_parser("seal")
    p.add_argument("--candidates", type=Path, required=True)
    p.add_argument("--observation", type=Path, required=True)
    p.add_argument("--source-sha", required=True)
    p.add_argument("--candidates-output", type=Path, required=True)
    p.add_argument("--lock-output", type=Path, required=True)
    return root


def main() -> int:
    args = parser().parse_args()
    return collect(args) if args.command == "collect" else verify(args) if args.command == "verify" else seal(args)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (KeyError, OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
        print(f"m3_alt_model_cohort_error: {exc}", file=sys.stderr)
        raise SystemExit(2)
