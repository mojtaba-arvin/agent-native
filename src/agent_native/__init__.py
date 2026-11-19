"""Public package surface for the Agent Native research framework."""

from .ir import Diagnostic, Parser, Token, lex, validate_ir

__version__ = "0.1.0.dev0"

__all__ = [
    "Diagnostic",
    "Parser",
    "Token",
    "__version__",
    "lex",
    "validate_ir",
]
