from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable
import unicodedata


@dataclass(frozen=True)
class Grant:
    principal_id: str
    tenant_id: str
    capability: str
    resource_prefix: str | None = None
    expires_at: int | None = None
    delegation_depth: int = 0

    def __post_init__(self) -> None:
        identities = (self.principal_id, self.tenant_id, self.capability)
        if any(not isinstance(value, str) or not value.strip() for value in identities):
            raise ValueError("grant_identity_tenant_and_capability_required")
        if self.resource_prefix is not None and not _valid_resource(self.resource_prefix):
            raise ValueError("invalid_grant_resource_prefix")
        if self.expires_at is not None and (
            not isinstance(self.expires_at, int)
            or isinstance(self.expires_at, bool)
            or self.expires_at < 0
        ):
            raise ValueError("invalid_grant_expiry")
        if (
            not isinstance(self.delegation_depth, int)
            or isinstance(self.delegation_depth, bool)
            or self.delegation_depth < 0
        ):
            raise ValueError("invalid_delegation_depth")


@dataclass(frozen=True)
class OperationContract:
    name: str
    required_capability: str
    allowed_effects: frozenset[str]

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not self.name.strip():
            raise ValueError("operation_name_required")
        if not isinstance(self.required_capability, str) or not self.required_capability.strip():
            raise ValueError("operation_capability_required")
        if not isinstance(self.allowed_effects, frozenset) or any(
            not isinstance(effect, str) or not effect.strip()
            for effect in self.allowed_effects
        ):
            raise ValueError("invalid_operation_effects")


@dataclass(frozen=True)
class RequestContext:
    principal_id: str | None
    tenant_id: str | None
    now: int
    grants: tuple[Grant, ...]

    def __post_init__(self) -> None:
        for name, value in (("principal_id", self.principal_id), ("tenant_id", self.tenant_id)):
            if value is not None and (not isinstance(value, str) or not value.strip()):
                raise ValueError(f"invalid_{name}")
        if not isinstance(self.now, int) or isinstance(self.now, bool) or self.now < 0:
            raise ValueError("invalid_trusted_time")
        if not isinstance(self.grants, tuple) or any(not isinstance(grant, Grant) for grant in self.grants):
            raise ValueError("request_grants_must_be_a_tuple_of_grants")


@dataclass(frozen=True)
class Decision:
    allowed: bool
    reason_code: str
    audit_event: dict[str, object]


def _valid_resource(resource: str) -> bool:
    if (
        not isinstance(resource, str)
        or not resource.startswith("/")
        or "//" in resource
        or "?" in resource
        or "#" in resource
        or "%" in resource
        or chr(92) in resource
        or any(ord(character) < 0x20 or ord(character) == 0x7F for character in resource)
        or unicodedata.normalize("NFC", resource) != resource
    ):
        return False
    return all(segment not in {".", ".."} for segment in resource.split("/"))


def _resource_matches(resource: str, prefix: str | None) -> bool:
    if prefix is None:
        return True
    normalized = prefix.rstrip("/") or "/"
    return resource == normalized or resource.startswith(normalized.rstrip("/") + "/")


def _normalize_scope(resource_prefix: str | None) -> str | None:
    if resource_prefix is None:
        return None
    return resource_prefix.rstrip("/") or "/"


def _scope_is_attenuated(candidate: str | None, parent: str | None) -> bool:
    if parent is None:
        return True
    if candidate is None:
        return False
    return candidate == parent or candidate.startswith(parent.rstrip("/") + "/")


