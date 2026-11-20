"""Public package surface for the Agent Native research framework."""

from .ir import Diagnostic, Parser, Token, lex, validate_ir
from .runtime import ConfigurationError, DomainFault, HandlerContext, HandlerResult, RuntimeFault, RuntimeResponse, ServiceRuntime, load_service_ir, validate_operation_inputs
from .manifest import RegisteredService, ServiceRegistry, ServiceRegistryError
from .handlers import RuntimeAdapters, TrustedHandlerRegistry, built_in_handler_registry, build_service_runtime
from .security import Grant, PolicyEngine, RequestContext
from .gateway import AgentGateway, GatewayError, Plan, Proposal, ValidationResult
from .authz import EFFECT_ACCESS_MODE, classify_effects
from .postgres import PostgresResourceRepository
from .host import ServiceHost

__version__ = "0.1.0.dev0"

__all__ = [
    "ConfigurationError",
    "Diagnostic",
    "DomainFault",
    "HandlerContext",
    "HandlerResult",
    "RuntimeFault",
    "RuntimeResponse",
    "RegisteredService",
    "ServiceHost",
    "ServiceRegistry",
    "ServiceRegistryError",
    "RuntimeAdapters",
    "TrustedHandlerRegistry",
    "built_in_handler_registry",
    "build_service_runtime",
    "Grant",
    "PolicyEngine",
    "PostgresResourceRepository",
    "RequestContext",
    "ServiceRuntime",
    "validate_operation_inputs",
    "AgentGateway",
    "GatewayError",
    "Plan",
    "Proposal",
    "ValidationResult",
    "EFFECT_ACCESS_MODE",
    "classify_effects",
    "Parser",
    "Token",
    "__version__",
    "lex",
    "load_service_ir",
    "validate_ir",
]
