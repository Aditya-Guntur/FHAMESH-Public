"""Exception hierarchy for the Federated Hierarchical Agent Mesh."""

from __future__ import annotations


class FHAMeshError(Exception):
    """Base exception for all fhamesh errors."""


class AuthenticationError(FHAMeshError):
    """Credential verification failed."""


class AuthorizationError(FHAMeshError):
    """Policy check denied the action."""


class PolicyViolationError(FHAMeshError):
    """Request violates an active policy constraint."""


class HopLimitExceeded(FHAMeshError):
    """Message exceeded max_hops, likely a routing loop."""


class SubtreeError(FHAMeshError):
    """Error within a subtree execution branch."""


class SubtreeTimeoutError(SubtreeError):
    """Subtree execution timed out."""


class PrivacyBudgetExhausted(FHAMeshError):
    """User's differential privacy budget is fully consumed."""


class RateLimitExceeded(FHAMeshError):
    """Agent or user exceeded their rate limit."""


class DataCoreDenied(FHAMeshError):
    """DataCore refused the query (missing justification, RLS violation, etc.)."""


class MessageExpiredError(FHAMeshError):
    """Message TTL has elapsed before delivery."""


class RegistrationError(FHAMeshError):
    """Agent registration or deregistration failed."""


class TransportError(FHAMeshError):
    """Message bus communication failure."""