def attenuate(
    grant: Grant,
    *,
    delegate_principal_id: str,
    resource_prefix: str | None,
    expires_at: int | None,
) -> Grant:
    if not isinstance(delegate_principal_id, str) or not delegate_principal_id.strip():
        raise ValueError("delegate_identity_required")
    if grant.delegation_depth <= 0:
        raise ValueError("delegation_depth_exhausted")
    if resource_prefix is not None and not _valid_resource(resource_prefix):
        raise ValueError("invalid_delegated_resource_prefix")
    parent_scope = _normalize_scope(grant.resource_prefix)
    candidate_scope = _normalize_scope(resource_prefix)
    if not _scope_is_attenuated(candidate_scope, parent_scope):
        raise ValueError("resource_scope_widening")
    if grant.expires_at is not None and (
        expires_at is None or expires_at > grant.expires_at
    ):
        raise ValueError("expiry_extension")
    scope_narrowed = candidate_scope != parent_scope
    expiry_narrowed = expires_at != grant.expires_at
    if not (scope_narrowed or expiry_narrowed):
        raise ValueError("no_authority_attenuation")
    return Grant(
        principal_id=delegate_principal_id,
        tenant_id=grant.tenant_id,
        capability=grant.capability,
        resource_prefix=candidate_scope,
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
        try:
            effects = frozenset(requested_effects)
            effects_valid = all(
                isinstance(effect, str) and bool(effect.strip())
                for effect in effects
            )
        except (TypeError, ValueError):
            effects = frozenset()
            effects_valid = False
        reason = "ALLOW"

        if not effects_valid:
            reason = "INVALID_EFFECTS"
        elif not context.principal_id or not context.tenant_id:
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


class AuthenticationError(ValueError):
    """A bearer credential is missing, malformed, invalid, or no longer valid."""


def _b64url_encode(value: bytes) -> str:
    import base64
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _b64url_decode(value: str) -> bytes:
    import base64
    import re
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]+", value):
        raise AuthenticationError("invalid_token_encoding")
    try:
        decoded = base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
    except Exception:
        raise AuthenticationError("invalid_token_encoding") from None
    if _b64url_encode(decoded) != value:
        raise AuthenticationError("noncanonical_token_encoding")
    return decoded


def _unique_json_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise AuthenticationError("duplicate_token_claim")
        result[key] = value
    return result


