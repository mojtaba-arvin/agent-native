"""Production multi-service loader and dispatcher."""
from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any, Callable

from .handlers import RuntimeAdapters, TrustedHandlerRegistry, build_service_runtime
from .manifest import ServiceRegistry, ServiceRegistryError
from .runtime import RuntimeResponse
from .security import AuthenticationError, CapabilityTokenAuthority


class ServiceHost:
    """Load validated service manifests once and dispatch by stable service ID.

    Service manifests select only IDs from the supplied host-owned handler
    registry. The host never imports code named by a manifest.
    """

    def __init__(
        self,
        services_root: str | Path,
        *,
        handlers: TrustedHandlerRegistry,
        adapters: RuntimeAdapters,
        clock: Callable[[], float] | None = None,
        audit_sink: Any = None,
        authenticator: CapabilityTokenAuthority | None = None,
    ):
        if not isinstance(handlers, TrustedHandlerRegistry):
            raise TypeError("host_requires_trusted_handler_registry")
        if not isinstance(adapters, RuntimeAdapters):
            raise TypeError("host_requires_runtime_adapters")
        if authenticator is not None and not isinstance(authenticator, CapabilityTokenAuthority):
            raise TypeError("host_requires_capability_token_authority")
        self.authenticator = authenticator
        self.registry = ServiceRegistry(
            services_root,
            trusted_handler_ids=handlers.handler_ids,
        )
        registered = self.registry.load_all()
        apply_migrations = getattr(adapters.repository, "apply_migrations", None)
        if callable(apply_migrations):
            apply_migrations(registered.values())
        self._runtimes = {
            service_id: build_service_runtime(
                service,
                handlers=handlers,
                adapters=adapters,
                clock=clock,
                audit_sink=audit_sink,
            )
            for service_id, service in registered.items()
        }

    @property
    def service_ids(self) -> tuple[str, ...]:
        return tuple(sorted(self._runtimes))

    def dispatch(
        self,
        service_id: str,
        method: str,
        target: str,
        body: dict[str, Any],
        identity,
        *,
        headers: dict[str, str] | None = None,
        request_id: str | None = None,
    ) -> RuntimeResponse:
        runtime = self._runtimes.get(service_id) if isinstance(service_id, str) else None
        if runtime is None:
            safe_request_id = (
                request_id
                if isinstance(request_id, str) and request_id.strip() and len(request_id) <= 128
                else str(uuid.uuid4())
            )
            return RuntimeResponse(
                404,
                {"error": {"code": "SERVICE_NOT_FOUND"}, "request_id": safe_request_id},
            )
        return runtime.dispatch(
            method,
            target,
            body,
            identity,
            headers=headers,
            request_id=request_id,
        )


    def dispatch_authenticated(
        self,
        service_id: str,
        method: str,
        target: str,
        body: dict[str, Any],
        *,
        authorization: str | None,
        headers: dict[str, str] | None = None,
        request_id: str | None = None,
    ) -> RuntimeResponse:
        """Authenticate a bearer token before dispatching an untrusted request.

        This is the production ingress boundary. The lower-level dispatch()
        method accepts a trusted RequestContext for in-process callers only.
        Missing authentication configuration and all invalid credentials fail
        closed without invoking a service handler.
        """
        safe_request_id = (
            request_id
            if isinstance(request_id, str) and request_id.strip() and len(request_id) <= 128
            else str(uuid.uuid4())
        )
        if self.authenticator is None:
            return RuntimeResponse(
                401,
                {"error": {"code": "UNAUTHENTICATED"}, "request_id": safe_request_id},
            )
        try:
            identity = self.authenticator.authenticate(authorization)
        except AuthenticationError:
            return RuntimeResponse(
                401,
                {"error": {"code": "UNAUTHENTICATED"}, "request_id": safe_request_id},
            )
        return self.dispatch(
            service_id,
            method,
            target,
            body,
            identity,
            headers=headers,
            request_id=safe_request_id,
        )
