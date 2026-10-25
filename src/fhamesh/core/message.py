"""Message envelope and data structures for inter-agent communication."""

from __future__ import annotations

import hashlib
import json
import time
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class MessageEnvelope:
    """Immutable message container for all inter-agent communication.

    Every message in the mesh is wrapped in an envelope that carries
    routing info, authentication tokens, and audit metadata.
    """

    message_id: str = field(default_factory=lambda: uuid.uuid4().hex[:16])
    correlation_id: str = ""
    message_type: str = ""
    source_agent_id: str = ""
    target_agent_id: str = ""
    timestamp: float = field(default_factory=time.time)
    payload: dict[str, Any] = field(default_factory=dict)
    auth_token: str = ""
    policy_attestation: str = ""
    parent_message_id: str = ""
    subtree_id: str = ""
    ttl_seconds: int = 30
    hop_count: int = 0
    max_hops: int = 10

    def content_hash(self) -> str:
        """SHA-256 of the payload for audit logging."""
        canonical = json.dumps(self.payload, sort_keys=True, default=str)
        return hashlib.sha256(canonical.encode()).hexdigest()

    def is_expired(self) -> bool:
        """Check if the message has exceeded its TTL."""
        return (time.time() - self.timestamp) > self.ttl_seconds

    def with_hop(self) -> MessageEnvelope:
        """Return a new envelope with incremented hop count."""
        data = asdict(self)
        data["hop_count"] = self.hop_count + 1
        return MessageEnvelope(**data)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a plain dictionary."""
        return asdict(self)

    def to_bytes(self) -> bytes:
        """Serialize to JSON bytes for transport."""
        return json.dumps(asdict(self), default=str).encode("utf-8")

    @classmethod
    def from_bytes(cls, data: bytes) -> MessageEnvelope:
        """Deserialize from JSON bytes."""
        parsed = json.loads(data)
        return cls(**parsed)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> MessageEnvelope:
        """Construct from a plain dictionary."""
        return cls(**data)

    def reply(
        self,
        message_type: str,
        payload: dict[str, Any],
        source_agent_id: str,
        auth_token: str = "",
        policy_attestation: str = "",
    ) -> MessageEnvelope:
        """Create a reply envelope addressed back to the sender."""
        return MessageEnvelope(
            correlation_id=self.correlation_id,
            message_type=message_type,
            source_agent_id=source_agent_id,
            target_agent_id=self.source_agent_id,
            payload=payload,
            auth_token=auth_token,
            policy_attestation=policy_attestation,
            parent_message_id=self.message_id,
            subtree_id=self.subtree_id,
            hop_count=self.hop_count + 1,
            max_hops=self.max_hops,
        )


@dataclass(slots=True)
class IntentDescriptor:
    """Structured output from Leaf nodes.

    This is the sole product of edge processing. It is a structured
    representation of user intent, never raw user text.
    """

    category: str = ""
    domain: str = "general"
    action: str = ""
    confidence: float = 0.0
    parameters: dict[str, Any] = field(default_factory=dict)
    raw_input_hash: str = ""
    sanitized: bool = False
    eligibility_passed: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> IntentDescriptor:
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


@dataclass(slots=True)
class QueryResult:
    """Structured result returned from DataCore nodes.

    Contains the actual data plus metadata about privacy protection
    and any redactions applied.
    """

    success: bool = False
    data: dict[str, Any] = field(default_factory=dict)
    privacy_budget_consumed: float = 0.0
    fields_redacted: list[str] = field(default_factory=list)
    noise_applied: bool = False
    error_message: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> QueryResult:
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})
