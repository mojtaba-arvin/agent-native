"""Local NDJSON gateway for the disposable E-005 disclosure pilot.

This is a protocol adapter, not a sandbox, network server, or agent runner.
An isolated agent client may communicate with it over inherited stdin/stdout.
It never loads or evaluates the hidden acceptance oracle.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import uuid
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[2]
E001_PROTOTYPE = ROOT / "experiments" / "e001" / "prototype"
E005_ROOT = ROOT / "experiments" / "e005"
CATALOG_SOURCE = ROOT / "experiments" / "e001" / "examples" / "catalog.an"

sys.path.insert(0, str(E001_PROTOTYPE))
sys.path.insert(0, str(E005_ROOT))

from agent_native import Parser  # noqa: E402
from interface import AgentInterface  # noqa: E402
from surface import build_surface, load_catalog, surface_size_bytes  # noqa: E402

MAX_MESSAGE_BYTES = 256 * 1024
MAX_REQUEST_ID_LENGTH = 128
TRUSTED_EFFECTS = {"repository.read", "repository.write"}
ENVELOPE_FIELDS = {"type", "request_id", "tool", "arguments"}
PILOT_TASK_ID = "pilot-catalog-add-readonly-operation"


class GatewayInputError(ValueError):
    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(message)


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise GatewayInputError("DUPLICATE_JSON_KEY", "JSON objects must not contain duplicate keys.")
        result[key] = value
    return result


def _reject_non_finite(value: str) -> None:
    raise GatewayInputError("NON_FINITE_JSON_NUMBER", "JSON numbers must be finite.")


def _error_response(request_id: str, code: str, message: str) -> dict:
    return {
        "type": "tool_result",
        "request_id": request_id,
        "response": {
            "protocol_version": "0.1",
            "request_id": request_id,
            "ok": False,
            "result": None,
            "diagnostics": [{
                "code": code,
                "message": message,
                "source_span": None,
                "fix_hint": None,
            }],
            "next_actions": [],
        },
    }


class JsonlTraceSink:
    """Create one exclusive trace file per run and append validated JSONL events."""

    def __init__(self, path: str | Path):
        trace_path = Path(path).expanduser().absolute()
        trace_path.parent.mkdir(parents=True, exist_ok=True)
        descriptor = os.open(
            trace_path,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL,
            0o600,
        )
        self.stream = os.fdopen(descriptor, "w", encoding="utf-8")

    def __call__(self, event: dict) -> None:
        encoded = json.dumps(
            event,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        self.stream.write(encoded + "\n")
        self.stream.flush()

    def close(self) -> None:
        self.stream.close()


class PilotGateway:
    def __init__(
        self,
        arm: str,
        *,
        trace_sink: Callable[[dict], None] | None = None,
        trace_context: dict | None = None,
    ):
        self.surface = build_surface(arm)
        self.catalog = load_catalog()
        source = CATALOG_SOURCE.read_text(encoding="utf-8")
        service_ir = Parser(source).parse()
        self.interface = AgentInterface(
            {"catalog": service_ir},
            trusted_effects=TRUSTED_EFFECTS,
        )
        self.allowed_tools = {item["name"] for item in self.catalog["tools"]}
        self.trace_sink = trace_sink
        self.trace_context = trace_context

        if trace_sink is not None:
            required = {"run_id", "candidate_id", "model_id", "task_id", "attempt"}
            if not isinstance(trace_context, dict) or not required.issubset(trace_context):
                raise ValueError("trace_context_missing_required_identity")
            for field in ("run_id", "candidate_id", "model_id", "task_id"):
                value = trace_context[field]
                if not isinstance(value, str) or not value or len(value) > 256:
                    raise ValueError(f"invalid_trace_identity:{field}")
            attempt = trace_context["attempt"]
            if not isinstance(attempt, int) or isinstance(attempt, bool) or attempt < 1:
                raise ValueError("invalid_trace_attempt")
            self._emit_trace("task_started")
            self._emit_trace(
                "runtime_metric",
                metric_name="initial_surface_payload",
                metric_value=surface_size_bytes(self.surface),
                metric_unit="bytes",
            )

    def _emit_trace(self, event_type: str, **fields: Any) -> None:
        if self.trace_sink is None:
            return
        event = {
            "event_id": uuid.uuid4().hex,
            "task_id": self.trace_context["task_id"],
            "attempt": self.trace_context["attempt"],
            "timestamp_ns": time.time_ns(),
            "event_type": event_type,
            "run_id": self.trace_context["run_id"],
            "candidate_id": self.trace_context["candidate_id"],
            "model_id": self.trace_context["model_id"],
            **fields,
        }
        self.trace_sink(event)

    def _record_tool_call(self, tool_name: str, failure_class: str | None = None) -> None:
        fields = {"tool_name": tool_name}
        if failure_class is not None:
            fields["failure_class"] = failure_class
        self._emit_trace("tool_call", **fields)

    def session_message(self) -> dict:
        return {
            "type": "session",
            "protocol_version": "0.1",
            "max_message_bytes": MAX_MESSAGE_BYTES,
            "surface": self.surface,
        }

    def handle_message(self, message: Any) -> dict:
        if not isinstance(message, dict):
            return _error_response("invalid", "REQUEST_SHAPE", "Message must be a JSON object.")
        request_id = message.get("request_id", "invalid")
        if not isinstance(request_id, str) or not request_id or len(request_id) > MAX_REQUEST_ID_LENGTH:
            return _error_response("invalid", "REQUEST_ID", "request_id must be a non-empty string of at most 128 characters.")
        if set(message) != ENVELOPE_FIELDS:
            return _error_response(request_id, "REQUEST_FIELDS", "Message must contain exactly type, request_id, tool, and arguments.")
        if message.get("type") != "tool_call":
            return _error_response(request_id, "MESSAGE_TYPE", "Only tool_call messages are accepted.")
        tool = message.get("tool")
        arguments = message.get("arguments")
        if not isinstance(tool, str) or not tool:
            self._record_tool_call("<invalid>", "TOOL_NAME")
            return _error_response(request_id, "TOOL_NAME", "tool must be a non-empty string.")
        if tool not in self.allowed_tools:
            self._record_tool_call(tool, "UNKNOWN_TOOL")
            return _error_response(request_id, "UNKNOWN_TOOL", f"Tool {tool!r} is not exposed.")
        if not isinstance(arguments, dict):
            self._record_tool_call(tool, "ARGUMENT_SHAPE")
            return _error_response(request_id, "ARGUMENT_SHAPE", "arguments must be a JSON object.")

        response = self.interface.handle({
            "protocol_version": "0.1",
            "request_id": request_id,
            "tool": tool,
            "arguments": arguments,
        })
        diagnostics = response.get("diagnostics", [])
        failure_class = diagnostics[0]["code"] if diagnostics else None
        self._record_tool_call(tool, failure_class)
        return {
            "type": "tool_result",
            "request_id": request_id,
            "response": response,
        }

    def handle_line(self, raw_line: bytes) -> bytes:
        if len(raw_line) > MAX_MESSAGE_BYTES:
            result = _error_response("invalid", "MESSAGE_TOO_LARGE", "Message exceeds the configured byte limit.")
        else:
            try:
                decoded = raw_line.decode("utf-8")
                message = json.loads(
                    decoded,
                    object_pairs_hook=_reject_duplicate_keys,
                    parse_constant=_reject_non_finite,
                )
                result = self.handle_message(message)
            except UnicodeDecodeError:
                result = _error_response("invalid", "INVALID_UTF8", "Messages must be UTF-8.")
            except json.JSONDecodeError:
                result = _error_response("invalid", "INVALID_JSON", "Message must contain one valid JSON value.")
            except GatewayInputError as error:
                result = _error_response("invalid", error.code, error.message)
        return (json.dumps(result, ensure_ascii=False, sort_keys=True, allow_nan=False) + "\n").encode("utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--arm", choices=("progressive", "upfront"), required=True)
    parser.add_argument("--trace-output", type=Path)
    parser.add_argument("--run-id")
    parser.add_argument("--model-id")
    parser.add_argument("--candidate-id")
    parser.add_argument("--task-id", default=PILOT_TASK_ID)
    parser.add_argument("--attempt", type=int, default=1)
    args = parser.parse_args()

    trace_sink = None
    trace_context = None
    if args.trace_output:
        if not args.run_id or not args.model_id:
            parser.error("--trace-output requires --run-id and --model-id")
        trace_sink = JsonlTraceSink(args.trace_output)
        trace_context = {
            "run_id": args.run_id,
            "candidate_id": args.candidate_id or args.arm,
            "model_id": args.model_id,
            "task_id": args.task_id,
            "attempt": args.attempt,
        }

    gateway = PilotGateway(
        args.arm,
        trace_sink=trace_sink,
        trace_context=trace_context,
    )
    stdout = sys.stdout.buffer
    stdin = sys.stdin.buffer

    stdout.write((json.dumps(gateway.session_message(), ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8"))
    stdout.flush()

    try:
        while True:
            line = stdin.readline(MAX_MESSAGE_BYTES + 1)
            if not line:
                break
            stdout.write(gateway.handle_line(line))
            stdout.flush()
            if len(line) > MAX_MESSAGE_BYTES:
                break
    finally:
        if trace_sink is not None:
            trace_sink.close()


if __name__ == "__main__":
    main()
