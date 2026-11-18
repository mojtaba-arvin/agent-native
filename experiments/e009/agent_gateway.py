"""Agent-facing gateway for the integrated E-009 service kernel.

The gateway exposes only E-005 inspect/propose/validate/plan semantics over a
provider-neutral NDJSON dispatch envelope. Proposals remain immutable and
apply stays disabled. No shell, filesystem, arbitrary network, secrets, or
deployment operations are exposed.
"""

from __future__ import annotations

import argparse
import copy
import json
import sys
from pathlib import Path
from typing import Any

E009_ROOT = Path(__file__).resolve().parent
ROOT = E009_ROOT.parents[1]
PILOT_ROOT = ROOT / "experiments" / "pilot"
E005_ROOT = ROOT / "experiments" / "e005"
E001_ROOT = ROOT / "experiments" / "e001" / "prototype"
E004_ROOT = ROOT / "experiments" / "e004"
E007_ROOT = ROOT / "experiments" / "e007"

for candidate in (E001_ROOT, E004_ROOT, E005_ROOT, PILOT_ROOT, E007_ROOT, E009_ROOT):
    if str(candidate) not in sys.path:
        sys.path.insert(0, str(candidate))

from interface import AgentInterface  # noqa: E402
from kernel import load_service_ir  # noqa: E402
from surface import SurfaceError, build_surface, load_catalog  # noqa: E402
from delta_materializer import DeltaMaterializationError, materialize_add_operation  # noqa: E402


PROTOCOL_VERSION = "0.1"
MAX_MESSAGE_BYTES = 256 * 1024
MESSAGE_FIELDS = {"type", "request_id", "tool", "arguments"}
TRUSTED_EFFECTS = {
    "repository.read",
    "repository.write",
    "queue.submit",
    "queue.read",
    "queue.cancel",
}

DELTA_ALLOWED_EFFECTS = {"repository.read"}
DELTA_ALLOWED_CAPABILITIES = {"items.read"}
DELTA_PROPOSAL_TOOL = {
    "name": "service.propose_delta",
    "summary": "Propose exactly one append-only operation change against the trusted current service revision; the Gateway materializes the complete canonical IR.",
    "mode": "proposal_only",
    "input_schema": {
        "type": "object",
        "required": ["service_id", "base_revision", "changes"],
        "properties": {
            "service_id": {"type": "string", "enum": ["catalog"]},
            "base_revision": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
            "changes": {
                "type": "array", "minItems": 1, "maxItems": 1,
                "items": {
                    "type": "object", "required": ["kind", "operation"],
                    "properties": {
                        "kind": {"type": "string", "enum": ["add_operation"]},
                        "operation": {
                            "type": "object",
                            "required": ["name", "method", "path", "input", "output", "errors", "validation", "effects", "capability"],
                            "properties": {
                                "name": {"type": "string"},
                                "method": {"type": "string", "enum": ["GET"]},
                                "path": {"type": "string"},
                                "input": {
                                    "type": "array",
                                    "items": {
                                        "type": "object", "required": ["name", "source", "type"],
                                        "properties": {
                                            "name": {"type": "string"},
                                            "source": {"type": "string", "enum": ["path", "query", "header", "body"]},
                                            "type": {"type": "string", "enum": ["String", "UUID", "Integer", "Boolean", "Float"]},
                                        },
                                        "additionalProperties": False,
                                    },
                                },
                                "output": {"type": "string"},
                                "errors": {"type": "array", "items": {"type": "string"}},
                                "validation": {"type": "array", "items": {"type": "string"}},
                                "effects": {"type": "array", "items": {"type": "string", "enum": sorted(DELTA_ALLOWED_EFFECTS)}},
                                "capability": {"type": "string", "enum": sorted(DELTA_ALLOWED_CAPABILITIES)},
                            },
                            "additionalProperties": False,
                        },
                    },
                    "additionalProperties": False,
                },
            },
        },
        "additionalProperties": False,
    },
}


