"""Unified, side-effect-conscious developer CLI for the agent_native package."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from urllib.parse import urlsplit


class CLIError(Exception):
    def __init__(self, code: str, message: str, exit_code: int = 3):
        super().__init__(message)
        self.code = code
        self.exit_code = exit_code


class JSONArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        payload = {"error": {"code": "invalid_arguments", "message": message}}
        print(json.dumps(payload, sort_keys=True), file=sys.stderr)
        self.exit(2)


def _emit(value: dict) -> None:
    print(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False))


def _error(error: CLIError) -> int:
    print(
        json.dumps(
            {"error": {"code": error.code, "message": str(error)}},
            ensure_ascii=False,
            sort_keys=True,
        ),
        file=sys.stderr,
    )
    return error.exit_code


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
            f"{error.message} at {error.token.line}:{error.token.column}",
        ) from error
    return service_path.resolve(), ir


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
    path, ir = _read_service(args.service)
    _emit({
        "status": "valid",
        "service": ir["service"]["name"],
        "version": ir["service"]["version"],
        "operations": len(ir["operations"]),
        "service_path": str(path),
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
        "queue_path": str(queue_path.resolve()),
        "records": total,
        "queued_records": queued,
    })
    return 0


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
        "events_path": str(events_path.resolve()),
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
