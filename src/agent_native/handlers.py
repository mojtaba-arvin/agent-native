"""Host-registered generic handlers for declarative service manifests.

Manifest data selects a trusted handler ID and static configuration. It cannot
name a Python module, callable, or import path.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Callable, Mapping

from .manifest import RegisteredService
from .runtime import ConfigurationError, DomainFault, HandlerContext, HandlerResult, ServiceRuntime


@dataclass(frozen=True)
class RuntimeAdapters:
    repository: Any
    jobs: Any
    events: Any


@dataclass(frozen=True)
class HandlerDefinition:
    handler_id: str
    factory: Callable[[Mapping[str, Any]], Callable[[HandlerContext], Any]]
    allowed_effects: frozenset[str]


class TrustedHandlerRegistry:
    """An explicit host-owned registry; manifest strings never trigger imports."""

    def __init__(self):
        self._definitions: dict[str, HandlerDefinition] = {}

    @property
    def handler_ids(self) -> frozenset[str]:
        return frozenset(self._definitions)

    def register(
        self,
        handler_id: str,
        factory: Callable[[Mapping[str, Any]], Callable[[HandlerContext], Any]],
        *,
        allowed_effects: set[str] | frozenset[str],
    ) -> None:
        if not isinstance(handler_id, str) or not re.fullmatch(r"[a-z][a-z0-9_.-]{0,95}", handler_id):
            raise ConfigurationError("handler ID must be a lowercase host-owned identifier")
        if handler_id in self._definitions:
            raise ConfigurationError(f"duplicate trusted handler ID: {handler_id}")
        if not callable(factory):
            raise ConfigurationError("handler factory must be callable")
        effects = frozenset(allowed_effects)
        if not effects or any(not isinstance(effect, str) or not effect for effect in effects):
            raise ConfigurationError("handler definition requires explicit allowed effects")
        self._definitions[handler_id] = HandlerDefinition(handler_id, factory, effects)

    def build_handlers(self, service: RegisteredService) -> dict[str, Callable[[HandlerContext], Any]]:
        handlers: dict[str, Callable[[HandlerContext], Any]] = {}
        policy_effects = set(service.policy["effects"])
        for operation in service.ir["operations"]:
            operation_name = operation["name"]
            handler_id = service.handler_bindings[operation_name]
            definition = self._definitions.get(handler_id)
            if definition is None:
                raise ConfigurationError(f"handler is not registered by the host: {handler_id}")
            required_effects = set(operation["effects"])
            if not required_effects.issubset(definition.allowed_effects):
                raise ConfigurationError(f"handler {handler_id} does not declare all effects required by {operation_name}")
            if not required_effects.issubset(policy_effects):
                raise ConfigurationError(f"service policy does not allow all effects required by {operation_name}")
            config = service.handler_configs.get(operation_name, {})
            _validate_config_inputs(config, operation)
            try:
                handler = definition.factory(config)
            except (TypeError, ValueError) as error:
                raise ConfigurationError(f"invalid config for handler {handler_id}: {error}") from error
            if not callable(handler):
                raise ConfigurationError(f"handler factory {handler_id} did not return a callable")
            handlers[operation_name] = handler
        return handlers


def _config(
    supplied: Mapping[str, Any],
    *,
    required: set[str],
    optional: set[str] = frozenset(),
) -> dict[str, Any]:
    if not isinstance(supplied, Mapping):
        raise ValueError("handler config must be an object")
    keys = set(supplied)
    if not required.issubset(keys) or not keys.issubset(required | optional):
        raise ValueError("handler config has missing or unknown properties")
    return dict(supplied)


def _identifier(value: Any, label: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[a-z][a-z0-9_-]{0,63}", value):
        raise ValueError(f"{label} must be a lowercase identifier")
    return value


def _input_fields(value: Any) -> tuple[str, ...]:
    if not isinstance(value, list) or any(not isinstance(field, str) or not field for field in value):
        raise ValueError("input_fields must be a string array")
    if len(value) != len(set(value)):
        raise ValueError("input_fields must not contain duplicates")
    forbidden = {"tenant_id", "principal_id", "request_id", "capability", "grants"}
    if forbidden.intersection(value):
        raise ValueError("trusted identity fields cannot be sourced from agent input")
    return tuple(value)


def _validate_config_inputs(config: Mapping[str, Any], operation: Mapping[str, Any]) -> None:
    declared = {item["name"] for item in operation["input"]}
    referenced: set[str] = set()
    for key in ("input", "key_input", "idempotency_input"):
        value = config.get(key)
        if value is not None:
            if not isinstance(value, str):
                raise ConfigurationError(f"{key} must be an input field name")
            referenced.add(value)
    fields = config.get("input_fields", [])
    if not isinstance(fields, (list, tuple)) or any(not isinstance(field, str) or not field for field in fields):
        raise ConfigurationError("handler config input_fields must be a string array")
    referenced.update(fields)
    filters = config.get("filters", {})
    if not isinstance(filters, Mapping) or any(not isinstance(value, str) or not value for value in filters.values()):
        raise ConfigurationError("handler config filters must map fields to input names")
    referenced.update(filters.values())
    if not referenced.issubset(declared):
        unknown = sorted(str(value) for value in referenced - declared)
        raise ConfigurationError(f"handler config references undeclared operation inputs: {', '.join(unknown)}")


def _tenant_id(context: HandlerContext) -> str:
    identity = context.identity
    tenant_id = getattr(identity, "tenant_id", None)
    if not isinstance(tenant_id, str) or not tenant_id:
        raise DomainFault("Unauthorized")
    return tenant_id


def _value(context: HandlerContext, name: str) -> Any:
    if name not in context.values:
        raise DomainFault("InvalidInput")
    return context.values[name]


def _adapter(context: HandlerContext, adapter_name: str, method_name: str) -> Callable[..., Any]:
    adapters = context.repository
    adapter = getattr(adapters, adapter_name, None)
    method = getattr(adapter, method_name, None)
    if not callable(method):
        raise DomainFault("ServiceUnavailable")
    return method


def _payload(context: HandlerContext, fields: tuple[str, ...]) -> dict[str, Any]:
    return {field: _value(context, field) for field in fields}


def _factory_crud_read(config: Mapping[str, Any]):
    cfg = _config(config, required={"resource", "key_input"})
    resource = _identifier(cfg["resource"], "resource")
    key_input = cfg["key_input"]
    if not isinstance(key_input, str):
        raise ValueError("key_input must be a string")

    def handle(context: HandlerContext):
        tenant_id = _tenant_id(context)
        result = _adapter(context, "repository", "read")(resource, _value(context, key_input), tenant_id=tenant_id)
        if result is None:
            raise DomainFault("NotFound")
        return result
    return handle


def _factory_crud_read_by_field(config: Mapping[str, Any]):
    cfg = _config(config, required={"resource", "field", "input"})
    resource = _identifier(cfg["resource"], "resource")
    field = _identifier(cfg["field"], "field")
    input_name = cfg["input"]
    if not isinstance(input_name, str):
        raise ValueError("input must be a string")

    def handle(context: HandlerContext):
        tenant_id = _tenant_id(context)
        result = _adapter(context, "repository", "read_by_field")(
            resource, field, _value(context, input_name), tenant_id=tenant_id
        )
        if result is None:
            raise DomainFault("NotFound")
        return result
    return handle


def _factory_crud_create(config: Mapping[str, Any]):
    cfg = _config(config, required={"resource", "input_fields"}, optional={"idempotency_input"})
    resource = _identifier(cfg["resource"], "resource")
    fields = _input_fields(cfg["input_fields"])
    idem_input = cfg.get("idempotency_input")
    if idem_input is not None and not isinstance(idem_input, str):
        raise ValueError("idempotency_input must be a string")

    def handle(context: HandlerContext):
        tenant_id = _tenant_id(context)
        idem = _value(context, idem_input) if idem_input else None
        result = _adapter(context, "repository", "create")(
            resource, _payload(context, fields), tenant_id=tenant_id, idempotency_key=idem
        )
        return HandlerResult(result, status_code=201)
    return handle


def _factory_crud_update(config: Mapping[str, Any]):
    cfg = _config(config, required={"resource", "key_input", "input_fields"})
    resource = _identifier(cfg["resource"], "resource")
    key_input = cfg["key_input"]
    if not isinstance(key_input, str):
        raise ValueError("key_input must be a string")
    fields = _input_fields(cfg["input_fields"])

    def handle(context: HandlerContext):
        tenant_id = _tenant_id(context)
        result = _adapter(context, "repository", "update")(
            resource, _value(context, key_input), _payload(context, fields), tenant_id=tenant_id
        )
        if result is None:
            raise DomainFault("NotFound")
        return result
    return handle


def _factory_crud_delete(config: Mapping[str, Any]):
    cfg = _config(config, required={"resource", "key_input"})
    resource = _identifier(cfg["resource"], "resource")
    key_input = cfg["key_input"]
    if not isinstance(key_input, str):
        raise ValueError("key_input must be a string")

    def handle(context: HandlerContext):
        tenant_id = _tenant_id(context)
        deleted = _adapter(context, "repository", "delete")(
            resource, _value(context, key_input), tenant_id=tenant_id
        )
        if not deleted:
            raise DomainFault("NotFound")
        return HandlerResult(None, status_code=204)
    return handle


def _factory_jobs_submit(config: Mapping[str, Any]):
    cfg = _config(config, required={"queue", "input_fields"}, optional={"idempotency_input"})
    queue = _identifier(cfg["queue"], "queue")
    fields = _input_fields(cfg["input_fields"])
    idem_input = cfg.get("idempotency_input")
    if idem_input is not None and not isinstance(idem_input, str):
        raise ValueError("idempotency_input must be a string")

    def handle(context: HandlerContext):
        tenant_id = _tenant_id(context)
        idem = _value(context, idem_input) if idem_input else None
        if context.audit_receipt is not None:
            transactional = _adapter(context, "jobs", "submit_with_audit")
            result = transactional(
                queue, _payload(context, fields), tenant_id=tenant_id,
                idempotency_key=idem, request_id=context.request_id,
                audit_event=context.audit_event, audit_receipt=context.audit_receipt,
            )
            return result if isinstance(result, HandlerResult) else HandlerResult(result, status_code=202)
        submit = _adapter(context, "jobs", "submit")
        return HandlerResult(
            submit(queue, _payload(context, fields), tenant_id=tenant_id, idempotency_key=idem, request_id=context.request_id),
            status_code=202,
        )
    return handle


def _factory_jobs_get(config: Mapping[str, Any]):
    cfg = _config(config, required={"queue", "key_input"})
    queue = _identifier(cfg["queue"], "queue")
    key_input = cfg["key_input"]
    if not isinstance(key_input, str):
        raise ValueError("key_input must be a string")

    def handle(context: HandlerContext):
        result = _adapter(context, "jobs", "get")(queue, _value(context, key_input), tenant_id=_tenant_id(context))
        if result is None:
            raise DomainFault("NotFound")
        return result
    return handle


def _factory_jobs_cancel(config: Mapping[str, Any]):
    cfg = _config(config, required={"queue", "key_input"})
    queue = _identifier(cfg["queue"], "queue")
    key_input = cfg["key_input"]
    if not isinstance(key_input, str):
        raise ValueError("key_input must be a string")

    def handle(context: HandlerContext):
        result = _adapter(context, "jobs", "cancel")(queue, _value(context, key_input), tenant_id=_tenant_id(context))
        if result is None:
            raise DomainFault("NotFound")
        return result
    return handle


def _factory_events_publish(config: Mapping[str, Any]):
    cfg = _config(config, required={"event_type", "input_fields"})
    event_type = cfg["event_type"]
    if not isinstance(event_type, str) or not re.fullmatch(r"[a-z][a-z0-9_.-]{0,95}", event_type):
        raise ValueError("event_type must be a lowercase topic identifier")
    fields = _input_fields(cfg["input_fields"])

    def handle(context: HandlerContext):
        result = _adapter(context, "events", "publish")(
            event_type, _payload(context, fields), tenant_id=_tenant_id(context), request_id=context.request_id
        )
        return HandlerResult(result, status_code=202)
    return handle


def built_in_handler_registry() -> TrustedHandlerRegistry:
    """Return the host's generic CRUD, job, and event handler definitions."""
    registry = TrustedHandlerRegistry()
    registry.register("crud.read", _factory_crud_read, allowed_effects={"repository.read"})
    registry.register("crud.read_by_field", _factory_crud_read_by_field, allowed_effects={"repository.read"})
    registry.register("crud.create", _factory_crud_create, allowed_effects={"repository.write"})
    registry.register("crud.update", _factory_crud_update, allowed_effects={"repository.write"})
    registry.register("crud.delete", _factory_crud_delete, allowed_effects={"repository.write"})
    registry.register("jobs.submit", _factory_jobs_submit, allowed_effects={"queue.submit"})
    registry.register("jobs.get", _factory_jobs_get, allowed_effects={"queue.read"})
    registry.register("jobs.cancel", _factory_jobs_cancel, allowed_effects={"queue.cancel"})
    registry.register("events.publish", _factory_events_publish, allowed_effects={"event.publish"})
    return registry


def build_service_runtime(
    service: RegisteredService,
    *,
    handlers: TrustedHandlerRegistry,
    adapters: RuntimeAdapters,
    clock: Callable[[], float] | None = None,
    audit_sink: Any = None,
) -> ServiceRuntime:
    """Build a runtime only from validated manifests and host-owned handlers."""
    operation_handlers = handlers.build_handlers(service)
    return ServiceRuntime(
        service.ir,
        handlers=operation_handlers,
        repository=adapters,
        trusted_effects=set(service.policy["effects"]),
        clock=clock,
        audit_sink=audit_sink,
    )
