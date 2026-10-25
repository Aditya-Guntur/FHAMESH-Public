"""Redis-backed agent registry.

Tracks all live agents in the mesh. Each agent registers on start,
heartbeats periodically, and deregisters on stop. Entries have TTL
so crashed agents auto-expire.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any

import redis.asyncio as aioredis

from .types import AgentLayer

logger = logging.getLogger(__name__)


class AgentRegistry:
    """Maintains a live registry of all agents in Redis.

    Each agent's record is stored as a Redis hash with a TTL.
    If an agent crashes, its record expires automatically.
    """

    KEY_PREFIX = "fhamesh:registry:"

    def __init__(self, redis_client: aioredis.Redis, ttl_seconds: int = 60):
        self._redis = redis_client
        self._ttl = ttl_seconds

    async def register(
        self,
        agent_id: str,
        layer: str,
        domain: str,
        channels: list[str],
    ) -> None:
        """Register an agent in the mesh."""
        key = f"{self.KEY_PREFIX}{agent_id}"
        data = {
            "agent_id": agent_id,
            "layer": layer,
            "domain": domain,
            "channels": json.dumps(channels),
            "registered_at": str(time.time()),
            "last_heartbeat": str(time.time()),
        }
        # Use hmset for Redis < 4.0 compatibility (hset mapping= needs 4.0+)
        for field, value in data.items():
            await self._redis.hset(key, field, value)
        await self._redis.expire(key, self._ttl)
        logger.info("Registered agent: %s (layer=%s, domain=%s)", agent_id, layer, domain)

    async def deregister(self, agent_id: str) -> None:
        """Remove an agent from the registry."""
        key = f"{self.KEY_PREFIX}{agent_id}"
        await self._redis.delete(key)
        logger.info("Deregistered agent: %s", agent_id)

    async def heartbeat(self, agent_id: str) -> None:
        """Refresh TTL and update last_heartbeat for an agent."""
        key = f"{self.KEY_PREFIX}{agent_id}"
        exists = await self._redis.exists(key)
        if exists:
            await self._redis.hset(key, "last_heartbeat", str(time.time()))
            await self._redis.expire(key, self._ttl)

    async def is_alive(self, agent_id: str) -> bool:
        """Check if an agent is currently registered."""
        key = f"{self.KEY_PREFIX}{agent_id}"
        return bool(await self._redis.exists(key))

    async def get_agent(self, agent_id: str) -> dict[str, Any] | None:
        """Get an agent's registry entry."""
        key = f"{self.KEY_PREFIX}{agent_id}"
        data = await self._redis.hgetall(key)
        if not data:
            return None
        return self._decode_entry(data)

    async def find_by_layer(self, layer: AgentLayer | str) -> list[dict[str, Any]]:
        """Find all agents in a given layer."""
        layer_val = layer.value if isinstance(layer, AgentLayer) else layer
        return await self._scan_filter("layer", layer_val)

    async def find_by_domain(
        self,
        domain: str,
        layer: AgentLayer | str | None = None,
    ) -> list[dict[str, Any]]:
        """Find agents for a specific domain, optionally filtered by layer."""
        agents = await self._scan_filter("domain", domain)
        if layer is not None:
            layer_val = layer.value if isinstance(layer, AgentLayer) else layer
            agents = [a for a in agents if a.get("layer") == layer_val]
        return agents

    async def find_one(
        self,
        domain: str,
        layer: AgentLayer | str,
    ) -> str | None:
        """Find a single agent ID for the given domain and layer."""
        agents = await self.find_by_domain(domain, layer)
        if agents:
            return agents[0]["agent_id"]
        return None

    async def list_all(self) -> list[dict[str, Any]]:
        """List all registered agents."""
        results = []
        async for key in self._redis.scan_iter(f"{self.KEY_PREFIX}*"):
            data = await self._redis.hgetall(key)
            if data:
                results.append(self._decode_entry(data))
        return results

    async def _scan_filter(self, field: str, value: str) -> list[dict[str, Any]]:
        """Scan registry and filter by a field value."""
        results = []
        async for key in self._redis.scan_iter(f"{self.KEY_PREFIX}*"):
            data = await self._redis.hgetall(key)
            if data:
                entry = self._decode_entry(data)
                if entry.get(field) == value:
                    results.append(entry)
        return results

    @staticmethod
    def _decode_entry(data: dict) -> dict[str, Any]:
        """Decode a Redis hash entry into a proper dict."""
        decoded = {}
        for k, v in data.items():
            key = k.decode("utf-8") if isinstance(k, bytes) else k
            val = v.decode("utf-8") if isinstance(v, bytes) else v
            decoded[key] = val
        if "channels" in decoded:
            try:
                decoded["channels"] = json.loads(decoded["channels"])
            except (json.JSONDecodeError, TypeError):
                decoded["channels"] = []
        return decoded
