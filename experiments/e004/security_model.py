from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable


@dataclass(frozen=True)
class Grant:
    principal_id: str
    tenant_id: str
    capability: str
    resource_prefix: str | None = None
    expires_at: int | None = None
    delegation_depth: int = 0

    def __post_init__(self) -> None:
        if not self.principal_id or not self.tenant_id or not self.capability:
            raise ValueError("grant_identity_tenant_and_capability_required")
        if self.resource_prefix is not None and not _valid_resource(self.resource_prefix):
            raise ValueError("invalid_grant_resource_prefix")
        if self.expires_at is not None and self.expires_at < 0:
            raise ValueError("invalid_grant_expiry")
        if self.delegation_depth < 0:
            raise ValueError("invalid_delegation_depth")


@dataclass(frozen=True)
class OperationContract:
    name: str
    required_capability: str
    allowed_effects: frozenset[str]


@dataclass(frozen=True)
class RequestContext:
    principal_id: str | None
    tenant_id: str | None
    now: int
    grants: tuple[Grant, ...]


@dataclass(frozen=True)
class Decision:
    allowed: bool
    reason_code: str
    audit_event: dict[str, object]


def _valid_resource(resource: str) -> bool:
    if not resource.startswith("/") or "//" in resource or "?" in resource or "#" in resource:
        return False
    return all(segment not in {".", ".."} for segment in resource.split("/"))


def _resource_matches(resource: str, prefix: str | None) -> bool:
    if prefix is None:
        return True
    normalized = prefix.rstrip("/") or "/"
    return resource == normalized or resource.startswith(normalized.rstrip("/") + "/")


def _scope_is_attenuated(candidate: str | None, parent: str | None) -> bool:
    if parent is None:
        return True
    if candidate is None:
        return False
    parent = parent.rstrip("/") or "/"
    candidate = candidate.rstrip("/") or "/"
    return candidate == parent or candidate.startswith(parent.rstrip("/") + "/")


def attenuate(
    grant: Grant,
    *,
    delegate_principal_id: str,
    resource_prefix: str | None,
    expires_at: int | None,
) -> Grant:
    if not delegate_principal_id:
        raise ValueError("delegate_identity_required")
    if grant.delegation_depth <= 0:
        raise ValueError("delegation_depth_exhausted")
    if not _scope_is_attenuated(resource_prefix, grant.resource_prefix):
        raise ValueError("resource_scope_widening")
    if grant.expires_at is not None and (
        expires_at is None or expires_at > grant.expires_at
    ):
        raise ValueError("expiry_extension")
    scope_narrowed = resource_prefix != grant.resource_prefix
    expiry_narrowed = expires_at != grant.expires_at
    if not (scope_narrowed or expiry_narrowed):
        raise ValueError("no_authority_attenuation")
    return Grant(
        principal_id=delegate_principal_id,
        tenant_id=grant.tenant_id,
        capability=grant.capability,
        resource_prefix=resource_prefix,
        expires_at=expires_at,
        delegation_depth=grant.delegation_depth - 1,
    )


class PolicyEngine:
    def authorize(
        self,
        operation: OperationContract,
        *,
        resource: str,
        requested_effects: Iterable[str],
        context: RequestContext,
    ) -> Decision:
        effects = frozenset(requested_effects)
        reason = "ALLOW"

        if not context.principal_id or not context.tenant_id:
            reason = "MISSING_IDENTITY"
        elif not operation.required_capability:
            reason = "INVALID_OPERATION_CONTRACT"
        elif not _valid_resource(resource):
            reason = "INVALID_RESOURCE"
        elif not effects.issubset(operation.allowed_effects):
            reason = "UNDECLARED_EFFECT"
        else:
            principal_grants = [
                grant
                for grant in context.grants
                if grant.principal_id == context.principal_id
                and grant.capability == operation.required_capability
            ]
            tenant_grants = [
                grant for grant in principal_grants
                if grant.tenant_id == context.tenant_id
            ]
            if not tenant_grants:
                reason = "TENANT_MISMATCH" if principal_grants else "MISSING_CAPABILITY"
            else:
                live_grants = [
                    grant for grant in tenant_grants
                    if grant.expires_at is None or context.now < grant.expires_at
                ]
                if not live_grants:
                    reason = "EXPIRED_GRANT"
                elif not any(
                    _resource_matches(resource, grant.resource_prefix)
                    for grant in live_grants
                ):
                    reason = "RESOURCE_SCOPE"

        event = {
            "principal_id": context.principal_id,
            "tenant_id": context.tenant_id,
            "operation": operation.name,
            "resource": resource,
            "requested_effects": sorted(effects),
            "decision": "allow" if reason == "ALLOW" else "deny",
            "reason_code": reason,
        }
        return Decision(allowed=reason == "ALLOW", reason_code=reason, audit_event=event)
