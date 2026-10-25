"""Message middleware for transport-level enforcement.

Sits between the transport and the agent. Enforces authentication,
hop limits, TTL, and registry checks on every inbound message.
"""

from __future__ import annotations

import logging
from typing import Any

from ..core.message import MessageEnvelope
from ..core.types import PolicyVerdict
from ..security.credentials import ScopedToken
from ..security.verifier import CredentialVerifier

logger = logging.getLogger(__name__)


class MessageMiddleware:
    """Validates every inbound message before it reaches the agent.

    Checks:
    1. Message TTL not expired
    2. Hop count within limit
    3. Auth token present, parseable, and valid
    4. Source agent is known (registry check, if registry provided)
    """

    def __init__(
        self,
        verifier: CredentialVerifier,
        registry: Any = None,
    ):
        self._verifier = verifier
        self._registry = registry

    async def process_inbound(
        self,
        envelope: MessageEnvelope,
        expected_action: str = "",
        expected_target: str = "",
    ) -> tuple[bool, str]:
        """Validate an inbound message.

        Returns (allowed: bool, reason: str).
        If not allowed, the message should be dropped and reason logged.
        """
        # 1. TTL check
        if envelope.is_expired():
            return False, f"Message expired (age={__import__('time').time() - envelope.timestamp:.1f}s, ttl={envelope.ttl_seconds}s)"

        # 2. Hop count
        if envelope.hop_count >= envelope.max_hops:
            return False, f"Hop limit exceeded ({envelope.hop_count}/{envelope.max_hops})"

        # 3. Auth token
        if not envelope.auth_token:
            # Allow health pings and control messages without auth
            if envelope.message_type in ("health_ping", "health_pong", "auth_challenge"):
                return True, "ok (no auth required for this message type)"
            return False, "No auth token present"

        token = self._verifier.extract_token(envelope.auth_token)
        if token is None:
            return False, "Failed to parse auth token"

        action = expected_action or envelope.message_type
        verdict = self._verifier.verify(token, action, expected_target)
        if verdict != PolicyVerdict.ALLOW:
            return False, f"Auth verification failed: {verdict.name}"

        # 4. Registry check (optional)
        if self._registry is not None:
            is_alive = await self._registry.is_alive(envelope.source_agent_id)
            if not is_alive:
                return False, f"Source agent not registered: {envelope.source_agent_id}"

        return True, "ok"
