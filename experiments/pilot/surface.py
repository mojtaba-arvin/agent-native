"""Build equivalent Agent Native pilot surfaces for the two disclosure arms.

This module controls only which tool schemas are initially visible. Both arms
use the same dispatch envelope and the same E-005 implementation.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

PILOT_ROOT = Path(__file__).resolve().parent
DEFAULT_CATALOG = PILOT_ROOT.parent / "e005" / "tools.json"
DISCOVERY_TOOL = "interface.describe"
DISPATCH_TOOL = "agent.invoke"


class SurfaceError(ValueError):
    """Raised when the source catalog cannot define a fair pilot surface."""


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def load_catalog(path: str | Path = DEFAULT_CATALOG) -> dict:
    try:
        catalog = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise SurfaceError("tool_catalog_unavailable_or_invalid") from error

    if not isinstance(catalog, dict) or catalog.get("protocol_version") != "0.1":
        raise SurfaceError("unsupported_tool_catalog")
    tools = catalog.get("tools")
    if not isinstance(tools, list) or not tools:
        raise SurfaceError("tool_catalog_must_be_nonempty")

    names: set[str] = set()
    for item in tools:
        if not isinstance(item, dict):
            raise SurfaceError("tool_catalog_entry_must_be_object")
        name, summary, mode, schema = (
            item.get("name"),
            item.get("summary"),
            item.get("mode"),
            item.get("input_schema"),
        )
        if not all(isinstance(value, str) and value for value in (name, summary, mode)):
            raise SurfaceError("tool_catalog_entry_missing_identity")
        if name in names:
            raise SurfaceError("duplicate_tool_name")
        names.add(name)
        if not isinstance(schema, dict) or schema.get("type") != "object":
            raise SurfaceError(f"tool_schema_must_be_object:{name}")
        if schema.get("additionalProperties") is not False:
            raise SurfaceError(f"tool_schema_must_reject_unknown_fields:{name}")

    if DISCOVERY_TOOL not in names:
        raise SurfaceError("discovery_tool_missing")
    return catalog


def build_dispatch_schema(tool_names: list[str]) -> dict:
    """The exact same dispatch schema is given to both experimental arms."""
    return {
        "type": "object",
        "required": ["request_id", "tool", "arguments"],
        "properties": {
            "request_id": {"type": "string", "minLength": 1, "maxLength": 128},
            "tool": {"type": "string", "enum": tool_names},
            "arguments": {"type": "object"},
        },
        "additionalProperties": False,
    }


def build_surface(arm: str, catalog: dict | None = None) -> dict:
    if arm not in {"progressive", "upfront"}:
        raise SurfaceError("unknown_disclosure_arm")
    catalog = load_catalog() if catalog is None else catalog
    tools = catalog["tools"]
    tool_names = [item["name"] for item in tools]

    visible_tools = []
    for item in tools:
        visible = {
            "name": item["name"],
            "summary": item["summary"],
            "mode": item["mode"],
        }
        # The discovery operation's own schema is common to both arms; without
        # it, the progressive arm could not request detailed schemas.
        if arm == "upfront" or item["name"] == DISCOVERY_TOOL:
            visible["input_schema"] = item["input_schema"]
        visible_tools.append(visible)

    return {
        "surface_version": 1,
        "dispatch": {
            "name": DISPATCH_TOOL,
            "summary": "Invoke one named E-005 operation using the shared request envelope.",
            "input_schema": build_dispatch_schema(tool_names),
        },
        "tools": visible_tools,
        "schema_discovery": {
            "tool": DISCOVERY_TOOL,
            "argument": "name",
            "instruction": (
                "Call interface.describe with the requested tool name to obtain "
                "its complete input schema."
            ),
        },
    }


def assert_fair_pair(progressive: dict, upfront: dict) -> None:
    if progressive.get("dispatch") != upfront.get("dispatch"):
        raise SurfaceError("dispatch_contract_mismatch")

    progressive_tools = progressive.get("tools")
    upfront_tools = upfront.get("tools")
    if not isinstance(progressive_tools, list) or not isinstance(upfront_tools, list):
        raise SurfaceError("surface_tools_must_be_lists")
    if len(progressive_tools) != len(upfront_tools):
        raise SurfaceError("tool_count_mismatch")

    for narrow, full in zip(progressive_tools, upfront_tools, strict=True):
        if any(narrow.get(field) != full.get(field) for field in ("name", "summary", "mode")):
            raise SurfaceError("tool_identity_or_description_mismatch")
        if full.get("input_schema") is None:
            raise SurfaceError("upfront_schema_missing")
        if narrow["name"] == DISCOVERY_TOOL:
            if narrow.get("input_schema") != full["input_schema"]:
                raise SurfaceError("discovery_schema_mismatch")
        elif "input_schema" in narrow:
            raise SurfaceError("progressive_arm_leaks_detailed_schema")

    if progressive.get("schema_discovery") != upfront.get("schema_discovery"):
        raise SurfaceError("schema_discovery_instruction_mismatch")


def surface_size_bytes(surface: dict) -> int:
    return len(_canonical_bytes(surface))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--arm", choices=("progressive", "upfront"), required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    surface = build_surface(args.arm)
    encoded = json.dumps(surface, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.write_text(encoded, encoding="utf-8")
    else:
        print(encoded, end="")


if __name__ == "__main__":
    main()
