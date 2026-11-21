"""Service-independent agent proposal gateway."""

from .core import AgentGateway, GatewayError, Plan, Proposal, ValidationResult

__all__ = ["AgentGateway", "GatewayError", "Plan", "Proposal", "ValidationResult"]
