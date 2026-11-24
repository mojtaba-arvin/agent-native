#!/usr/bin/env python3
"""Issue and verify compact HMAC-SHA256 capability bearer tokens for T16."""
from __future__ import annotations

import hashlib
import hmac
import re
import time
from typing import Iterable

ISSUER = "agent-native"
AUDIENCE = "agent-native-api"
MAX_TTL_SECONDS = 900
_VERSION = "AN-CAP-V1"
_IDENTITY = re.compile(r"[A-Za-z0-9_-]{1,128}\Z")
_CAPABILITY = re.compile(r"[A-Za-z0-9._-]{1,128}\Z")


def _valid_resource_prefix(value: str) -> bool:
    if not isinstance(value, str) or not value.startswith("/"):
        return False
    if any(char in value for char in ("|", "~", ",", "?", "#", "%", "\\")) or "//" in value:
        return False
    if any(ord(char) < 0x20 or ord(char) == 0x7F for char in value):
        return False
    return all(segment not in {".", ".."} for segment in value.split("/"))


def issue_token(
    key_hex: str,
    principal_id: str,
    tenant_id: str,
    grants: Iterable[tuple[str, str, int | None, int]],
    *,
    ttl_seconds: int = 600,
    now: int | None = None,
) -> str:
    try:
        key = bytes.fromhex(key_hex)
    except ValueError as error:
        raise ValueError("signing_key_must_be_hex") from error
    if len(key) < 32:
        raise ValueError("signing_key_must_be_at_least_32_bytes")
    if not _IDENTITY.fullmatch(principal_id) or not _IDENTITY.fullmatch(tenant_id):
        raise ValueError("invalid_token_identity")
    if type(ttl_seconds) is not int or not 1 <= ttl_seconds <= MAX_TTL_SECONDS:
        raise ValueError("invalid_token_ttl")
    issued_at = int(time.time()) if now is None else now
    if type(issued_at) is not int or issued_at < 0:
        raise ValueError("invalid_token_issue_time")
    encoded_grants = []
    for capability, resource_prefix, expires_at, delegation_depth in grants:
        if not _CAPABILITY.fullmatch(capability) or not _valid_resource_prefix(resource_prefix):
            raise ValueError("invalid_token_grant")
        if expires_at is not None and (type(expires_at) is not int or expires_at < 0):
            raise ValueError("invalid_token_grant_expiry")
        if type(delegation_depth) is not int or delegation_depth < 0:
            raise ValueError("invalid_token_delegation_depth")
        encoded_grants.append("~".join((
            capability, resource_prefix,
            "-" if expires_at is None else str(expires_at),
            str(delegation_depth),
        )))
    if not encoded_grants or len(encoded_grants) > 128:
        raise ValueError("invalid_token_grants")
    payload = "|".join((
        _VERSION, ISSUER, AUDIENCE, str(issued_at),
        str(issued_at + ttl_seconds), principal_id, tenant_id, ",".join(encoded_grants),
    ))
    signature = hmac.new(key, payload.encode("ascii"), hashlib.sha256).hexdigest()
    return payload + "." + signature


def verify_token(token: str, key_hex: str, *, now: int | None = None) -> dict:
    try:
        key = bytes.fromhex(key_hex)
    except ValueError as error:
        raise ValueError("signing_key_must_be_hex") from error
    if len(key) < 32:
        raise ValueError("signing_key_must_be_at_least_32_bytes")
    if not isinstance(token, str) or len(token) > 8192 or "." not in token:
        raise ValueError("malformed_token")
    payload, supplied = token.rsplit(".", 1)
    if not re.fullmatch(r"[0-9a-f]{64}", supplied):
        raise ValueError("invalid_token_signature_encoding")
    expected = hmac.new(key, payload.encode("ascii"), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, supplied):
        raise ValueError("invalid_token_signature")
    fields = payload.split("|")
    if len(fields) != 8 or fields[:3] != [_VERSION, ISSUER, AUDIENCE]:
        raise ValueError("invalid_token_claims")
    _, _, _, issued_text, expires_text, principal, tenant, grants_text = fields
    if not _IDENTITY.fullmatch(principal) or not _IDENTITY.fullmatch(tenant):
        raise ValueError("invalid_token_identity")
    try:
        issued_at, expires_at = int(issued_text), int(expires_text)
    except ValueError as error:
        raise ValueError("invalid_token_time") from error
    current = int(time.time()) if now is None else now
    if issued_at > current or expires_at <= current or expires_at <= issued_at or expires_at - issued_at > MAX_TTL_SECONDS:
        raise ValueError("token_expired_or_outside_validity_window")
    grants = []
    for item in grants_text.split(","):
        parts = item.split("~")
        if len(parts) != 4:
            raise ValueError("invalid_token_grant")
        capability, resource_prefix, grant_expiry, depth_text = parts
        if not _CAPABILITY.fullmatch(capability) or not _valid_resource_prefix(resource_prefix):
            raise ValueError("invalid_token_grant")
        try:
            grant_expires = None if grant_expiry == "-" else int(grant_expiry)
            depth = int(depth_text)
        except ValueError as error:
            raise ValueError("invalid_token_grant") from error
        if (grant_expires is not None and grant_expires < 0) or depth < 0:
            raise ValueError("invalid_token_grant")
        grants.append({
            "capability": capability, "resource_prefix": resource_prefix,
            "expires_at": grant_expires, "delegation_depth": depth,
        })
    if not grants or len(grants) > 128:
        raise ValueError("invalid_token_grants")
    return {
        "issuer": ISSUER, "audience": AUDIENCE, "issued_at": issued_at,
        "expires_at": expires_at, "principal_id": principal,
        "tenant_id": tenant, "grants": grants,
    }


def issue_benchmark_tokens(key_hex: str, *, now: int | None = None) -> tuple[str, str]:
    reader = issue_token(
        key_hex, "benchmark-reader", "tenant-a",
        (("catalog.read", "/v1/records/fixture-0001", None, 0), ("jobs.create", "/v1/jobs", None, 0)),
        now=now,
    )
    limited = issue_token(
        key_hex, "benchmark-limited", "tenant-a",
        (("catalog.read", "/v1/records/fixture-0001", None, 0),),
        now=now,
    )
    return reader, limited


def authorize(claims: dict, capability: str, resource: str, *, now: int) -> tuple[bool, str]:
    if now >= claims["expires_at"]:
        return False, "TOKEN_EXPIRED"
    matching = [grant for grant in claims["grants"] if grant["capability"] == capability]
    if not matching:
        return False, "MISSING_CAPABILITY"
    live = [grant for grant in matching if grant["expires_at"] is None or now < grant["expires_at"]]
    if not live:
        return False, "EXPIRED_GRANT"
    for grant in live:
        prefix = grant["resource_prefix"].rstrip("/") or "/"
        if resource == prefix or resource.startswith(prefix.rstrip("/") + "/"):
            return True, "ALLOW"
    return False, "RESOURCE_SCOPE"
