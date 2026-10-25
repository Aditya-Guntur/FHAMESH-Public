"""Short-term conversation memory for the leaf layer.

Stores structured turns — domain, action, parameters — never raw user
text, matching the leaf layer's existing stance that IntentDescriptor
(not the original text) is the only thing that gets passed around or
persisted. This is what lets a follow-up like "and in sales?" get
classified using the previous turn's domain as context.

Redis-backed when a client is attached (shared across leaf instances),
with an in-memory fallback that keeps it fully testable without Redis.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any

logger = logging.getLogger(__name__)

_REDIS_KEY_PREFIX = "fhamesh:session:"
_DEFAULT_MAX_TURNS = 5
_DEFAULT_TTL_SECONDS = 1800  # 30 minutes


class SessionMemory:
    """Per-user short-term memory of recent classified turns."""

    def __init__(self, max_turns: int = _DEFAULT_MAX_TURNS, ttl_seconds: int = _DEFAULT_TTL_SECONDS):
        self._max_turns = max_turns
        self._ttl_seconds = ttl_seconds
        self._redis: Any | None = None
        self._local: dict[str, list[dict[str, Any]]] = {}

    def set_redis(self, redis_client: Any) -> None:
        """Attach a Redis client so memory is shared across leaf instances."""
        self._redis = redis_client

    async def record_turn(self, user_id: str, domain: str, action: str, parameters: dict[str, Any]) -> None:
        """Append one turn, trimmed to max_turns, with a TTL so it doesn't live forever."""
        if not user_id:
            return
        turn = {"domain": domain, "action": action, "parameters": parameters, "ts": time.time()}

        if self._redis is not None:
            key = _REDIS_KEY_PREFIX + user_id
            await self._redis.rpush(key, json.dumps(turn))
            await self._redis.ltrim(key, -self._max_turns, -1)
            await self._redis.expire(key, self._ttl_seconds)
            return

        turns = self._local.setdefault(user_id, [])
        turns.append(turn)
        del turns[: max(0, len(turns) - self._max_turns)]

    async def recall(self, user_id: str) -> list[dict[str, Any]]:
        """Return recent turns for a user, oldest first."""
        if not user_id:
            return []

        if self._redis is not None:
            key = _REDIS_KEY_PREFIX + user_id
            raw: list[Any] = await self._redis.lrange(key, 0, -1)
            turns: list[dict[str, Any]] = []
            for item in raw:
                item_str = item.decode() if isinstance(item, bytes) else item
                try:
                    turns.append(json.loads(item_str))
                except (ValueError, TypeError):
                    logger.warning("Skipping malformed session memory entry for user %s", user_id)
            return turns

        return list(self._local.get(user_id, []))

    def as_prompt_context(self, turns: list[dict[str, Any]]) -> str:
        """Render recalled turns as grounding context for an LLM prompt."""
        if not turns:
            return ""
        lines = ["Recent turns in this conversation, oldest first:"]
        for turn in turns:
            lines.append(f"- domain={turn.get('domain')} action={turn.get('action')} parameters={turn.get('parameters')}")
        return "\n".join(lines)
