from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path


PROTOCOL_VERSION = "0.1"
HIGH_IMPACT_EFFECTS = frozenset({
    "network.egress",
    "secrets.read",
    "database.drop",
    "production.deploy",
})


def canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def digest(value: object) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


class AgentInterface:
    def __init__(self, services: dict[str, dict], *, trusted_effects: set[str]):
        self.services = copy.deepcopy(services)
        self.trusted_effects = frozenset(trusted_effects)
        self.proposals: dict[str, dict] = {}
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
        change_set_id = digest(proposal)
        self.proposals.setdefault(change_set_id, proposal)
        return {
            "change_set_id": change_set_id,
            "base_revision": base_revision,
            "immutable": True,
            "applied": False,
        }, ["service.validate with the change_set_id"]

    def _validate_ir(self, ir: dict) -> list[dict]:
        diagnostics = []
        if not {"service", "types", "operations"}.issubset(ir):
            return [self._diagnostic("IR_SHAPE", "IR must contain service, types, and operations.")]
        if not isinstance(ir["operations"], list) or not ir["operations"]:
            diagnostics.append(self._diagnostic("IR_OPERATIONS", "At least one operation is required."))
            return diagnostics
        names = set()
        for operation in ir["operations"]:
            name = operation.get("name")
            if not name or name in names:
                diagnostics.append(self._diagnostic("DUPLICATE_OPERATION", "Operation names must be unique."))
                continue
            names.add(name)
            if not operation.get("capability"):
                diagnostics.append(self._diagnostic("CAPABILITY_REQUIRED", f"{name} has no capability."))
            undeclared = set(operation.get("effects", [])) - self.trusted_effects
            if undeclared:
                diagnostics.append(self._diagnostic(
                    "UNTRUSTED_EFFECT",
                    f"{name} requests effects outside the trusted allowlist: {', '.join(sorted(undeclared))}.",
                    "Remove the effect or submit a separately reviewed platform capability change.",
                ))
            if "errors" not in operation or "validation" not in operation:
                diagnostics.append(self._diagnostic("CONTRACT_INCOMPLETE", f"{name} lacks errors or validation."))
        return diagnostics

    def _validate(self, arguments: dict, _context: dict):
        change_set_id = arguments.get("change_set_id")
        proposal = self.proposals.get(change_set_id)
        if proposal is None:
            raise InterfaceError("CHANGE_SET_NOT_FOUND", "Unknown change_set_id.")
        diagnostics = self._validate_ir(proposal["ir"])
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
        effects = sorted({
            effect
            for operation in proposal["ir"].get("operations", [])
            for effect in operation.get("effects", [])
        })
        approvals = sorted(set(effects) & HIGH_IMPACT_EFFECTS)
        return {
            "change_set_id": change_set_id,
            "effects": effects,
            "human_approval_required": bool(approvals),
            "approval_reasons": approvals,
            "will_mutate": False,
            "will_deploy": False,
        }, ["service.apply is disabled in this prototype"]

    def _apply(self, arguments: dict, _context: dict):
        raise InterfaceError(
            "APPLY_DISABLED",
            "Applying changes is disabled in this prototype; no state or production mutation is possible.",
        )


class InterfaceError(Exception):
    def __init__(self, code: str, message: str, fix_hint: str | None = None):
        self.code = code
        self.message = message
        self.fix_hint = fix_hint
        super().__init__(message)
