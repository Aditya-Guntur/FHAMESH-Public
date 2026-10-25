"""Core types, base classes, and message primitives."""

from .agent import BaseAgent
from .errors import (
    AuthenticationError,
    AuthorizationError,
    DataCoreDenied,
    FHAMeshError,
    HopLimitExceeded,
    MessageExpiredError,
    PolicyViolationError,
    PrivacyBudgetExhausted,
    RateLimitExceeded,
    RegistrationError,
    SubtreeError,
    SubtreeTimeoutError,
    TransportError,
)
from .message import IntentDescriptor, MessageEnvelope, QueryResult
from .registry import AgentRegistry
from .types import AgentLayer, IntentCategory, MessageType, PolicyVerdict, SubtreeState
