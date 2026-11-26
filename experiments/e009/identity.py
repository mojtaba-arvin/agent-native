"""Identity-provider boundary for the E-009 executable kernel prototype.

The in-memory token map is a test/demo fixture, not a production identity
system. A deployment must inject an authenticated workload/user identity
provider; clients never submit grants or tenant identity as trusted claims.
"""

from __future__ import annotations

import secrets
import sys
from pathlib import Path
from typing import Callable, Protocol

_REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPOSITORY_ROOT / "experiments" / "e004"))

from security_model import RequestContext


TrustedContextFactory = Callable[[], RequestContext]


class IdentityProvider(Protocol):
    def authenticate(self, authorization: str | None) -> RequestContext | None:
        """Return trusted identity and grants, or None when authentication fails."""


class MemoryIdentityProvider:
    """Constant-time token comparison over a small trusted, in-process fixture.

    Values may be prebuilt RequestContext instances for compatibility with
    deterministic tests, or zero-argument factories for hosts that must create
    request-scoped authority only after a credential has been authenticated.
    """

    def __init__(
        self,
        tokens: dict[str, RequestContext | TrustedContextFactory],
    ):
        if not isinstance(tokens, dict) or not tokens:
            raise ValueError("identity_tokens_must_be_nonempty_mapping")
        for token, context_or_factory in tokens.items():
            if not isinstance(token, str) or not token.strip():
                raise ValueError("identity_token_must_be_nonempty")
            if not isinstance(context_or_factory, RequestContext) and not callable(
                context_or_factory
            ):
                raise ValueError("identity_value_must_be_trusted_context_or_factory")
        self._tokens = tuple(tokens.items())

    def authenticate(self, authorization: str | None) -> RequestContext | None:
        if not isinstance(authorization, str) or not authorization.startswith("Bearer "):
            return None
        supplied = authorization[7:].strip()
        if not supplied:
            return None
        matched = None
        for expected, context_or_factory in self._tokens:
            try:
                equal = secrets.compare_digest(supplied, expected)
            except TypeError:
                equal = False
            if equal:
                matched = context_or_factory
        if matched is None:
            return None
        context = matched() if callable(matched) else matched
        if not isinstance(context, RequestContext):
            raise TypeError("trusted_context_factory_must_return_request_context")
        return context
