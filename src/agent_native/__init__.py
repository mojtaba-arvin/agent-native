"""Public package surface for the Agent Native research framework."""

from .ir import Diagnostic, Parser, Token, lex, validate_ir
from .runtime import ConfigurationError, DomainFault, HandlerContext, HandlerResult, RuntimeFault, RuntimeResponse, ServiceRuntime, load_service_ir
from .manifest import RegisteredService, ServiceRegistry, ServiceRegistryError
from .handlers import RuntimeAdapters, TrustedHandlerRegistry, built_in_handler_registry, build_service_runtime

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
    "ServiceRegistry",
    "ServiceRegistryError",
    "RuntimeAdapters",
    "TrustedHandlerRegistry",
    "built_in_handler_registry",
    "build_service_runtime",
    "ServiceRuntime",
    "Parser",
    "Token",
    "__version__",
    "lex",
    "load_service_ir",
    "validate_ir",
]
