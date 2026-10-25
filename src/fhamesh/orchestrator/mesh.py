"""Peer mesh — lateral communication between orchestrators.

Enables cross-domain queries, ensemble consensus, load balancing,
and fault recovery without escalation to a central controller.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, TYPE_CHECKING

from ..core.message import MessageEnvelope
from ..core.types import AgentLayer, MessageType

if TYPE_CHECKING:
    from .controller import OrchestratorNode

logger = logging.getLogger(__name__)


class PeerMesh:
    """Lateral communication between peer orchestrators.

    Use cases:
    - Cross-domain queries: forward sub-queries to domain specialists
    - Ensemble consensus: ask multiple peers to validate a conclusion
    - Load balancing: redirect when overloaded
    - Fault recovery: take over for a failed peer
    """

    def __init__(self, owner: OrchestratorNode):
        self._owner = owner

    async def request_peer(
        self,
        domain: str,
        query: dict[str, Any],
        original_envelope: MessageEnvelope,
        timeout: float = 15.0,
    ) -> MessageEnvelope | None:
        """Send a request to a peer orchestrator in another domain.

        Returns the peer's response or None on timeout.
        """
        if not self._owner._registry:
            logger.warning("No registry available for peer lookup")
            return None

        # Find a peer orchestrator for the target domain
        peer_id = await self._owner._registry.find_one(
            domain, AgentLayer.ORCHESTRATOR,
        )
        if not peer_id:
            logger.warning("No peer orchestrator found for domain: %s", domain)
            return None

        peer_envelope = MessageEnvelope(
            correlation_id=original_envelope.correlation_id,
            message_type=MessageType.PEER_REQUEST.value,
            source_agent_id=self._owner.agent_id,
            target_agent_id=peer_id,
            payload=query,
            parent_message_id=original_envelope.message_id,
            hop_count=original_envelope.hop_count + 1,
            max_hops=original_envelope.max_hops,
        )

        if self._owner._transport:
            return await self._owner._transport.request(
                peer_envelope, timeout=timeout,
            )
        return None

    async def broadcast_for_consensus(
        self,
        query: dict[str, Any],
        original_envelope: MessageEnvelope,
        timeout: float = 10.0,
    ) -> list[MessageEnvelope]:
        """Broadcast to all peer orchestrators and collect responses.

        Used for ensemble agreement — if peers disagree, the input
        may be adversarial or ambiguous.
        """
        if not self._owner._registry:
            return []

        peers = await self._owner._registry.find_by_layer(AgentLayer.ORCHESTRATOR)
        # Exclude self
        peers = [p for p in peers if p["agent_id"] != self._owner.agent_id]

        if not peers:
            return []

        tasks = []
        for peer in peers:
            peer_envelope = MessageEnvelope(
                correlation_id=original_envelope.correlation_id,
                message_type=MessageType.PEER_REQUEST.value,
                source_agent_id=self._owner.agent_id,
                target_agent_id=peer["agent_id"],
                payload=query,
                parent_message_id=original_envelope.message_id,
                hop_count=original_envelope.hop_count + 1,
                max_hops=original_envelope.max_hops,
            )
            if self._owner._transport:
                tasks.append(
                    self._owner._transport.request(peer_envelope, timeout=timeout)
                )

        if not tasks:
            return []

        results = await asyncio.gather(*tasks, return_exceptions=True)
        responses = []
        for r in results:
            if isinstance(r, MessageEnvelope):
                responses.append(r)
            elif isinstance(r, Exception):
                logger.warning("Peer request failed: %s", r)

        return responses

    async def check_consensus(
        self,
        responses: list[MessageEnvelope],
    ) -> tuple[bool, float]:
        """Check if peers agree on their responses.

        Returns (consensus_reached: bool, agreement_ratio: float).
        Agreement is measured by comparing response verdicts/categories.
        """
        if len(responses) < 2:
            return True, 1.0  # Single or no responses = trivial consensus

        verdicts = []
        for r in responses:
            verdict = r.payload.get("verdict", r.payload.get("category", "unknown"))
            verdicts.append(verdict)

        # Count most common verdict
        from collections import Counter
        counts = Counter(verdicts)
        most_common_count = counts.most_common(1)[0][1]
        agreement = most_common_count / len(verdicts)

        return agreement >= 0.5, agreement
