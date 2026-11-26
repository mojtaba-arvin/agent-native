"""Unified, side-effect-conscious developer CLI for the agent_native package."""

from __future__ import annotations

import argparse
import importlib.resources
import json
import os
import re
import sys
from pathlib import Path
from urllib.parse import urlsplit


class CLIError(Exception):
    def __init__(self, code: str, message: str, exit_code: int = 3, *, details: dict | None = None):
        super().__init__(message)
        self.code = code
        self.exit_code = exit_code
        self.details = details or {}


class JSONArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        payload = {"error": {"code": "invalid_arguments", "message": message}}
        print(json.dumps(payload, sort_keys=True), file=sys.stderr)
        self.exit(2)


def _emit(value: dict) -> None:
    print(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False))


def _error(error: CLIError) -> int:
    payload = {"error": {"code": error.code, "message": str(error), **error.details}}
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True), file=sys.stderr)
    return error.exit_code


def _diagnostic_hint(code: str) -> str:
    hints = {
        "AN001": "Check the character at the reported location; service contracts use the documented Agent Native DSL tokens.",
        "AN002": "Compare the declaration with docs/IR_V1.md and add the missing or expected token.",
        "AN003": "Use the required token kind; identifiers, strings, and punctuation are distinct.",
        "AN005": "Give each operation a unique name.",
        "AN016": "Give each record type a unique name.",
        "AN020": "Declare the referenced record type or use a supported built-in type.",
        "AN007": "Declare at least one operation in the service.",
    }
    return hints.get(code, "Review the reported source location and the v1 contract in docs/IR_V1.md.")


def _read_service(path: str):
    from .ir import Diagnostic, Parser

    service_path = Path(path).expanduser()
    try:
        source = service_path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as error:
        raise CLIError("service_file_unreadable", f"cannot read service file: {service_path}") from error
    try:
        ir = Parser(source).parse()
    except Diagnostic as error:
        raise CLIError(
            error.code,
            error.message,
            details={
                "diagnostics": [{
                    "code": error.code,
                    "message": error.message,
                    "source_span": {
                        "line": error.token.line,
                        "column": error.token.column,
                    },
                    "fix_hint": _diagnostic_hint(error.code),
                }]
            },
        ) from error
    return service_path, ir


def _schema_files() -> dict[str, object]:
    directory = importlib.resources.files("agent_native").joinpath("schemas")
    try:
        files = {
            item.name.removesuffix(".schema.json"): item
            for item in directory.iterdir()
            if item.is_file() and item.name.endswith(".schema.json")
        }
    except (FileNotFoundError, NotADirectoryError) as error:
        raise CLIError(
            "schema_catalog_unavailable",
            "packaged JSON Schema resources are missing; reinstall the agent-native package",
        ) from error
    return dict(sorted(files.items()))


