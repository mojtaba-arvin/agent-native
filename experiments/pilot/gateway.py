"""Local NDJSON gateway for the disposable E-005 disclosure pilot.

This is a protocol adapter, not a sandbox, network server, or agent runner.
An isolated agent client may communicate with it over inherited stdin/stdout.
It never loads or evaluates the hidden acceptance oracle.
"""

from __future__ import annotations

import argparse
import json
import math
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
        max_tool_calls: int | None = None,
    ):
        if max_tool_calls is not None and (
            type(max_tool_calls) is not int or max_tool_calls < 1
        ):
            raise ValueError("max_tool_calls_must_be_positive_integer")
        self.max_tool_calls = max_tool_calls
        self.tool_call_count = 0
        self.model_usage_request_ids: set[str] = set()
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
            "timestamp_ns": time.monotonic_ns(),
            "event_type": event_type,
            "run_id": self.trace_context["run_id"],
            "candidate_id": self.trace_context["candidate_id"],
            "model_id": self.trace_context["model_id"],
            **fields,
        }
        self.trace_sink(event)

    def _record_tool_call(
        self,
        tool_name: str,
        failure_class: str | None = None,
        *,
        schema_lookup: bool = False,
        change_set_id: str | None = None,
        safe_result_metadata: dict | None = None,
    ) -> None:
        fields = {"tool_name": tool_name, "schema_lookup": schema_lookup}
        if failure_class is not None:
            fields["failure_class"] = failure_class
        if change_set_id is not None:
            fields["change_set_id"] = change_set_id
        if safe_result_metadata:
            fields.update(safe_result_metadata)
        self._emit_trace("tool_call", **fields)

    def _record_protocol_error(self, message: Any, code: str) -> None:
        tool_name = "<invalid>"
        if isinstance(message, dict):
            supplied_tool = message.get("tool")
            if isinstance(supplied_tool, str) and supplied_tool:
                tool_name = supplied_tool[:128]
        self._record_tool_call(tool_name, code)

    def session_message(self) -> dict:
        return {
            "type": "session",
            "protocol_version": "0.1",
            "max_message_bytes": MAX_MESSAGE_BYTES,
            "surface": self.surface,
        }

    def _handle_model_usage(self, message: dict, request_id: str) -> dict:
        """Accept usage only on the trusted adapter-to-gateway control channel.

        The provider adapter sends this internal message after each model
        response. It is not a model-facing tool and is never listed in the
        session surface or dispatch enum.
        """
        allowed = {"type", "request_id", "input_tokens", "output_tokens", "cost_usd"}
        if set(message) - allowed:
            return {
                "type": "telemetry_ack",
                "request_id": request_id,
                "accepted": False,
                "diagnostic": "MODEL_USAGE_FIELDS",
            }
        input_tokens = message.get("input_tokens")
        output_tokens = message.get("output_tokens")
        if (
            type(input_tokens) is not int or input_tokens < 0
            or type(output_tokens) is not int or output_tokens < 0
        ):
            return {
                "type": "telemetry_ack",
                "request_id": request_id,
                "accepted": False,
                "diagnostic": "MODEL_USAGE_TOKENS",
            }
        if request_id in self.model_usage_request_ids:
            return {
                "type": "telemetry_ack",
                "request_id": request_id,
                "accepted": False,
                "diagnostic": "MODEL_USAGE_DUPLICATE_REQUEST",
            }
        fields = {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
        }
        if "cost_usd" in message:
            cost = message["cost_usd"]
            if (
                isinstance(cost, bool)
                or not isinstance(cost, (int, float))
                or not math.isfinite(cost)
                or cost < 0
            ):
                return {
                    "type": "telemetry_ack",
                    "request_id": request_id,
                    "accepted": False,
                    "diagnostic": "MODEL_USAGE_COST",
                }
            fields["cost_usd"] = cost
        self._emit_trace("model_usage", **fields)
        self.model_usage_request_ids.add(request_id)
        return {
            "type": "telemetry_ack",
            "request_id": request_id,
            "accepted": True,
        }

    def handle_message(self, message: Any) -> dict:
        if not isinstance(message, dict):
            self._record_protocol_error(message, "REQUEST_SHAPE")
            return _error_response("invalid", "REQUEST_SHAPE", "Message must be a JSON object.")
        request_id = message.get("request_id", "invalid")
        if not isinstance(request_id, str) or not request_id or len(request_id) > MAX_REQUEST_ID_LENGTH:
            self._record_protocol_error(message, "REQUEST_ID")
            return _error_response("invalid", "REQUEST_ID", "request_id must be a non-empty string of at most 128 characters.")
        if message.get("type") == "model_usage":
            return self._handle_model_usage(message, request_id)
        if message.get("type") == "tool_call":
            self.tool_call_count += 1
            if (
                self.max_tool_calls is not None
                and self.tool_call_count > self.max_tool_calls
            ):
                tool_name = message.get("tool")
                if not isinstance(tool_name, str) or not tool_name:
                    tool_name = "<invalid>"
                self._record_tool_call(tool_name[:128], "TOOL_CALL_BUDGET_EXCEEDED")
                return _error_response(
                    request_id,
                    "TOOL_CALL_BUDGET_EXCEEDED",
                    "The scheduled tool-call budget is exhausted.",
                )
        if set(message) != ENVELOPE_FIELDS:
            self._record_protocol_error(message, "REQUEST_FIELDS")
            return _error_response(request_id, "REQUEST_FIELDS", "Message must contain exactly type, request_id, tool, and arguments.")
        if message.get("type") != "tool_call":
            self._record_protocol_error(message, "MESSAGE_TYPE")
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
        schema_lookup = tool == "interface.describe" and isinstance(arguments.get("name"), str) and bool(arguments["name"])
        change_set_id = None
        if tool == "service.propose" and response.get("ok"):
            proposed = response.get("result")
            if isinstance(proposed, dict):
                candidate_id = proposed.get("change_set_id")
                if isinstance(candidate_id, str):
                    change_set_id = candidate_id
        elif tool in {"service.validate", "service.plan"} and response.get("ok"):
            tool_result = response.get("result")
            supplied_id = arguments.get("change_set_id")
            returned_id = tool_result.get("change_set_id") if isinstance(tool_result, dict) else None
            if isinstance(supplied_id, str) and supplied_id == returned_id:
                change_set_id = supplied_id
        safe_result_metadata = {}
        tool_result = response.get("result")
        if tool == "service.validate" and isinstance(tool_result, dict):
            valid = tool_result.get("valid")
            if isinstance(valid, bool):
                safe_result_metadata["validation_valid"] = valid
        if tool == "service.plan" and isinstance(tool_result, dict):
            valid = tool_result.get("valid")
            will_mutate = tool_result.get("will_mutate")
            will_deploy = tool_result.get("will_deploy")
            if isinstance(valid, bool):
                safe_result_metadata["plan_valid"] = valid
            if isinstance(will_mutate, bool):
                safe_result_metadata["plan_will_mutate"] = will_mutate
            if isinstance(will_deploy, bool):
                safe_result_metadata["plan_will_deploy"] = will_deploy
        self._record_tool_call(
            tool,
            failure_class,
            schema_lookup=schema_lookup,
            change_set_id=change_set_id,
            safe_result_metadata=safe_result_metadata,
        )
        return {
            "type": "tool_result",
            "request_id": request_id,
            "response": response,
        }

    def handle_line(self, raw_line: bytes) -> bytes:
        if len(raw_line) > MAX_MESSAGE_BYTES:
            self._record_protocol_error(None, "MESSAGE_TOO_LARGE")
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
                self._record_protocol_error(None, "INVALID_UTF8")
                result = _error_response("invalid", "INVALID_UTF8", "Messages must be UTF-8.")
            except json.JSONDecodeError:
                self._record_protocol_error(None, "INVALID_JSON")
                result = _error_response("invalid", "INVALID_JSON", "Message must contain one valid JSON value.")
            except GatewayInputError as error:
                self._record_protocol_error(None, error.code)
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
    parser.add_argument("--max-tool-calls", type=int)
    args = parser.parse_args()

    trace_sink = None
    trace_context = None
    if args.trace_output:
        if not args.run_id or not args.model_id:
            parser.error("--trace-output requires --run-id and --model-id")
        if args.max_tool_calls is None or args.max_tool_calls < 1:
            parser.error("--trace-output requires a positive --max-tool-calls")
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
        max_tool_calls=args.max_tool_calls,
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
