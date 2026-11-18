from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from typing import Callable
import sys

_REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPOSITORY_ROOT / "experiments" / "e001" / "prototype"))
from agent_native import Diagnostic, validate_ir  # noqa: E402


PROTOCOL_VERSION = "0.1"
HIGH_IMPACT_EFFECTS = frozenset({
    "network.egress",
    "secrets.read",
    "database.drop",
    "production.deploy",
})


def canonical_json(value: object) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def digest(value: object) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


class AgentInterface:
    def __init__(
        self,
        services: dict[str, dict],
        *,
        trusted_effects: set[str],
        apply_callback: Callable[[dict, dict], dict] | None = None,
    ):
        self.services = copy.deepcopy(services)
        self.trusted_effects = frozenset(trusted_effects)
        self.apply_callback = apply_callback
        self.proposals: dict[str, dict] = {}
        self.validated_change_sets: set[str] = set()
        self.planned_change_sets: set[str] = set()
        self.applied_change_sets: dict[str, dict] = {}
        self.catalog = json.loads(
            (Path(__file__).parent / "tools.json").read_text(encoding="utf-8")
        )

    def revision(self, service_id: str) -> str:
        return digest(self.services[service_id])

    @staticmethod
    def _diagnostic(code: str, message: str, fix_hint: str | None = None) -> dict:
        return {"code": code, "message": message, "source_span": None, "fix_hint": fix_hint}

    def _response(self, request_id: str, *, result=None, diagnostics=None, next_actions=None):
        diagnostics = diagnostics or []
        return {
            "protocol_version": PROTOCOL_VERSION,
            "request_id": request_id,
            "ok": not diagnostics,
            "result": result,
            "diagnostics": diagnostics,
            "next_actions": next_actions or [],
        }

    def handle(self, request: dict, *, context: dict | None = None) -> dict:
        if not isinstance(request, dict):
            return self._response(
                "invalid",
                diagnostics=[self._diagnostic("REQUEST_SHAPE", "Request must be an object.")],
            )
        request_id = request.get("request_id", "missing-request-id")
        if request.get("protocol_version") != PROTOCOL_VERSION:
            return self._response(
                request_id,
                diagnostics=[self._diagnostic("PROTOCOL_VERSION", "Unsupported protocol version.")],
            )
        if not isinstance(request_id, str) or not request_id:
            return self._response(
                "invalid",
                diagnostics=[self._diagnostic("REQUEST_ID", "A non-empty request_id is required.")],
            )
        unexpected_request_fields = set(request) - {"protocol_version", "request_id", "tool", "arguments"}
        if unexpected_request_fields:
            return self._response(
                request_id,
                diagnostics=[self._diagnostic("REQUEST_FIELDS", "Request contains unknown envelope fields.")],
            )
        tool = request.get("tool")
        arguments = request.get("arguments")
        if not isinstance(tool, str) or not isinstance(arguments, dict):
            return self._response(
                request_id,
                diagnostics=[self._diagnostic("REQUEST_SHAPE", "tool and object arguments are required.")],
            )

        handlers = {
            "interface.describe": self._describe,
            "service.inspect": self._inspect,
            "service.propose": self._propose,
            "service.validate": self._validate,
            "service.plan": self._plan,
            "service.apply": self._apply,
        }
        handler = handlers.get(tool)
        if handler is None:
            return self._response(
                request_id,
                diagnostics=[self._diagnostic("UNKNOWN_TOOL", f"Tool {tool!r} is not exposed.")],
            )
        argument_contracts = {
            "interface.describe": (set(), {"name": str}),
            "service.inspect": ({"service_id"}, {"service_id": str, "operation": str}),
            "service.propose": ({"service_id", "base_revision", "ir"}, {"service_id": str, "base_revision": str, "ir": dict}),
            "service.validate": ({"change_set_id"}, {"change_set_id": str}),
            "service.plan": ({"change_set_id"}, {"change_set_id": str}),
            "service.apply": ({"change_set_id"}, {"change_set_id": str}),
        }
        required, allowed = argument_contracts[tool]
        if set(arguments) - set(allowed):
            return self._response(
                request_id,
                diagnostics=[self._diagnostic("ARGUMENT_FIELDS", "Arguments contain unknown fields.")],
            )
        if required - set(arguments):
            return self._response(
                request_id,
                diagnostics=[self._diagnostic("ARGUMENTS_REQUIRED", "Required tool arguments are missing.")],
            )
        if any(
            key in arguments and (
                not isinstance(arguments[key], expected_type)
                or (expected_type is str and not arguments[key].strip())
            )
            for key, expected_type in allowed.items()
        ):
            return self._response(
                request_id,
                diagnostics=[self._diagnostic("ARGUMENT_TYPE", "Tool arguments have invalid types or empty values.")],
            )
        try:
            result, next_actions = handler(arguments, context or {})
            return self._response(request_id, result=result, next_actions=next_actions)
        except InterfaceError as error:
            return self._response(
                request_id,
                diagnostics=[self._diagnostic(error.code, error.message, error.fix_hint)],
            )

    def _describe(self, arguments: dict, _context: dict):
        name = arguments.get("name")
        tools = self.catalog["tools"]
        if name is None:
            return (
                {
                    "protocol_version": PROTOCOL_VERSION,
                    "tools": [
                        {"name": item["name"], "summary": item["summary"], "mode": item["mode"]}
                        for item in tools
                    ],
                },
                ["interface.describe with a tool name to inspect its schema"],
            )
        for item in tools:
            if item["name"] == name:
                return item, []
        raise InterfaceError("UNKNOWN_TOOL", f"No schema is published for {name!r}.")

    def _inspect(self, arguments: dict, _context: dict):
        service_id = arguments.get("service_id")
        service = self.services.get(service_id)
        if service is None:
            raise InterfaceError("SERVICE_NOT_FOUND", f"Unknown service {service_id!r}.")
        operation_name = arguments.get("operation")
        if operation_name is None:
            return {
                "service": service["service"],
                "types": service["types"],
                "operations": [
                    {"name": op["name"], "method": op["method"], "path": op["path"]}
                    for op in service["operations"]
                ],
                "revision": digest(service),
            }, ["service.inspect with an operation name for its full contract"]
        for operation in service["operations"]:
            if operation["name"] == operation_name:
                return {"operation": operation, "revision": digest(service)}, []
        raise InterfaceError("OPERATION_NOT_FOUND", f"Unknown operation {operation_name!r}.")

    def _propose(self, arguments: dict, _context: dict):
        service_id = arguments.get("service_id")
        current = self.services.get(service_id)
        if current is None:
            raise InterfaceError("SERVICE_NOT_FOUND", f"Unknown service {service_id!r}.")
        base_revision = arguments.get("base_revision")
        if base_revision != digest(current):
            raise InterfaceError("STALE_BASE_REVISION", "Proposal base does not match current revision.")
        proposed_ir = arguments.get("ir")
        if not isinstance(proposed_ir, dict):
            raise InterfaceError("INVALID_PROPOSAL", "ir must be an object.")
        proposal = {
            "service_id": service_id,
            "base_revision": base_revision,
            "ir": copy.deepcopy(proposed_ir),
        }
        try:
            change_set_id = digest(proposal)
        except (TypeError, ValueError) as error:
            raise InterfaceError("INVALID_PROPOSAL", "IR must contain only finite JSON values.") from error
        self.proposals.setdefault(change_set_id, proposal)
        return {
            "change_set_id": change_set_id,
            "base_revision": base_revision,
            "immutable": True,
            "applied": False,
        }, ["service.validate with the change_set_id"]

    def _validate_ir(self, ir: dict) -> list[dict]:
        diagnostics = []
        try:
            validate_ir(ir)
        except Diagnostic as error:
            fix_hint = None
            if error.code == "AN021":
                fix_hint = (
                    "Submit a complete canonical IR snapshot, not a patch: the top-level object must contain "
                    "exactly ir_version (integer 1), service, types, and operations. Include all existing "
                    "operation declarations that must be preserved. Each operation.input must be an array "
                    "of {name, source, type} declarations."
                )
            diagnostics.append(self._diagnostic(error.code, error.message, fix_hint))
            return diagnostics
        except (TypeError, ValueError, KeyError, AttributeError, IndexError):
            diagnostics.append(self._diagnostic("INVALID_IR_SHAPE", "IR contains malformed nested values."))
            return diagnostics
        for operation in ir["operations"]:
            undeclared = set(operation["effects"]) - self.trusted_effects
            if undeclared:
                diagnostics.append(self._diagnostic(
                    "UNTRUSTED_EFFECT",
                    f"{operation['name']} requests effects outside the trusted allowlist: {', '.join(sorted(undeclared))}.",
                    "Remove the effect or submit a separately reviewed platform capability change.",
                ))
        return diagnostics

    def _validate(self, arguments: dict, _context: dict):
        change_set_id = arguments.get("change_set_id")
        proposal = self.proposals.get(change_set_id)
        if proposal is None:
            raise InterfaceError("CHANGE_SET_NOT_FOUND", "Unknown change_set_id.")
        diagnostics = self._validate_ir(proposal["ir"])
        if diagnostics:
            self.validated_change_sets.discard(change_set_id)
            self.planned_change_sets.discard(change_set_id)
        else:
            self.validated_change_sets.add(change_set_id)
        return {
            "change_set_id": change_set_id,
            "valid": not diagnostics,
            "diagnostics": diagnostics,
        }, ["service.plan with the change_set_id"] if not diagnostics else ["service.propose a corrected IR"]

    def _plan(self, arguments: dict, _context: dict):
        change_set_id = arguments.get("change_set_id")
        proposal = self.proposals.get(change_set_id)
        if proposal is None:
            raise InterfaceError("CHANGE_SET_NOT_FOUND", "Unknown change_set_id.")
        validation_diagnostics = self._validate_ir(proposal["ir"])
        structural_errors = [
            item for item in validation_diagnostics
            if item["code"] != "UNTRUSTED_EFFECT"
        ]
        if structural_errors:
            return {
                "change_set_id": change_set_id,
                "valid": False,
                "effects": [],
                "human_approval_required": False,
                "approval_reasons": [],
                "validation_diagnostics": structural_errors,
                "will_mutate": False,
                "will_deploy": False,
            }, ["service.propose a structurally valid IR"]
        effects = sorted({
            effect
            for operation in proposal["ir"]["operations"]
            for effect in operation["effects"]
        })
        approvals = sorted(set(effects) & HIGH_IMPACT_EFFECTS)
        sandbox_apply_ready = (
            self.apply_callback is not None
            and not validation_diagnostics
            and not approvals
            and change_set_id in self.validated_change_sets
        )
        if sandbox_apply_ready:
            self.planned_change_sets.add(change_set_id)
        else:
            self.planned_change_sets.discard(change_set_id)
        return {
            "change_set_id": change_set_id,
            "valid": not validation_diagnostics,
            "effects": effects,
            "human_approval_required": bool(approvals),
            "approval_reasons": approvals,
            "validation_diagnostics": validation_diagnostics,
            "will_mutate": sandbox_apply_ready,
            "will_deploy": False,
            "sandbox_only": self.apply_callback is not None,
        }, (
            ["service.apply in the isolated sandbox"]
            if sandbox_apply_ready
            else ["service.apply is disabled in this prototype"]
        )

    def _apply(self, arguments: dict, context: dict):
        if self.apply_callback is None:
            raise InterfaceError(
                "APPLY_DISABLED",
                "Applying changes is disabled outside the isolated sandbox.",
            )
        change_set_id = arguments.get("change_set_id")
        proposal = self.proposals.get(change_set_id)
        if proposal is None:
            raise InterfaceError("CHANGE_SET_NOT_FOUND", "Unknown change_set_id.")
        if change_set_id in self.applied_change_sets:
            return {
                **copy.deepcopy(self.applied_change_sets[change_set_id]),
                "replayed": True,
            }, ["service.inspect to verify the applied service revision"]
        if proposal["base_revision"] != self.revision(proposal["service_id"]):
            raise InterfaceError("STALE_BASE_REVISION", "The service changed after this proposal was created.")
        if change_set_id not in self.validated_change_sets or change_set_id not in self.planned_change_sets:
            raise InterfaceError(
                "APPLY_REQUIRES_VALIDATED_PLAN",
                "Apply requires a successful service.validate and a matching service.plan in this session.",
            )
        diagnostics = self._validate_ir(proposal["ir"])
        if diagnostics:
            raise InterfaceError("APPLY_VALIDATION_FAILED", "The proposed service no longer passes validation.")
        plan, _ = self._plan({"change_set_id": change_set_id}, context)
        if (
            not plan.get("valid")
            or not plan.get("will_mutate")
            or plan.get("human_approval_required")
            or plan.get("will_deploy")
        ):
            raise InterfaceError("APPLY_PLAN_NOT_ALLOWED", "The current plan is not eligible for isolated sandbox apply.")
        try:
            applied = self.apply_callback(copy.deepcopy(proposal), dict(context or {}))
        except Exception as error:
            raise InterfaceError("APPLY_FAILED", "The isolated sandbox apply failed closed.") from error
        if not isinstance(applied, dict) or applied.get("applied") is not True:
            raise InterfaceError("APPLY_FAILED", "The isolated sandbox did not confirm the apply.")
        self.services[proposal["service_id"]] = copy.deepcopy(proposal["ir"])
        result = {
            **copy.deepcopy(applied),
            "change_set_id": change_set_id,
            "applied": True,
            "replayed": False,
        }
        self.applied_change_sets[change_set_id] = result
        return result, ["service.inspect to verify the applied service revision"]


class InterfaceError(Exception):
    def __init__(self, code: str, message: str, fix_hint: str | None = None):
        self.code = code
        self.message = message
        self.fix_hint = fix_hint
        super().__init__(message)
