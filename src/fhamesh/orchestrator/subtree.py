"""Subtree lifecycle management.

Manages the creation, tracking, result collection, timeout, and
garbage collection of dynamically instantiated execution subtrees.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any, TYPE_CHECKING

from ..core.message import MessageEnvelope, QueryResult
from ..core.types import AgentLayer, MessageType, SubtreeState

if TYPE_CHECKING:
    from .controller import OrchestratorNode

logger = logging.getLogger(__name__)


@dataclass
class SubtreeContext:
    """State for an active subtree execution."""
    subtree_id: str
    parent_envelope: MessageEnvelope
    sub_queries: list[dict[str, Any]]
    state: SubtreeState = SubtreeState.PENDING
    results: dict[int, QueryResult] = field(default_factory=dict)
    spawned_at: float = field(default_factory=time.time)
    timeout_seconds: float = 30.0
    child_agent_ids: list[str] = field(default_factory=list)
    error_message: str = ""


class SubtreeManager:
    """Manages the full lifecycle of execution subtrees.

    Subtrees are isolated execution branches spawned by an orchestrator
    to handle decomposed sub-queries. Each subtree:
    - Is tracked independently
    - Has its own timeout
    - Is garbage-collected on completion
    - Has failures contained to its branch
    """

    def __init__(self, parent: OrchestratorNode):
        self._parent = parent
        self._active: dict[str, SubtreeContext] = {}
        self._seq = 0

    async def spawn(
        self,
        parent_envelope: MessageEnvelope,
        sub_queries: list[dict[str, Any]],
        timeout_seconds: float = 30.0,
    ) -> str:
        """Create a new subtree and dispatch sub-queries.

        Returns the subtree_id. Results arrive asynchronously via
        record_result().
        """
        self._seq += 1
        subtree_id = f"subtree:{self._parent.agent_id}:{self._seq}"

        ctx = SubtreeContext(
            subtree_id=subtree_id,
            parent_envelope=parent_envelope,
            sub_queries=sub_queries,
            timeout_seconds=timeout_seconds,
        )
        self._active[subtree_id] = ctx
        ctx.state = SubtreeState.RUNNING

        # Subscribe to subtree channel
        if self._parent._transport:
            from ..bus.channels import ChannelRouter
            await self._parent._transport.subscribe(
                ChannelRouter.subtree_channel(subtree_id)
            )

        # Dispatch each sub-query
        for idx, sq in enumerate(sub_queries):
            target_id = ""
            if self._parent._registry:
                domain = sq.get("domain", self._parent.domain)
                target_id = await self._parent._registry.find_one(
                    domain, AgentLayer.DATACORE,
                ) or ""

            child_envelope = MessageEnvelope(
                correlation_id=parent_envelope.correlation_id,
                message_type=MessageType.DATA_QUERY.value,
                source_agent_id=self._parent.agent_id,
                target_agent_id=target_id,
                payload={
                    "sub_query": sq,
                    "sub_query_index": idx,
                    "subtree_id": subtree_id,
                },
                subtree_id=subtree_id,
                parent_message_id=parent_envelope.message_id,
                hop_count=parent_envelope.hop_count + 1,
                max_hops=parent_envelope.max_hops,
            )
            await self._parent.send(child_envelope)

        # Schedule timeout watcher
        asyncio.create_task(self._timeout_watcher(subtree_id))

        logger.info(
            "Spawned subtree %s with %d sub-queries",
            subtree_id, len(sub_queries),
        )
        return subtree_id

    def record_result(self, subtree_id: str, idx: int, result: QueryResult) -> None:
        """Record a sub-query result."""
        ctx = self._active.get(subtree_id)
        if ctx is None:
            logger.warning("Result for unknown subtree: %s", subtree_id)
            return
        ctx.results[idx] = result
        logger.debug(
            "Subtree %s: received result %d/%d",
            subtree_id, len(ctx.results), len(ctx.sub_queries),
        )

    def is_complete(self, subtree_id: str) -> bool:
        """Check if all sub-query results have been received."""
        ctx = self._active.get(subtree_id)
        if ctx is None:
            return False
        return len(ctx.results) >= len(ctx.sub_queries)

    def collect_results(self, subtree_id: str) -> list[QueryResult]:
        """Collect results in sub-query order."""
        ctx = self._active.get(subtree_id)
        if ctx is None:
            return []
        return [ctx.results[i] for i in sorted(ctx.results.keys())]

    def get_parent_envelope(self, subtree_id: str) -> MessageEnvelope | None:
        """Get the original request that spawned this subtree."""
        ctx = self._active.get(subtree_id)
        return ctx.parent_envelope if ctx else None

    def get_state(self, subtree_id: str) -> SubtreeState | None:
        """Get the current state of a subtree."""
        ctx = self._active.get(subtree_id)
        return ctx.state if ctx else None

    async def gc(self, subtree_id: str) -> None:
        """Garbage-collect a completed subtree.

        Removes all state and unsubscribes from subtree channel.
        """
        ctx = self._active.pop(subtree_id, None)
        if ctx:
            ctx.state = SubtreeState.GARBAGE_COLLECTED
            # Unsubscribe from subtree channel
            if self._parent._transport:
                from ..bus.channels import ChannelRouter
                await self._parent._transport.unsubscribe(
                    ChannelRouter.subtree_channel(subtree_id)
                )
            logger.info("Garbage-collected subtree: %s", subtree_id)

    def active_count(self) -> int:
        """Number of currently active subtrees."""
        return len(self._active)

    def list_active(self) -> list[str]:
        """List IDs of all active subtrees."""
        return list(self._active.keys())

    async def _timeout_watcher(self, subtree_id: str) -> None:
        """Monitor a subtree for timeout."""
        ctx = self._active.get(subtree_id)
        if ctx is None:
            return
        await asyncio.sleep(ctx.timeout_seconds)
        if subtree_id in self._active and not self.is_complete(subtree_id):
            ctx.state = SubtreeState.FAILED
            ctx.error_message = f"Subtree timed out after {ctx.timeout_seconds}s"
            logger.error("Subtree %s timed out", subtree_id)