class AgentGatewayError(ValueError):
    pass


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise AgentGatewayError("duplicate_json_key")
        result[key] = value
    return result


def _reject_non_finite(value: str) -> None:
    raise AgentGatewayError("non_finite_json_number")


def strict_json_loads(raw: bytes) -> Any:
    try:
        return json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_non_finite,
        )
    except UnicodeDecodeError as error:
        raise AgentGatewayError("invalid_utf8") from error
    except json.JSONDecodeError as error:
        raise AgentGatewayError("invalid_json") from error


def _encode(value: dict) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
        + b"\n"
    )


class AgentNativeGateway:
    """A narrow Agent-facing tool gateway backed by the live E-009 service IR."""

    def __init__(
        self,
        arm: str,
        *,
        proposal_mode: str = "snapshot",
        service_source: str | None = None,
        apply_callback=None,
    ):
        if arm not in {"progressive", "upfront"}:
            raise AgentGatewayError("unknown_disclosure_arm")
        if proposal_mode not in {"snapshot", "delta"}:
            raise AgentGatewayError("unknown_proposal_mode")
        source = service_source
        if source is None:
            source = (E009_ROOT / "catalog.an").read_text(encoding="utf-8")
        service_ir = load_service_ir(source)
        self.proposal_mode = proposal_mode
        self.catalog = load_catalog()
        if proposal_mode == "delta":
            self.catalog = copy.deepcopy(self.catalog)
            self.catalog["tools"] = [
                item for item in self.catalog["tools"] if item["name"] != "service.propose"
            ] + [copy.deepcopy(DELTA_PROPOSAL_TOOL)]
        self.surface = build_surface(arm, catalog=self.catalog)
        self.surface["proposal_mode"] = proposal_mode
        self.allowed_tools = {item["name"] for item in self.catalog["tools"]}
        self.interface = AgentInterface(
            {"catalog": service_ir},
            trusted_effects=TRUSTED_EFFECTS,
            apply_callback=apply_callback,
        )
        self.interface.catalog = copy.deepcopy(self.catalog)
        self._delta_intents: dict[str, dict] = {}
        if apply_callback is not None:
            for catalog_tool in self.interface.catalog.get("tools", []):
                if catalog_tool.get("name") == "service.apply":
                    catalog_tool["mode"] = "sandbox_only"
                    catalog_tool["summary"] = "Apply a validated service change set to the isolated demo runtime; never production."
            for surface_tool in self.surface.get("tools", []):
                if surface_tool.get("name") == "service.apply":
                    surface_tool["mode"] = "sandbox_only"
                    surface_tool["summary"] = "Apply a validated service change set to the isolated demo runtime; never production."
        self._required_inspection_order = [
            item["name"] for item in service_ir["operations"]
        ]
        self._required_inspection_operations = set(self._required_inspection_order)
        self._inspected_revision: str | None = None
        self._inspected_operations: set[str] = set()
        self._inspected_operation_contracts: dict[str, dict] = {}
        self._inspected_service: dict | None = None
        self._inspected_types: list | None = None
        self._service_inspection_repeat_attempts: set[tuple[str, ...]] = set()

    def session_message(self) -> dict:
        return {
            "type": "session",
            "protocol_version": PROTOCOL_VERSION,
            "max_message_bytes": MAX_MESSAGE_BYTES,
            "surface": self.surface,
        }

    @staticmethod
    def _error(
        request_id: str,
        code: str,
        message: str,
        *,
        next_actions: list[str] | None = None,
        fix_hint: str | None = None,
    ) -> dict:
        response = {
            "protocol_version": PROTOCOL_VERSION,
            "request_id": request_id,
            "ok": False,
            "result": None,
            "diagnostics": [{
                "code": code,
                "message": message,
                "source_span": None,
                "fix_hint": fix_hint,
            }],
            "next_actions": next_actions or [],
        }
        return {
            "type": "tool_result",
            "request_id": request_id,
            "response": response,
        }

    def _handle_delta_proposal(self, request_id: str, arguments: dict) -> dict:
        def delta_error(*args, **kwargs):
            return self._error(*args, **kwargs)["response"]

        if self.proposal_mode != "delta":
            return self._error(request_id, "UNKNOWN_TOOL", "Delta proposals are not enabled in this Gateway instance.")
        if self._inspected_revision is None:
            return self._error(
                request_id, "INSPECTION_REQUIRED", "Inspect the service before proposing a delta.",
                next_actions=["service.inspect with service_id=catalog"],
            )
        if arguments.get("base_revision") != self._inspected_revision:
            return self._error(
                request_id, "STALE_BASE_REVISION", "The delta base must match the exact inspected service revision.",
                next_actions=["service.inspect with service_id=catalog"],
            )
        current_service = self.interface.services.get(arguments.get("service_id"))
        if current_service is None:
            return self._error(request_id, "SERVICE_NOT_FOUND", "Unknown service for delta proposal.")
        try:
            materialized = materialize_add_operation(
                _encode(arguments),
                service_id="catalog",
                current_service=current_service,
                trusted_effects=DELTA_ALLOWED_EFFECTS,
                trusted_capabilities=DELTA_ALLOWED_CAPABILITIES,
            )
        except DeltaMaterializationError as error:
            code = "DELTA_" + error.code.upper()
            return self._error(
                request_id, code, "The append-only delta was rejected by the trusted materializer.",
                fix_hint="Submit exactly one add_operation against the current inspected base, using only trusted effects and capabilities.",
            )
        proposal_response = self.interface.handle({
            "protocol_version": PROTOCOL_VERSION,
            "request_id": request_id,
            "tool": "service.propose",
            "arguments": {
                "service_id": "catalog",
                "base_revision": materialized["base_revision"],
                "ir": materialized["ir"],
            },
        }, context={"request_id": request_id})
        if proposal_response.get("ok"):
            change_set_id = proposal_response["result"]["change_set_id"]
            intent_record = {
                "base_revision": materialized["base_revision"],
                "intent_digest": materialized["intent_digest"],
                "normalized_intent": materialized["normalized_intent"],
                "materialized_ir_digest": materialized["materialized_ir_digest"],
            }
            self._delta_intents[change_set_id] = intent_record
            self.interface.proposals[change_set_id].update(intent_record)
            proposal_response["result"].update({
                "proposal_mode": "delta",
                "intent_digest": materialized["intent_digest"],
                "materialized_ir_digest": materialized["materialized_ir_digest"],
            })
        return proposal_response

    def _delta_proposal_current_error(self, request_id: str, change_set_id: Any) -> dict | None:
        if not isinstance(change_set_id, str) or change_set_id not in self._delta_intents:
            return None
        proposal = self.interface.proposals.get(change_set_id)
        if proposal is None or proposal.get("base_revision") != self.interface.revision("catalog"):
            self.interface.validated_change_sets.discard(change_set_id)
            self.interface.planned_change_sets.discard(change_set_id)
            return self._error(
                request_id, "STALE_BASE_REVISION",
                "The service base changed after this delta was proposed; validation and planning are blocked.",
                next_actions=["Inspect the current service and create a new delta proposal."],
            )
        return None

    def handle_message(self, message: Any) -> dict:
        if not isinstance(message, dict):
            return self._error("invalid", "REQUEST_SHAPE", "Message must be a JSON object.")
        request_id = message.get("request_id")
        if not isinstance(request_id, str) or not request_id or len(request_id) > 128:
            return self._error("invalid", "REQUEST_ID", "request_id must be a non-empty string of at most 128 characters.")
        if set(message) != MESSAGE_FIELDS:
            return self._error(request_id, "REQUEST_FIELDS", "Message must contain exactly type, request_id, tool, and arguments.")
        if message.get("type") != "tool_call":
            return self._error(request_id, "MESSAGE_TYPE", "Only tool_call messages are accepted.")
        tool = message.get("tool")
        arguments = message.get("arguments")
        if not isinstance(tool, str) or not tool:
            return self._error(request_id, "TOOL_NAME", "tool must be a non-empty string.")
        if tool not in self.allowed_tools:
            return self._error(request_id, "UNKNOWN_TOOL", f"Tool {tool!r} is not exposed.")
        if not isinstance(arguments, dict):
            return self._error(request_id, "ARGUMENT_SHAPE", "arguments must be a JSON object.")

        if tool == "service.propose_delta":
            response = self._handle_delta_proposal(request_id, arguments)
            return {"type": "tool_result", "request_id": request_id, "response": response}

        if tool in {"service.validate", "service.plan"}:
            stale = self._delta_proposal_current_error(request_id, arguments.get("change_set_id"))
            if stale is not None:
                return stale

        if tool == "service.propose":
            base_revision = arguments.get("base_revision")
            if self._inspected_revision is None:
                return self._error(
                    request_id,
                    "INSPECTION_REQUIRED",
                    "Inspect the service before proposing a change.",
                    next_actions=["service.inspect with service_id=catalog"],
                )
            if base_revision == self._inspected_revision:
                missing = sorted(
                    self._required_inspection_operations - self._inspected_operations
                )
                if missing:
                    return self._error(
                        request_id,
                        "INSPECTION_INCOMPLETE",
                        "Inspect every existing operation before proposing. Missing: "
                        + ", ".join(missing),
                        next_actions=[
                            f"service.inspect with operation={name}"
                            for name in missing
                        ],
                    )

                ir = arguments.get("ir")
                if isinstance(ir, dict):
                    changed_sections = []
                    if "service" in ir and ir["service"] != self._inspected_service:
                        changed_sections.append("service")
                    if "types" in ir and ir["types"] != self._inspected_types:
                        changed_sections.append("types")
                    operations = ir.get("operations")
                    changed_operations = []
                    if isinstance(operations, list):
                        for index, name in enumerate(self._required_inspection_order):
                            expected = self._inspected_operation_contracts.get(name)
                            if index >= len(operations) or expected is None or operations[index] != expected:
                                changed_operations.append(name)
                        if len(operations) < len(self._required_inspection_order):
                            changed_sections.append("existing_operations_missing")
                        if changed_operations:
                            changed_sections.append("existing_operations_changed")
                    if changed_sections:
                        details = []
                        if changed_operations:
                            details.append("changed existing operations: " + ", ".join(changed_operations))
                        details.append("changed sections: " + ", ".join(changed_sections))
                        return self._error(
                            request_id,
                            "IR_PRESERVATION_MISMATCH",
                            "The proposal does not preserve the inspected base exactly: " + "; ".join(details),
                            next_actions=[
                                "Copy the exact inspected service and type declarations and every existing operation object in original order; append only the requested new operation."
                            ],
                            fix_hint=(
                                "Do not recreate, normalize, infer, reorder, or edit existing declarations. "
                                "Copy the complete service object, types array, and each operation JSON object "
                                "exactly as returned by service.inspect. Preserve method, path, input, output, "
                                "errors, validation, effects, and capability. Append only the requested new operation."
                            ),
                        )

        response = self.interface.handle({
            "protocol_version": PROTOCOL_VERSION,
            "request_id": request_id,
            "tool": tool,
            "arguments": arguments,
        }, context={"request_id": request_id})
        if tool == "service.inspect" and response.get("ok"):
            operation = arguments.get("operation")
            if operation is None:
                revision = response["result"]["revision"]
                if self._inspected_revision == revision:
                    missing = [
                        name for name in self._required_inspection_order
                        if name not in self._inspected_operations
                    ]
                    if missing:
                        repair_key = tuple(missing)
                        if repair_key in self._service_inspection_repeat_attempts:
                            return self._error(
                                request_id,
                                "INSPECTION_PROGRESS_REPAIR_EXHAUSTED",
                                "The same incomplete service-level inspection was repeated after an actionable correction. Stop repeating it and inspect the first remaining operation from the previous next_actions.",
                                next_actions=["Stop: inspect an existing operation using its exact operation name."],
                                fix_hint=(
                                    'Use service.inspect arguments {"service_id":"catalog","operation":"<exact remaining operation name>"}. '
                                    "A repeated service-level inspection with no operation will not be retried."
                                ),
                            )
                        self._service_inspection_repeat_attempts.add(repair_key)
                        return self._error(
                            request_id,
                            "INSPECTION_OPERATION_REQUIRED",
                            "The service-level inspection is already complete. Inspect each existing operation contract individually; repeating service.inspect without operation does not complete inspection.",
                            next_actions=[
                                f"service.inspect with operation={name}"
                                for name in missing
                            ],
                            fix_hint=(
                                'Call service.inspect with arguments {"service_id":"catalog","operation":"<exact available operation name>"}. '
                                "Start with the first name in next_actions; do not repeat the service-level inspection."
                            ),
                        )
                    response["next_actions"] = [
                        "service.propose_delta with the inspected base_revision and exactly one add_operation change"
                        if self.proposal_mode == "delta" else
                        "service.propose with the inspected base_revision and complete canonical IR snapshot"
                    ]
                else:
                    self._inspected_revision = revision
                    self._inspected_service = copy.deepcopy(response["result"]["service"])
                    self._inspected_types = copy.deepcopy(response["result"]["types"])
                    self._service_inspection_repeat_attempts.clear()
                    self._inspected_operations.clear()
                    self._inspected_operation_contracts.clear()
                    self._required_inspection_order = [
                        item["name"] for item in response["result"]["operations"]
                    ]
                    self._required_inspection_operations = set(self._required_inspection_order)
                    response["next_actions"] = (
                        ["service.propose_delta with the inspected base_revision and exactly one add_operation change"]
                        if self.proposal_mode == "delta" else
                        [
                            f"service.inspect with operation={name}"
                            for name in self._required_inspection_order
                        ]
                    )
            elif self._inspected_revision is not None:
                self._inspected_operations.add(operation)
                full_contract = (response.get("result") or {}).get("operation")
                if isinstance(full_contract, dict) and full_contract.get("name") == operation:
                    self._inspected_operation_contracts[operation] = copy.deepcopy(full_contract)
        return {
            "type": "tool_result",
            "request_id": request_id,
            "response": response,
        }

    def handle_line(self, raw_line: bytes) -> bytes:
        if len(raw_line) > MAX_MESSAGE_BYTES:
            result = self._error("invalid", "MESSAGE_TOO_LARGE", "Message exceeds the configured byte limit.")
        else:
            try:
                result = self.handle_message(strict_json_loads(raw_line))
            except AgentGatewayError as error:
                result = self._error("invalid", str(error).upper(), "Message must be finite UTF-8 JSON without duplicate keys.")
        return _encode(result)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--arm", choices=("progressive", "upfront"), required=True)
    parser.add_argument("--proposal-mode", choices=("snapshot", "delta"), default="snapshot")
    parser.add_argument("--sandbox-apply", action="store_true")
    parser.add_argument("--sandbox-dir", type=Path)
    args = parser.parse_args()
    try:
        apply_callback = None
        if args.sandbox_apply:
            if args.sandbox_dir is None:
                parser.error("--sandbox-dir is required with --sandbox-apply")
            e010_root = ROOT / "experiments" / "e010"
            if str(e010_root) not in sys.path:
                sys.path.insert(0, str(e010_root))
            from demo_apply import SandboxApplyCoordinator
            coordinator = SandboxApplyCoordinator(args.sandbox_dir)
            apply_callback = coordinator.apply
        gateway = AgentNativeGateway(args.arm, proposal_mode=args.proposal_mode, apply_callback=apply_callback)
    except (AgentGatewayError, SurfaceError, OSError, ValueError) as error:
        parser.error(str(error))

    stdout = sys.stdout.buffer
    stdin = sys.stdin.buffer
    stdout.write(_encode(gateway.session_message()))
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
