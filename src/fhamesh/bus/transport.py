"""Redis pub/sub transport layer for inter-agent communication."""

from __future__ import annotations

import asyncio
import logging
import uuid
from collections.abc import AsyncIterator
from typing import Any

import redis.asyncio as aioredis

from ..core.message import MessageEnvelope
from .channels import ChannelRouter

logger = logging.getLogger(__name__)


class RedisTransport:
    """Async Redis pub/sub transport.

    Each agent instance gets its own transport. Agents communicate
    exclusively through Redis channels — making them process-independent.
    """

    def __init__(self, redis_url: str = "redis://localhost:6379"):
        self._url = redis_url
        self._redis: aioredis.Redis | None = None
        self._pubsub: aioredis.client.PubSub | None = None
        self._subscribed_channels: set[str] = set()

    async def connect(self) -> None:
        """Establish connection to Redis."""
        self._redis = aioredis.from_url(self._url, decode_responses=False)
        self._pubsub = self._redis.pubsub()
        logger.info("Transport connected to %s", self._url)

    async def disconnect(self) -> None:
        """Close Redis connection."""
        if self._pubsub:
            await self._pubsub.unsubscribe()
            await self._pubsub.close()
        if self._redis:
            await self._redis.close()
        logger.info("Transport disconnected")

    @property
    def redis(self) -> aioredis.Redis:
        """Access the underlying Redis client (for session/registry/rate-limit use)."""
        if self._redis is None:
            raise RuntimeError("Transport not connected")
        return self._redis

    async def subscribe(self, *channels: str) -> None:
        """Subscribe to one or more channels."""
        if self._pubsub is None:
            raise RuntimeError("Transport not connected")
        new_channels = [ch for ch in channels if ch not in self._subscribed_channels]
        if new_channels:
            await self._pubsub.subscribe(*new_channels)
            self._subscribed_channels.update(new_channels)
            logger.debug("Subscribed to: %s", new_channels)

    async def unsubscribe(self, *channels: str) -> None:
        """Unsubscribe from one or more channels."""
        if self._pubsub is None:
            return
        await self._pubsub.unsubscribe(*channels)
        self._subscribed_channels -= set(channels)

    async def publish(self, envelope: MessageEnvelope) -> None:
        """Publish a message to the appropriate channel."""
        if self._redis is None:
            raise RuntimeError("Transport not connected")
        channel = ChannelRouter.resolve_target(envelope)
        await self._redis.publish(channel, envelope.to_bytes())
        logger.debug(
            "Published %s -> %s on %s",
            envelope.source_agent_id, envelope.target_agent_id, channel,
        )

    async def publish_to_channel(self, channel: str, envelope: MessageEnvelope) -> None:
        """Publish a message to a specific channel (bypass routing)."""
        if self._redis is None:
            raise RuntimeError("Transport not connected")
        await self._redis.publish(channel, envelope.to_bytes())

    async def listen(self) -> AsyncIterator[bytes]:
        """Yield raw message bytes from all subscribed channels.

        This is the main consumption loop used by BaseAgent._run_loop().
        """
        if self._pubsub is None:
            raise RuntimeError("Transport not connected")
        async for message in self._pubsub.listen():
            if message["type"] == "message":
                yield message["data"]

    async def request(
        self,
        envelope: MessageEnvelope,
        timeout: float = 10.0,
    ) -> MessageEnvelope | None:
        """Send a message and wait for a correlated response.

        Creates a temporary reply channel, publishes the request,
        and waits for a response with matching correlation_id.
        Returns None on timeout.
        """
        if self._redis is None:
            raise RuntimeError("Transport not connected")

        reply_channel = f"fhamesh:reply:{uuid.uuid4().hex[:12]}"
        reply_pubsub = self._redis.pubsub()
        await reply_pubsub.subscribe(reply_channel)
        # Ensure subscription is active before publishing
        await asyncio.sleep(0.05)

        # Set the reply channel as target for the response
        data = envelope.to_dict()
        data["payload"] = {**data["payload"], "_reply_channel": reply_channel}
        request_envelope = MessageEnvelope.from_dict(data)
        logger.debug("request() publishing to %s, reply on %s", ChannelRouter.resolve_target(request_envelope), reply_channel)
        await self.publish(request_envelope)

        try:
            async with asyncio.timeout(timeout):
                async for message in reply_pubsub.listen():
                    if message["type"] == "message":
                        response = MessageEnvelope.from_bytes(message["data"])
                        if response.correlation_id == envelope.correlation_id:
                            return response
        except TimeoutError:
            logger.warning("Request timed out for %s", envelope.message_id)
            return None
        finally:
            await reply_pubsub.unsubscribe(reply_channel)
            await reply_pubsub.close()

        return None
