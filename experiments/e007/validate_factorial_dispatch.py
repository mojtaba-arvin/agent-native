#!/usr/bin/env python3
"""Validate a matched E-007 factorial dispatch before any model request."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


EXPECTED_SETTINGS = {
    "arm": "upfront",
    "temperature": 0,
    "top_p": 1,
    "seed": 42,
    "num_ctx": 16384,
    "num_predict": 2048,
    "max_input_tokens": 120000,
    "max_output_tokens": 6000,
    "max_tool_calls": 20,
    "max_wall_seconds": 3000,
}
EXPECTED_CELLS = {
    ("snapshot", "per_operation"),
    ("delta", "per_operation"),
    ("snapshot", "upfront_full"),
    ("delta", "upfront_full"),
}
MANIFEST_FIELDS = {
    "schema_version", "dispatch_id", "status", "model_id", "repetitions",
    "arm", "model_settings", "cases", "no_apply", "purpose",
}
CASE_ENTRY_FIELDS = {"case_path", "eval_id", "proposal_mode", "base_disclosure"}


class DispatchValidationError(ValueError):
    pass


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise DispatchValidationError(f"duplicate_json_key:{key}")
        result[key] = value
    return result


def _read_json(path: Path) -> dict:
    try:
        value = json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=lambda value: (_ for _ in ()).throw(
                DispatchValidationError(f"non_finite_json:{value}")
            ),
        )
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise DispatchValidationError(f"invalid_json_file:{path.name}") from error
    if not isinstance(value, dict):
        raise DispatchValidationError(f"json_object_required:{path.name}")
    return value


def validate_dispatch(root: Path, manifest_path: Path) -> tuple[dict, list[dict]]:
    root = root.expanduser().resolve()
    manifest_path = manifest_path.expanduser().resolve()
    if root not in manifest_path.parents or not manifest_path.is_file():
        raise DispatchValidationError("dispatch_manifest_outside_or_missing")
    manifest = _read_json(manifest_path)
    if set(manifest) != MANIFEST_FIELDS or manifest.get("schema_version") != 2:
        raise DispatchValidationError("dispatch_manifest_schema_invalid")
    if manifest.get("status") != "ready_for_manual_dispatch":
        raise DispatchValidationError("dispatch_manifest_not_ready")
    if manifest.get("no_apply") is not True:
        raise DispatchValidationError("dispatch_no_apply_policy_required")
    if (
        manifest.get("model_id") != "qwen3:8b"
        or manifest.get("repetitions") != 1
        or manifest.get("arm") != "upfront"
        or manifest.get("model_settings") != EXPECTED_SETTINGS
    ):
        raise DispatchValidationError("dispatch_model_or_budget_changed")

    cases = manifest.get("cases")
    if not isinstance(cases, list) or len(cases) != 4:
        raise DispatchValidationError("dispatch_must_contain_exactly_four_factorial_cells")

    seen: set[tuple[str, str]] = set()
    shared_identity = None
    rows = []
    for item in cases:
        if not isinstance(item, dict) or set(item) != CASE_ENTRY_FIELDS:
            raise DispatchValidationError("dispatch_case_entry_invalid")
        cell = (item["proposal_mode"], item["base_disclosure"])
        if cell not in EXPECTED_CELLS or cell in seen:
            raise DispatchValidationError("dispatch_factorial_cell_invalid_or_duplicate")
        seen.add(cell)

        relative = Path(item["case_path"])
        if relative.is_absolute() or ".." in relative.parts:
            raise DispatchValidationError("dispatch_case_path_invalid")
        case_path = (root / relative).resolve()
        if root not in case_path.parents or not case_path.is_file():
            raise DispatchValidationError("dispatch_case_file_missing_or_outside_repository")
        case = _read_json(case_path)
        expected_task_file = (
            "experiments/e009/AGENT_TASK_DELTA.md"
            if item["proposal_mode"] == "delta"
            else "experiments/e009/AGENT_TASK.md"
        )
        if (
            case.get("eval_id") != item["eval_id"]
            or case.get("proposal_mode") != item["proposal_mode"]
            or case.get("base_disclosure") != item["base_disclosure"]
            or case.get("model_id") != manifest["model_id"]
            or case.get("repetitions") != manifest["repetitions"]
            or case.get("model_settings") != EXPECTED_SETTINGS
            or case.get("task_file") != expected_task_file
        ):
            raise DispatchValidationError("dispatch_case_identity_or_settings_mismatch")
        shared = (
            case.get("task_id"), case.get("service_id"), case.get("candidate_id"),
            case.get("expected_operation"), case.get("scorers"), case.get("budget"),
        )
        if shared_identity is None:
            shared_identity = shared
        elif shared != shared_identity:
            raise DispatchValidationError("factorial_cases_are_not_matched")
        budget = case.get("budget")
        if not isinstance(budget, dict) or (
            budget.get("max_total_input_tokens") != EXPECTED_SETTINGS["max_input_tokens"]
            or budget.get("max_total_output_tokens") != EXPECTED_SETTINGS["max_output_tokens"]
            or budget.get("max_total_wall_seconds") != EXPECTED_SETTINGS["max_wall_seconds"]
        ):
            raise DispatchValidationError("factorial_case_budget_mismatch")
        rows.append({
            "case_path": item["case_path"],
            "eval_id": item["eval_id"],
            "proposal_mode": item["proposal_mode"],
            "base_disclosure": item["base_disclosure"],
            "settings": EXPECTED_SETTINGS,
            "repetitions": manifest["repetitions"],
        })

    if seen != EXPECTED_CELLS:
        raise DispatchValidationError("factorial_cells_incomplete")
    return manifest, rows


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument(
        "--manifest", type=Path,
        default=Path(__file__).resolve().parent / "dispatch.json",
    )
    parser.add_argument("--format", choices=("json", "tsv"), default="json")
    args = parser.parse_args()
    manifest, rows = validate_dispatch(args.root, args.manifest)
    if args.format == "tsv":
        for row in rows:
            settings = row["settings"]
            fields = [
                row["case_path"], row["eval_id"], row["proposal_mode"],
                row["base_disclosure"], settings["arm"], str(row["repetitions"]),
                str(settings["temperature"]), str(settings["top_p"]), str(settings["seed"]),
                str(settings["num_ctx"]), str(settings["num_predict"]),
                str(settings["max_input_tokens"]), str(settings["max_output_tokens"]),
                str(settings["max_tool_calls"]), str(settings["max_wall_seconds"]),
            ]
            print("\t".join(fields))
    else:
        print(json.dumps({
            "dispatch_id": manifest["dispatch_id"],
            "status": manifest["status"],
            "validated_cells": rows,
            "model_id": manifest["model_id"],
            "no_apply": manifest["no_apply"],
        }, ensure_ascii=False, sort_keys=True, indent=2))


if __name__ == "__main__":
    main()
