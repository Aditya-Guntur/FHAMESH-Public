"""Runtime-extensible schema registry.

DomainSchema is static — every table/field is hardcoded. This wraps it
with domains that can be registered at runtime (no code change, no
redeploy), shared mesh-wide through Redis when a client is attached —
same pattern AgentRegistry uses for agent discovery — and fully usable
without Redis too, so it stays testable with nothing but a plain dict.

Used by the LangGraph planner's schema tools (see
fhamesh.agents.tools) so an LLM can look up or extend the schema
instead of it being dumped whole into every prompt.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from .schema import DomainSchema

logger = logging.getLogger(__name__)

_REDIS_KEY = "fhamesh:schema:dynamic_domains"


class DynamicSchemaRegistry:
    """DomainSchema plus runtime-registered domains."""

    def __init__(self, base: DomainSchema | None = None):
        self._base = base or DomainSchema()
        self._redis: Any | None = None
        self._dynamic: dict[str, dict[str, Any]] = {}

    def set_redis(self, redis_client: Any) -> None:
        """Attach a Redis client so registrations are shared mesh-wide."""
        self._redis = redis_client

    async def load(self) -> None:
        """Hydrate dynamic registrations from Redis, if a client is attached."""
        if self._redis is None:
            return
        raw: dict[Any, Any] = await self._redis.hgetall(_REDIS_KEY)
        for domain_key, payload_value in raw.items():
            domain = domain_key.decode() if isinstance(domain_key, bytes) else domain_key
            payload = payload_value.decode() if isinstance(payload_value, bytes) else payload_value
            try:
                self._dynamic[domain] = json.loads(payload)
            except (ValueError, TypeError):
                logger.warning("Skipping malformed schema registration for domain %s", domain)

    async def register_domain(self, domain: str, table: str, actions: dict[str, list[str]]) -> None:
        """Register a new domain at runtime."""
        entry = {"table": table, "actions": actions}
        self._dynamic[domain] = entry
        if self._redis is not None:
            await self._redis.hset(_REDIS_KEY, domain, json.dumps(entry))
        logger.info("Registered dynamic domain %s -> table %s", domain, table)

    def known_domains(self) -> list[str]:
        return sorted(set(self._base.known_domains()) | set(self._dynamic))

    def known_tables(self) -> list[str]:
        dynamic_tables = {entry["table"] for entry in self._dynamic.values()}
        return sorted(set(self._base.known_tables()) | dynamic_tables)

    def resolve_table(self, domain: str, explicit: str | None = None) -> str:
        if explicit:
            return explicit
        if domain in self._dynamic:
            return str(self._dynamic[domain]["table"])
        return self._base.resolve_table(domain)

    def resolve_fields(self, domain: str, action: str, explicit: list[str] | None = None) -> list[str]:
        if explicit:
            return explicit
        if domain in self._dynamic:
            actions: dict[str, list[str]] = self._dynamic[domain]["actions"]
            if action in actions:
                return actions[action]
            return next(iter(actions.values()), ["*"])
        return self._base.resolve_fields(domain, action)

    def resolve_filters(self, parameters: dict[str, Any]) -> dict[str, Any]:
        return self._base.resolve_filters(parameters)

    def describe_domain(self, domain: str) -> str:
        """One-line description of a domain's table/fields."""
        if domain in self._dynamic:
            entry = self._dynamic[domain]
            actions = ", ".join(f"{a} -> {fields}" for a, fields in entry["actions"].items())
            return f"{domain} (dynamically registered): table={entry['table']}; actions: {actions}"
        if domain in self._base.known_domains():
            for line in self._base.as_prompt_context().splitlines():
                if line.startswith(f"- {domain}:"):
                    return line[2:]
        return f"Unknown domain '{domain}'. Known domains: {', '.join(self.known_domains())}"

    def as_prompt_context(self) -> str:
        lines = [self._base.as_prompt_context()]
        for domain, entry in sorted(self._dynamic.items()):
            actions = ", ".join(f"{a} -> {fields}" for a, fields in entry["actions"].items())
            lines.append(f"- {domain} (dynamic): table={entry['table']}; actions: {actions}")
        return "\n".join(lines)
