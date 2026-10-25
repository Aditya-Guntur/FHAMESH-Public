"""Channel naming conventions and routing for Redis pub/sub."""

from __future__ import annotations

from ..core.message import MessageEnvelope
from ..core.types import AgentLayer


class ChannelRouter:
    """Determines which Redis channel(s) a message should be published to.

    Channel naming convention:
        fhamesh:agent:{agent_id}       — direct to specific agent
        fhamesh:layer:{layer}          — broadcast to layer
        fhamesh:domain:{domain}        — broadcast to domain
        fhamesh:subtree:{subtree_id}   — within a subtree
        fhamesh:mesh:peer              — orchestrator peer mesh
        fhamesh:health                 — health ping/pong
        fhamesh:control                — system control
    """

    PREFIX = "fhamesh"

    @staticmethod
    def direct_channel(agent_id: str) -> str:
        """Channel for direct messages to a specific agent."""
        return f"fhamesh:agent:{agent_id}"

    @staticmethod
    def layer_broadcast(layer: AgentLayer | str) -> str:
        """Channel for broadcasting to all agents in a layer."""
        layer_val = layer.value if isinstance(layer, AgentLayer) else layer
        return f"fhamesh:layer:{layer_val}"

    @staticmethod
    def domain_channel(domain: str) -> str:
        """Channel for broadcasting to all agents in a domain."""
        return f"fhamesh:domain:{domain}"

    @staticmethod
    def subtree_channel(subtree_id: str) -> str:
        """Channel for messages within a subtree."""
        return f"fhamesh:subtree:{subtree_id}"

    @staticmethod
    def peer_mesh_channel() -> str:
        """Channel for orchestrator lateral communication."""
        return "fhamesh:mesh:peer"

    @staticmethod
    def health_channel() -> str:
        """Channel for health pings."""
        return "fhamesh:health"

    @staticmethod
    def control_channel() -> str:
        """Channel for system control messages."""
        return "fhamesh:control"

    @staticmethod
    def resolve_target(envelope: MessageEnvelope) -> str:
        """Determine which channel to publish to based on envelope metadata.

        Priority:
        1. Direct target agent (if target_agent_id is set)
        2. Subtree channel (if subtree_id is set and no direct target)
        3. Layer broadcast (fallback)
        """
        if envelope.target_agent_id:
            return ChannelRouter.direct_channel(envelope.target_agent_id)
        if envelope.subtree_id:
            return ChannelRouter.subtree_channel(envelope.subtree_id)
        # Fallback: broadcast to orchestrator layer
        return ChannelRouter.layer_broadcast(AgentLayer.ORCHESTRATOR)

    @staticmethod
    def agent_channels(agent_id: str, layer: AgentLayer, domain: str) -> list[str]:
        """Return all channels an agent should subscribe to."""
        channels = [
            ChannelRouter.direct_channel(agent_id),
            ChannelRouter.layer_broadcast(layer),
            ChannelRouter.domain_channel(domain),
            ChannelRouter.health_channel(),
            ChannelRouter.control_channel(),
        ]
        if layer == AgentLayer.ORCHESTRATOR:
            channels.append(ChannelRouter.peer_mesh_channel())
        return channels
