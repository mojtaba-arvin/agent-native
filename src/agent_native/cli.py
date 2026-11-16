"""CLI entry point. Machine-readable output is the default for inspection."""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sys
from pathlib import Path
from typing import Any

from . import __version__
from .manifest import MANIFEST_NAME, ManifestError, load_manifest, validate_manifest

TEMPLATE_MANIFEST = {
    "schema_version": "1",
    "name": "example-service",
    "version": "0.1.0",
    "entrypoint": "main:app",
    "operations": [
        {"id": "health.read", "method": "GET", "path": "/health", "summary": "Service health"},
        {"id": "items.list", "method": "GET", "path": "/items", "summary": "List items"},
    ],
}
TEMPLATE_MAIN = '''from fastapi import FastAPI

app = FastAPI(title="example-service", version="0.1.0")


@app.get("/health", tags=["system"])
async def health():
    return {"status": "ok"}


@app.get("/items", tags=["items"])
async def list_items():
    return {"items": []}
'''


def _emit(payload: Any, as_json: bool = True) -> None:
    if as_json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(payload)


def command_init(args: argparse.Namespace) -> int:
    target = Path(args.path).resolve()
    try:
        validate_manifest({**TEMPLATE_MANIFEST, "name": args.name})
    except ManifestError as exc:
        _emit({"ok": False, "error": str(exc)})
        return 2
    if target.exists() and (not target.is_dir() or any(target.iterdir())):
        _emit({"ok": False, "error": "target directory is not empty", "path": str(target)})
        return 2
    target.mkdir(parents=True, exist_ok=True)
    (target / MANIFEST_NAME).write_text(json.dumps({**TEMPLATE_MANIFEST, "name": args.name}, indent=2) + "\n", encoding="utf-8")
    (target / "main.py").write_text(TEMPLATE_MAIN.replace("example-service", args.name), encoding="utf-8")
    (target / "requirements.txt").write_text("fastapi>=0.115,<1\nuvicorn[standard]>=0.30,<1\n", encoding="utf-8")
    _emit({"ok": True, "created": [MANIFEST_NAME, "main.py", "requirements.txt"], "next": ["python -m pip install -r requirements.txt", "agent-native validate", "agent-native verify", "agent-native inspect"]})
    return 0


def _project(root_arg: str) -> tuple[Path, dict[str, Any]]:
    root = Path(root_arg).resolve()
    return root, load_manifest(root)


def command_inspect(args: argparse.Namespace) -> int:
    try:
        root, manifest = _project(args.path)
    except ManifestError as exc:
        _emit({"ok": False, "error": str(exc)})
        return 2
    _emit({
        "contract": "agent-native.service/v1",
        "framework_version": __version__,
        "service": manifest,
        "project_root": str(root),
        "agent_operations": [
            {"id": "project.inspect", "command": "agent-native inspect", "effect": "read-only"},
            {"id": "project.validate", "command": "agent-native validate", "effect": "read-only"},
            {"id": "project.verify", "command": "agent-native verify", "effect": "executes local Python imports"},
        ],
    })
    return 0


def command_validate(args: argparse.Namespace) -> int:
    try:
        root, manifest = _project(args.path)
    except ManifestError as exc:
        _emit({"ok": False, "valid": False, "errors": [str(exc)]})
        return 2
    _emit({"ok": True, "valid": True, "service": manifest["name"], "operation_count": len(manifest["operations"]), "root": str(root)})
    return 0


def command_verify(args: argparse.Namespace) -> int:
    try:
        root, manifest = _project(args.path)
    except ManifestError as exc:
        _emit({"ok": False, "verified": False, "stage": "manifest", "error": str(exc)})
        return 2

    compile_errors = []
    for source in sorted(root.rglob("*.py")):
        if any(part in {".venv", "venv", "__pycache__", ".git"} for part in source.parts):
            continue
        try:
            compile(source.read_text(encoding="utf-8"), str(source), "exec")
        except (OSError, SyntaxError) as exc:
            compile_errors.append({"file": str(source.relative_to(root)), "error": f"{type(exc).__name__}: {exc}"})
    if compile_errors:
        _emit({"ok": False, "verified": False, "stage": "compile", "errors": compile_errors})
        return 1

    module_name, attribute = manifest["entrypoint"].split(":", 1)
    module_path = root / (module_name.replace(".", os.sep) + ".py")
    if not module_path.is_file():
        _emit({"ok": False, "verified": False, "stage": "entrypoint", "error": f"Missing entrypoint module: {module_path.relative_to(root)}"})
        return 1
    try:
        spec = importlib.util.spec_from_file_location(f"_agent_native_verify_{module_name}", module_path)
        if spec is None or spec.loader is None:
            raise RuntimeError("Cannot create module loader")
        module = importlib.util.module_from_spec(spec)
        sys.path.insert(0, str(root))
        try:
            spec.loader.exec_module(module)
        finally:
            sys.path.pop(0)
        app = getattr(module, attribute)
    except Exception as exc:
        _emit({"ok": False, "verified": False, "stage": "import", "error": f"{type(exc).__name__}: {exc}"})
        return 1

    routes = getattr(app, "routes", None)
    if routes is None:
        _emit({"ok": False, "verified": False, "stage": "entrypoint", "error": "Entrypoint is not an ASGI application with a routes collection"})
        return 1
    actual = {(method, route.path) for route in routes for method in (getattr(route, "methods", None) or set())}
    missing = [{"method": op["method"], "path": op["path"], "id": op["id"]} for op in manifest["operations"] if (op["method"], op["path"]) not in actual]
    if missing:
        _emit({"ok": False, "verified": False, "stage": "contract", "missing_routes": missing})
        return 1
    _emit({"ok": True, "verified": True, "checks": ["manifest", "python_compile", "entrypoint_import", "declared_routes"], "service": manifest["name"], "route_count": len(manifest["operations"])})
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="agent-native", description="Machine-actionable backend service tooling")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)
    init = sub.add_parser("init", help="create a runnable FastAPI service")
    init.add_argument("name", help="service name (lowercase kebab-case)")
    init.add_argument("--path", default=".", help="target directory")
    init.set_defaults(func=command_init)
    for name, handler, help_text in (
        ("inspect", command_inspect, "emit project contract and agent operations as JSON"),
        ("validate", command_validate, "validate the service manifest"),
        ("verify", command_verify, "compile, import, and check declared routes"),
    ):
        item = sub.add_parser(name, help=help_text)
        item.add_argument("--path", default=".", help="project directory")
        item.set_defaults(func=handler)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    raise SystemExit(args.func(args))


if __name__ == "__main__":
    main()