class CapabilityTokenAuthority:
    """Issue and verify short-lived HMAC-signed capability bearer tokens.

    The signing key is an application secret and must be shared only by trusted
    issuers/verifiers. Token claims never accept caller-supplied identity from
    request bodies or query parameters.
    """

    _HEADER = {"alg": "HS256", "typ": "AN-CAP", "v": 1}
    _GRANT_KEYS = {"capability", "resource_prefix", "expires_at", "delegation_depth"}
    _CLAIM_KEYS = {"v", "iss", "aud", "sub", "tid", "iat", "exp", "grants"}

    def __init__(
        self,
        signing_key: bytes,
        *,
        issuer: str = "agent-native",
        audience: str = "agent-native-api",
        clock=None,
        max_ttl_seconds: int = 900,
        clock_skew_seconds: int = 0,
    ):
        if not isinstance(signing_key, bytes) or len(signing_key) < 32:
            raise ValueError("capability_signing_key_must_be_at_least_32_bytes")
        if not isinstance(issuer, str) or not issuer.strip():
            raise ValueError("token_issuer_required")
        if not isinstance(audience, str) or not audience.strip():
            raise ValueError("token_audience_required")
        if type(max_ttl_seconds) is not int or not 1 <= max_ttl_seconds <= 86400:
            raise ValueError("invalid_max_token_ttl")
        if type(clock_skew_seconds) is not int or not 0 <= clock_skew_seconds <= 60:
            raise ValueError("invalid_token_clock_skew")
        self._key = signing_key
        self.issuer = issuer
        self.audience = audience
        self.clock = clock or (lambda: int(__import__("time").time()))
        self.max_ttl_seconds = max_ttl_seconds
        self.clock_skew_seconds = clock_skew_seconds

    def issue_token(
        self,
        principal_id: str,
        tenant_id: str,
        grants: Iterable[Grant],
        *,
        ttl_seconds: int = 300,
    ) -> str:
        import hashlib
        import hmac
        import json
        if not isinstance(principal_id, str) or not principal_id.strip():
            raise ValueError("principal_identity_required")
        if not isinstance(tenant_id, str) or not tenant_id.strip():
            raise ValueError("tenant_identity_required")
        if type(ttl_seconds) is not int or not 1 <= ttl_seconds <= self.max_ttl_seconds:
            raise ValueError("invalid_token_ttl")
        if not isinstance(grants, (tuple, list)) or len(grants) > 128:
            raise ValueError("invalid_token_grants")
        now = self.clock()
        if type(now) is not int or now < 0:
            raise ValueError("invalid_trusted_time")
        encoded_grants = []
        for grant in grants:
            if not isinstance(grant, Grant):
                raise ValueError("token_grants_must_be_grants")
            if grant.principal_id != principal_id or grant.tenant_id != tenant_id:
                raise ValueError("token_grant_identity_mismatch")
            encoded_grants.append({
                "capability": grant.capability,
                "resource_prefix": grant.resource_prefix,
                "expires_at": grant.expires_at,
                "delegation_depth": grant.delegation_depth,
            })
        claims = {
            "v": 1,
            "iss": self.issuer,
            "aud": self.audience,
            "sub": principal_id,
            "tid": tenant_id,
            "iat": now,
            "exp": now + ttl_seconds,
            "grants": encoded_grants,
        }
        header_part = _b64url_encode(json.dumps(
            self._HEADER, sort_keys=True, separators=(",", ":")
        ).encode("utf-8"))
        claims_part = _b64url_encode(json.dumps(
            claims, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode("utf-8"))
        signing_input = (header_part + "." + claims_part).encode("ascii")
        signature = hmac.new(self._key, signing_input, hashlib.sha256).digest()
        return header_part + "." + claims_part + "." + _b64url_encode(signature)

    def authenticate(self, authorization: str | None) -> RequestContext:
        import hashlib
        import hmac
        import json
        import re
        if not isinstance(authorization, str):
            raise AuthenticationError("missing_bearer_token")
        match = re.fullmatch(r"Bearer ([A-Za-z0-9_.-]+)", authorization)
        if match is None:
            raise AuthenticationError("invalid_authorization_scheme")
        token = match.group(1)
        if len(token) > 8192:
            raise AuthenticationError("token_too_large")
        parts = token.split(".")
        if len(parts) != 3:
            raise AuthenticationError("malformed_token")
        header_part, claims_part, signature_part = parts
        signing_input = (header_part + "." + claims_part).encode("ascii")
        expected = hmac.new(self._key, signing_input, hashlib.sha256).digest()
        supplied = _b64url_decode(signature_part)
        if not hmac.compare_digest(expected, supplied):
            raise AuthenticationError("invalid_token_signature")
        try:
            header = json.loads(
                _b64url_decode(header_part).decode("utf-8"),
                object_pairs_hook=_unique_json_object,
            )
            claims = json.loads(
                _b64url_decode(claims_part).decode("utf-8"),
                object_pairs_hook=_unique_json_object,
            )
        except AuthenticationError:
            raise
        except (ValueError, UnicodeDecodeError):
            raise AuthenticationError("invalid_token_payload") from None
        if not isinstance(header, dict) or header != self._HEADER:
            raise AuthenticationError("unsupported_token_header")
        if not isinstance(claims, dict) or set(claims) != self._CLAIM_KEYS:
            raise AuthenticationError("invalid_token_claims")
        if (
            type(claims["v"]) is not int or claims["v"] != 1
            or claims["iss"] != self.issuer
            or claims["aud"] != self.audience
            or not isinstance(claims["sub"], str) or not claims["sub"].strip()
            or not isinstance(claims["tid"], str) or not claims["tid"].strip()
            or type(claims["iat"]) is not int
            or type(claims["exp"]) is not int
            or not isinstance(claims["grants"], list)
            or len(claims["grants"]) > 128
        ):
            raise AuthenticationError("invalid_token_claims")
        now = self.clock()
        if type(now) is not int or now < 0:
            raise AuthenticationError("trusted_clock_unavailable")
        issued_at, expires_at = claims["iat"], claims["exp"]
        if (
            issued_at > now + self.clock_skew_seconds
            or expires_at <= now
            or expires_at <= issued_at
            or expires_at - issued_at > self.max_ttl_seconds
        ):
            raise AuthenticationError("token_expired_or_outside_validity_window")
        grants = []
        for item in claims["grants"]:
            if not isinstance(item, dict) or set(item) != self._GRANT_KEYS:
                raise AuthenticationError("invalid_token_grant")
            try:
                grant = Grant(
                    principal_id=claims["sub"],
                    tenant_id=claims["tid"],
                    capability=item["capability"],
                    resource_prefix=item["resource_prefix"],
                    expires_at=item["expires_at"],
                    delegation_depth=item["delegation_depth"],
                )
            except (TypeError, ValueError):
                raise AuthenticationError("invalid_token_grant") from None
            if grant.expires_at is not None and grant.expires_at <= now:
                continue
            grants.append(grant)
        return RequestContext(
            principal_id=claims["sub"],
            tenant_id=claims["tid"],
            now=now,
            grants=tuple(grants),
        )
