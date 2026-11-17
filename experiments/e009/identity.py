"""Identity-provider boundary for the E-009 executable kernel prototype.

The in-memory token map is a test/demo fixture, not a production identity
system. A deployment must inject an authenticated workload/user identity
provider; clients never submit grants or tenant identity as trusted claims.
"""

from __future__ import annotations

import secrets
from typing import Protocol

from security_model import RequestContext


class IdentityProvider(Protocol):
    def authenticate(self, authorization: str | None) -> RequestContext | None:
        """Return trusted identity and grants, or None when authentication fails."""


class MemoryIdentityProvider:
    """Constant-time token comparison over a small trusted, in-process fixture."""

    def __init__(self, tokens: dict[str, RequestContext]):
        if not isinstance(tokens, dict) or not tokens:
            raise ValueError("identity_tokens_must_be_nonempty_mapping")
        for token, context in tokens.items():
            if not isinstance(token, str) or not token.strip():
                raise ValueError("identity_token_must_be_nonempty")
            if not isinstance(context, RequestContext):
                raise ValueError("identity_context_must_be_trusted_request_context")
        self._tokens = tuple(tokens.items())

    def authenticate(self, authorization: str | None) -> RequestContext | None:
        if not isinstance(authorization, str) or not authorization.startswith("Bearer "):
            return None
        supplied = authorization[7:].strip()
        if not supplied:
            return None
        match = None
        for expected, context in self._tokens:
            if secrets.compare_digest(supplied, expected):
                match = context
        return match