def command_schema(args: argparse.Namespace) -> int:
    schemas = _schema_files()
    if args.name is None or args.list:
        _emit({
            "status": "available",
            "schemas": [
                {"name": name, "resource": f"agent_native/schemas/{name}.schema.json"}
                for name in schemas
            ],
        })
        return 0
    if not re.fullmatch(r"[a-z0-9-]+", args.name):
        raise CLIError("invalid_schema_name", "schema name must contain lowercase ASCII letters, digits, and hyphens")
    resource = schemas.get(args.name)
    if resource is None:
        raise CLIError(
            "schema_not_found",
            f"unknown schema {args.name!r}",
            details={"available_schemas": list(schemas)},
        )
    try:
        value = json.loads(resource.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise CLIError("schema_resource_invalid", f"packaged schema {args.name!r} cannot be read as JSON") from error
    _emit({"name": args.name, "schema": value})
    return 0


def _route_pattern(template: str) -> re.Pattern[str]:
    parts = re.split(r"(\{[A-Za-z_][A-Za-z0-9_]*\})", template)
    pattern = []
    for part in parts:
        if part.startswith("{") and part.endswith("}"):
            pattern.append(f"(?P<{part[1:-1]}>[^/]+)")
        else:
            pattern.append(re.escape(part))
    return re.compile("^" + "".join(pattern) + "$")


def command_check(args: argparse.Namespace) -> int:
    _path, ir = _read_service(args.service)
    _emit({
        "status": "valid",
        "service": ir["service"]["name"],
        "version": ir["service"]["version"],
        "operations": len(ir["operations"]),
        "service_path": args.service,
    })
    return 0


def command_diagnose(args: argparse.Namespace) -> int:
    path, ir = _read_service(args.service)
    _emit({
        "status": "valid",
        "service": ir["service"]["name"],
        "service_path": str(path),
        "diagnostics": [],
    })
    return 0


def command_inspect(args: argparse.Namespace) -> int:
    _path, ir = _read_service(args.service)
    _emit(ir)
    return 0


def command_run(args: argparse.Namespace) -> int:
    _path, ir = _read_service(args.service)
    if not args.dry_run:
        raise CLIError(
            "runtime_handlers_not_configured",
            "M1 exposes contract routing in --dry-run mode only; register trusted handlers before execution.",
            4,
        )
    parsed = urlsplit(args.path)
    if not parsed.path.startswith("/"):
        raise CLIError("invalid_request_path", "request path must start with '/'")
    method = args.method.upper()
    matched = []
    for operation in ir["operations"]:
        values = _route_pattern(operation["path"]).fullmatch(parsed.path)
        if values:
            matched.append((operation, values.groupdict()))
            if operation["method"] == method:
                _emit({
                    "status": "planned",
                    "execution_started": False,
                    "side_effects": False,
                    "service": ir["service"]["name"],
                    "operation": operation["name"],
                    "method": method,
                    "path": parsed.path,
                    "path_parameters": values.groupdict(),
                })
                return 0
    if matched:
        raise CLIError("method_not_allowed", "path exists but no operation accepts this method")
    raise CLIError("route_not_found", "no service operation matches the requested path")


def command_worker(args: argparse.Namespace) -> int:
    queue_path = Path(args.queue).expanduser()
    try:
        raw_lines = queue_path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError) as error:
        raise CLIError("queue_file_unreadable", f"cannot read queue file: {queue_path}") from error
    queued = 0
    total = 0
    for line_number, line in enumerate(raw_lines, 1):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError as error:
            raise CLIError("invalid_queue_json", f"invalid JSON on queue line {line_number}") from error
        if not isinstance(record, dict) or not isinstance(record.get("task_id"), str) or not isinstance(record.get("state"), str):
            raise CLIError("invalid_queue_record", f"queue line {line_number} requires string task_id and state")
        total += 1
        if record["state"] in {"queued", "pending"}:
            queued += 1
    _emit({
        "status": "planned",
        "execution_started": False,
        "service_id": args.service_id,
        "queue_path": args.queue,
        "records": total,
        "queued_records": queued,
    })
    return 0


def _safe_server_error(error: Exception) -> str:
    message = str(error)
    for name in ("AGENT_NATIVE_POSTGRES_DSN", "AGENT_NATIVE_TOKEN_SIGNING_KEY_HEX"):
        secret = os.environ.get(name)
        if secret:
            message = message.replace(secret, "<redacted>")
    message = re.sub(
        r"(?i)(postgres(?:ql)?://)[^/@\s]+@",
        r"\1<redacted>@",
        message,
    )
    message = re.sub(
        r"(?i)(password|token_signing_key_hex)=([^\s,]+)",
        r"\1=<redacted>",
        message,
    )
    return message[:240]


def command_serve(args: argparse.Namespace) -> int:
    try:
        from .server import run_server
        return run_server(args)
    except Exception as error:
        raise CLIError(
            "server_start_failed",
            f"server initialization failed ({type(error).__name__})",
            4,
            details={"cause": _safe_server_error(error)},
        ) from error


