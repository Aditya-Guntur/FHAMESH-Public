"""Redis-backed session management with TTL.

Sessions provide continuous re-authentication. Each session has a short
TTL and must be refreshed. If the TTL expires, the agent must re-authenticate.
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from typing import Any

import redis.asyncio as aioredis

logger = logging.getLogger(__name__)


class SessionManager:
    """Manages agent sessions in Redis with automatic TTL expiration."""

    KEY_PREFIX = "fhamesh:session:"

    def __init__(self, redis_client: aioredis.Redis, default_ttl: int = 60):
        self._redis = redis_client
        self._default_ttl = default_ttl

    async def create_session(
        self,
        agent_id: str,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        """Create a new session. Returns the session_id."""
        session_id = uuid.uuid4().hex
        data = {
            "session_id": session_id,
            "agent_id": agent_id,
            "created_at": time.time(),
            "metadata": metadata or {},
        }
        key = f"{self.KEY_PREFIX}{session_id}"
        await self._redis.setex(key, self._default_ttl, json.dumps(data, default=str))
        logger.debug("Session created: %s for agent %s", session_id, agent_id)
        return session_id

    async def validate_session(self, session_id: str) -> dict[str, Any] | None:
        """Return session data if valid, None if expired or not found."""
        key = f"{self.KEY_PREFIX}{session_id}"
        raw = await self._redis.get(key)
        if raw is None:
            return None
        return json.loads(raw)

    async def refresh_session(self, session_id: str) -> bool:
        """Extend the session's TTL. Returns False if already expired."""
        key = f"{self.KEY_PREFIX}{session_id}"
        exists = await self._redis.exists(key)
        if not exists:
            return False
        await self._redis.expire(key, self._default_ttl)
        return True

    async def destroy_session(self, session_id: str) -> None:
        """Explicitly destroy a session."""
        key = f"{self.KEY_PREFIX}{session_id}"
        await self._redis.delete(key)
        logger.debug("Session destroyed: %s", session_id)

    async def get_agent_session(self, agent_id: str) -> str | None:
        """Find a session ID for a given agent. Returns None if no active session."""
        # Scan for sessions belonging to this agent
        async for key in self._redis.scan_iter(f"{self.KEY_PREFIX}*"):
            raw = await self._redis.get(key)
            if raw:
                data = json.loads(raw)
                if data.get("agent_id") == agent_id:
                    return data["session_id"]
        return None
