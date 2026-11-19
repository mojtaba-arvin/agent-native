"""Proposal, validation, and planning gateway with no apply surface."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Mapping
from urllib.parse import quote

from ..manifest import RegisteredService, ServiceRegistry, ServiceRegistryError
from ..runtime import validate_operation_inputs
from ..security import OperationContract, PolicyEngine, RequestContext
from ..authz.effects import classify_effects


class GatewayError(ValueError):
    def __init__(self, code: str, message: str | None = None):
        self.code = code
        super().__init__(message or code)


@dataclass(frozen=True)
class Proposal:
    service_id: str
    service_name: str
    service_version: str
    operation_name: str
    method: str
    resource: str
    inputs: Mapping[str, Any]
    required_capability: str
    effects: tuple[str, ...]
    effect_mode: str
    candidate_sha256: str
    proposal_sha256: str
    no_apply: bool = True


@dataclass(frozen=True)
class ValidationResult:
    service_id: str
    operation_name: str
    proposal_sha256: str
    candidate_sha256: str
    required_capability: str
    effects: tuple[str, ...]
    effect_mode: str
    allowed: bool = True


@dataclass(frozen=True)
class Plan:
    service_id: str
    operation_name: str
    method: str
    resource: str
    inputs: Mapping[str, Any]
    required_capability: str
    effects: tuple[str, ...]
    effect_mode: str
    candidate_sha256: str
    proposal_sha256: str
    plan_sha256: str
    no_apply: bool = True
    apply_endpoint_exposed: bool = False


def _freeze_json(value: Any) -> Any:
    """Recursively freeze JSON containers exposed by proposal and plan objects."""
    if isinstance(value, Mapping):
        return MappingProxyType({key: _freeze_json(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze_json(item) for item in value)
    return value


def _thaw_json(value: Any) -> Any:
    """Return ordinary JSON containers from the immutable public representation."""
    if isinstance(value, Mapping):
        return {key: _thaw_json(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_thaw_json(item) for item in value]
    return value


def _canonical_hash(value: Mapping[str, Any]) -> str:
    try:
        encoded = json.dumps(
            _thaw_json(value),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
    except (TypeError, ValueError) as error:
        raise GatewayError("NON_CANONICAL_INPUT", "proposal inputs must be finite JSON values") from error
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _render_resource_path(path_template: str, inputs: Mapping[str, Any]) -> str:
    def replace(match: re.Match[str]) -> str:
        name = match.group(1)
        if name not in inputs:
            raise GatewayError("INVALID_INPUT", f"missing path input: {name}")
        value = inputs[name]
        if not isinstance(value, (str, int)) or isinstance(value, bool):
            raise GatewayError("INVALID_INPUT", f"path input {name} must be a string or integer")
        return quote(str(value), safe="")

    resource = re.sub(r"\{([A-Za-z_][A-Za-z0-9_]*)\}", replace, path_template)
    if "{" in resource or "}" in resource:
        raise GatewayError("INVALID_OPERATION_PATH")
    return resource


class AgentGateway:
    """Service-independent, no-side-effect proposal and planning interface."""

    def __init__(self, service_registry: ServiceRegistry, policy_engine: PolicyEngine | None = None):
        self.service_registry = service_registry
        self.policy_engine = policy_engine or PolicyEngine()

    def resolve_service(self, service_id: str) -> RegisteredService:
        if not isinstance(service_id, str) or not service_id:
            raise GatewayError("INVALID_SERVICE_ID")
        try:
            service = self.service_registry.load(service_id)
        except ServiceRegistryError as error:
            raise GatewayError("SERVICE_REGISTRY_ERROR", str(error)) from error
        if service.service_id != service_id:
            raise GatewayError("SERVICE_IDENTITY_MISMATCH")
        return service

    def _operation(self, service: RegisteredService, operation_name: str) -> Mapping[str, Any]:
        operation = next((item for item in service.ir["operations"] if item["name"] == operation_name), None)
        if operation is None:
            raise GatewayError("UNSUPPORTED_OPERATION")
        return operation

    def _authorize(
        self,
        service: RegisteredService,
        operation: Mapping[str, Any],
        resource: str,
        identity: RequestContext,
    ) -> tuple[str, tuple[str, ...], str]:
        effects = tuple(sorted(operation["effects"]))
        try:
            effect_mode = classify_effects(effects)
        except ValueError as error:
            raise GatewayError("UNSUPPORTED_EFFECT", str(error)) from error
        if not set(effects).issubset(set(service.policy["effects"])):
            raise GatewayError("POLICY_EFFECT_NOT_ALLOWED")
        capability = operation["capability"]
        if capability not in service.policy["capabilities"]:
            raise GatewayError("POLICY_CAPABILITY_NOT_ALLOWED")
        contract = OperationContract(
            name=operation["name"],
            required_capability=capability,
            allowed_effects=frozenset(effects),
        )
        decision = self.policy_engine.authorize(
            contract,
            resource=resource,
            requested_effects=effects,
            context=identity,
        )
        if not decision.allowed:
            raise GatewayError(decision.reason_code)
        return capability, effects, effect_mode

    def propose(
        self,
        service_id: str,
        operation_name: str,
        inputs: Mapping[str, Any],
        identity: RequestContext,
    ) -> Proposal:
        service = self.resolve_service(service_id)
        operation = self._operation(service, operation_name)
        try:
            normalized_inputs = validate_operation_inputs(service.ir, operation_name, dict(inputs))
        except (TypeError, ValueError) as error:
            raise GatewayError("INVALID_INPUT", str(error)) from error
        resource = _render_resource_path(operation["path"], normalized_inputs)
        capability, effects, effect_mode = self._authorize(service, operation, resource, identity)
        candidate = {
            "service_id": service.service_id,
            "service_name": service.service_name,
            "service_version": service.version,
            "operation_name": operation_name,
            "method": operation["method"],
            "resource": resource,
            "inputs": normalized_inputs,
            "required_capability": capability,
            "effects": list(effects),
            "effect_mode": effect_mode,
        }
        candidate_hash = _canonical_hash(candidate)
        proposal_payload = {**candidate, "candidate_sha256": candidate_hash, "no_apply": True}
        proposal_hash = _canonical_hash(proposal_payload)
        return Proposal(
            service_id=service.service_id,
            service_name=service.service_name,
            service_version=service.version,
            operation_name=operation_name,
            method=operation["method"],
            resource=resource,
            inputs=_freeze_json(normalized_inputs),
            required_capability=capability,
            effects=effects,
            effect_mode=effect_mode,
            candidate_sha256=candidate_hash,
            proposal_sha256=proposal_hash,
        )

    def validate(self, proposal: Proposal, identity: RequestContext) -> ValidationResult:
        if not isinstance(proposal, Proposal) or proposal.no_apply is not True:
            raise GatewayError("INVALID_PROPOSAL")
        service = self.resolve_service(proposal.service_id)
        if proposal.service_name != service.service_name or proposal.service_version != service.version:
            raise GatewayError("SERVICE_IDENTITY_MISMATCH")
        operation = self._operation(service, proposal.operation_name)
        try:
            inputs = validate_operation_inputs(service.ir, proposal.operation_name, _thaw_json(proposal.inputs))
        except (TypeError, ValueError) as error:
            raise GatewayError("INVALID_INPUT", str(error)) from error
        resource = _render_resource_path(operation["path"], inputs)
        expected_effects = tuple(sorted(operation["effects"]))
        try:
            effect_mode = classify_effects(proposal.effects)
        except ValueError as error:
            raise GatewayError("UNSUPPORTED_EFFECT", str(error)) from error
        if tuple(sorted(proposal.effects)) != expected_effects:
            raise GatewayError("UNSUPPORTED_EFFECT")
        if (
            proposal.method != operation["method"]
            or proposal.resource != resource
            or proposal.required_capability != operation["capability"]
            or proposal.effect_mode != effect_mode
        ):
            raise GatewayError("PROPOSAL_CONTRACT_MISMATCH")
        capability, effects, effect_mode = self._authorize(service, operation, resource, identity)
        candidate = {
            "service_id": service.service_id,
            "service_name": service.service_name,
            "service_version": service.version,
            "operation_name": proposal.operation_name,
            "method": operation["method"],
            "resource": resource,
            "inputs": inputs,
            "required_capability": capability,
            "effects": list(effects),
            "effect_mode": effect_mode,
        }
        candidate_hash = _canonical_hash(candidate)
        proposal_hash = _canonical_hash({**candidate, "candidate_sha256": candidate_hash, "no_apply": True})
        if proposal.candidate_sha256 != candidate_hash or proposal.proposal_sha256 != proposal_hash:
            raise GatewayError("PROPOSAL_HASH_MISMATCH")
        return ValidationResult(
            service_id=service.service_id,
            operation_name=proposal.operation_name,
            proposal_sha256=proposal_hash,
            candidate_sha256=candidate_hash,
            required_capability=capability,
            effects=effects,
            effect_mode=effect_mode,
        )

    def plan(self, proposal: Proposal, validation: ValidationResult, identity: RequestContext) -> Plan:
        if not isinstance(validation, ValidationResult) or not validation.allowed:
            raise GatewayError("VALIDATION_REQUIRED")
        fresh = self.validate(proposal, identity)
        if fresh.proposal_sha256 != validation.proposal_sha256:
            raise GatewayError("VALIDATION_STALE")
        plan_payload = {
            "service_id": proposal.service_id,
            "operation_name": proposal.operation_name,
            "method": proposal.method,
            "resource": proposal.resource,
            "inputs": _thaw_json(proposal.inputs),
            "required_capability": proposal.required_capability,
            "effects": list(proposal.effects),
            "effect_mode": proposal.effect_mode,
            "candidate_sha256": proposal.candidate_sha256,
            "proposal_sha256": proposal.proposal_sha256,
            "no_apply": True,
            "apply_endpoint_exposed": False,
        }
        plan_hash = _canonical_hash(plan_payload)
        return Plan(
            service_id=proposal.service_id,
            operation_name=proposal.operation_name,
            method=proposal.method,
            resource=proposal.resource,
            inputs=_freeze_json(_thaw_json(proposal.inputs)),
            required_capability=proposal.required_capability,
            effects=proposal.effects,
            effect_mode=proposal.effect_mode,
            candidate_sha256=proposal.candidate_sha256,
            proposal_sha256=proposal.proposal_sha256,
            plan_sha256=plan_hash,
        )
