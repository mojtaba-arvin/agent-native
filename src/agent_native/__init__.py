"""Public package surface for the Agent Native research framework."""

from .ir import Diagnostic, Parser, Token, lex, validate_ir
from .runtime import ConfigurationError, DomainFault, HandlerContext, HandlerResult, RuntimeFault, RuntimeResponse, ServiceRuntime, load_service_ir

__version__ = "0.1.0.dev0"

__all__ = [
    "ConfigurationError",
    "Diagnostic",
    "DomainFault",
    "HandlerContext",
    "HandlerResult",
    "RuntimeFault",
    "RuntimeResponse",
    "ServiceRuntime",
    "Parser",
    "Token",
    "__version__",
    "lex",
    "load_service_ir",
    "validate_ir",
]
