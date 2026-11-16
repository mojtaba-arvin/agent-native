"""Local NDJSON gateway for the disposable E-005 disclosure pilot.

This is a protocol adapter, not a sandbox, network server, or agent runner.
An external isolated agent process may communicate with it over inherited
stdin/stdout. It never loads or evaluates the hidden acceptance oracle.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
E001_PROTOTYPE = ROOT / "experiments" / "e001" / "prototype"
E005_ROOT = ROOT / "experiments" / "e005"
CATALOG_SOURCE = ROOT / "experiments" / "e001" / "examples" / "catalog.an"

sys.path.insert(0, str(E001_PROTOTYPE))
sys.path.insert(0, str(E005_ROOT))

from agent_native import Parser  # noqa: E402
from interface import AgentInterface  # noqa: E402
from surface import build_surface, load_catalog  # noqa: E402

MAX_MESSAGE_BYTES = 256 * 1024
MAX_REQUEST_ID_LENGTH = 128
TRUSTED_EFFECTS = {"repository.read", "repository.write"}
ENVELOPE_FIELDS = {"type", "request_id", "tool", "arguments"}


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


class PilotGateway:
    def __init__(self, arm: str):
        self.surface = build_surface(arm)
        self.catalog = load_catalog()
        source = CATALOG_SOURCE.read_text(encoding="utf-8")
        service_ir = Parser(source).parse()
        self.interface = AgentInterface(
            {"catalog": service_ir},
            trusted_effects=TRUSTED_EFFECTS,
        )
        self.allowed_tools = {item["name"] for item in self.catalog["tools"]}

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
            return _error_response(request_id, "TOOL_NAME", "tool must be a non-empty string.")
        if tool not in self.allowed_tools:
            return _error_response(request_id, "UNKNOWN_TOOL", f"Tool {tool!r} is not exposed.")
        if not isinstance(arguments, dict):
            return _error_response(request_id, "ARGUMENT_SHAPE", "arguments must be a JSON object.")

        response = self.interface.handle({
            "protocol_version": "0.1",
            "request_id": request_id,
            "tool": tool,
            "arguments": arguments,
        })
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
    args = parser.parse_args()
    gateway = PilotGateway(args.arm)
    stdout = sys.stdout.buffer
    stdin = sys.stdin.buffer

    stdout.write((json.dumps(gateway.session_message(), ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8"))
    stdout.flush()

    while True:
        line = stdin.readline(MAX_MESSAGE_BYTES + 1)
        if not line:
            break
        stdout.write(gateway.handle_line(line))
        stdout.flush()
        if len(line) > MAX_MESSAGE_BYTES:
            break


if __name__ == "__main__":
    main()