def command_audit(args: argparse.Namespace) -> int:
    events_path = Path(args.events).expanduser()
    try:
        raw_lines = events_path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError) as error:
        raise CLIError("audit_file_unreadable", f"cannot read audit file: {events_path}") from error
    allow = deny = total = 0
    for line_number, line in enumerate(raw_lines, 1):
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError as error:
            raise CLIError("invalid_audit_json", f"invalid JSON on audit line {line_number}") from error
        if not isinstance(event, dict) or not isinstance(event.get("event_id"), str) or not isinstance(event.get("reason_code"), str):
            raise CLIError("invalid_audit_event", f"audit line {line_number} requires event_id and reason_code")
        if event.get("decision") not in {"allow", "deny"}:
            raise CLIError("invalid_audit_decision", f"audit line {line_number} decision must be allow or deny")
        total += 1
        allow += event["decision"] == "allow"
        deny += event["decision"] == "deny"
    _emit({
        "status": "valid",
        "events_path": args.events,
        "events": total,
        "allow": allow,
        "deny": deny,
    })
    return 0


def build_parser() -> JSONArgumentParser:
    parser = JSONArgumentParser(
        prog="agent-native",
        description="Validate and inspect service contracts; operational commands remain explicit and side-effect limited.",
    )
    parser.add_argument("--version", action="version", version="agent-native 0.1.0.dev0")
    subparsers = parser.add_subparsers(dest="command", required=True, parser_class=JSONArgumentParser)

    check = subparsers.add_parser("check", help="validate a service contract")
    check.add_argument("--service", required=True, help="explicit path to a service contract")
    check.set_defaults(handler=command_check)

    diagnose = subparsers.add_parser("diagnose", help="validate a contract and return actionable diagnostics")
    diagnose.add_argument("--service", required=True, help="explicit path to a service contract")
    diagnose.set_defaults(handler=command_diagnose)

    schema = subparsers.add_parser("schema", help="discover or print a packaged JSON Schema")
    schema.add_argument("--list", action="store_true", help="list all packaged schema identifiers")
    schema.add_argument("--name", help="schema identifier without the .schema.json suffix")
    schema.set_defaults(handler=command_schema)

    inspect = subparsers.add_parser("inspect", help="print canonical service IR")
    inspect.add_argument("--service", required=True, help="explicit path to a service contract")
    inspect.set_defaults(handler=command_inspect)

    run = subparsers.add_parser("run", help="resolve a route without executing handlers")
    run.add_argument("--service", required=True, help="explicit path to a service contract")
    run.add_argument("--method", required=True, help="HTTP method")
    run.add_argument("--path", required=True, help="request path")
    run.add_argument("--dry-run", action="store_true", help="plan routing only; never execute handlers")
    run.set_defaults(handler=command_run)

    worker = subparsers.add_parser("worker", help="inspect an explicit local queue without claiming work")
    worker.add_argument("--service-id", required=True, help="explicit service identifier")
    worker.add_argument("--queue", required=True, help="explicit JSONL queue path")
    worker.set_defaults(handler=command_worker)

    serve = subparsers.add_parser("serve", help="serve registered services with PostgreSQL-backed persistence")
    serve.add_argument("--services-root", default=os.getenv("AGENT_NATIVE_SERVICES_ROOT", "/opt/agent-native/services"))
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8080)
    serve.add_argument("--max-concurrency", type=int, default=32)
    serve.add_argument("--max-request-body-bytes", type=int, default=16_384)
    serve.add_argument("--request-timeout-seconds", type=float, default=10.0)
    serve.add_argument("--shutdown-timeout-seconds", type=float, default=10.0)
    serve.add_argument("--allow-non-loopback", action="store_true", help="explicitly allow binding outside loopback")
    serve.set_defaults(handler=command_serve)

    audit = subparsers.add_parser("audit", help="validate and summarize an explicit JSONL audit file")
    audit.add_argument("--events", required=True, help="explicit JSONL audit-event path")
    audit.set_defaults(handler=command_audit)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
        return args.handler(args)
    except CLIError as error:
        return _error(error)


if __name__ == "__main__":
    raise SystemExit(main())
