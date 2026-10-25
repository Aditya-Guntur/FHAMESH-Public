"""Core type definitions for the Federated Hierarchical Agent Mesh."""

from __future__ import annotations

from enum import Enum, auto
from typing import Any, TypedDict


class AgentLayer(Enum):
    """Layers in the agent mesh hierarchy."""
    LEAF = "leaf"
    ORCHESTRATOR = "orchestrator"
    DATACORE = "datacore"


class MessageType(Enum):
    """All message types in the mesh protocol."""
    INTENT_REQUEST = "intent_request"
    INTENT_RESPONSE = "intent_response"
    DATA_QUERY = "data_query"
    DATA_RESPONSE = "data_response"
    SUBTREE_SPAWN = "subtree_spawn"
    SUBTREE_RESULT = "subtree_result"
    PEER_REQUEST = "peer_request"
    PEER_RESPONSE = "peer_response"
    HEALTH_PING = "health_ping"
    HEALTH_PONG = "health_pong"
    AUTH_CHALLENGE = "auth_challenge"
    AUTH_RESPONSE = "auth_response"
    ERROR = "error"


class IntentCategory(Enum):
    """Categories for classified user intents."""
    QUERY = "query"
    COMMAND = "command"
    NAVIGATION = "navigation"
    UNKNOWN = "unknown"


class PolicyVerdict(Enum):
    """Outcome of a policy evaluation."""
    ALLOW = auto()
    DENY = auto()
    CHALLENGE = auto()
    RATE_LIMITED = auto()


class SubtreeState(Enum):
    """Lifecycle states for a subtree execution."""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    GARBAGE_COLLECTED = "garbage_collected"


# Type aliases for readability
AgentId = str       # format: "{layer}:{domain}:{uuid4_short}"
SubtreeId = str     # format: "subtree:{parent_agent_id}:{seq}"
CorrelationId = str # traces a request across the entire mesh


class AgentRegistryEntry(TypedDict):
    """Schema for an agent's registry record."""
    agent_id: str
    layer: str
    domain: str
    channels: list[str]
    registered_at: float
