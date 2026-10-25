"""Domain routing for the edge layer.

Maps IntentDescriptors to target orchestrator domains. Routing table
is loaded from config/domains.yaml or can be configured at runtime.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from ..core.message import IntentDescriptor

logger = logging.getLogger(__name__)


class DomainRouter:
    """Routes intents to the appropriate orchestrator domain.

    Uses the intent's domain field as primary routing key, with
    pattern-based fallback matching from config.
    """

    def __init__(self, config: dict[str, Any] | None = None):
        config = config or {}
        self._routes: dict[str, str] = {}
        self._patterns: dict[str, list[re.Pattern[str]]] = {}
        self._load_config(config)

    def resolve(self, intent: IntentDescriptor) -> str:
        """Determine the target orchestrator domain for an intent.

        Priority:
        1. Direct mapping from intent.domain
        2. Pattern matching against intent parameters
        3. Fallback to 'general'
        """
        # Direct mapping
        if intent.domain in self._routes:
            return self._routes[intent.domain]

        # Already a known domain
        if intent.domain != "general" and intent.domain in self._routes.values():
            return intent.domain

        # Fallback
        return "general"

    def _load_config(self, config: dict[str, Any]) -> None:
        """Load routing table from domains config."""
        domains = config.get("domains", config)
        for domain_name, domain_data in domains.items():
            if isinstance(domain_data, dict):
                target = domain_data.get("orchestrator_domain", domain_name)
                self._routes[domain_name] = target
                patterns = domain_data.get("intent_patterns", [])
                self._patterns[domain_name] = [re.compile(p) for p in patterns]
            else:
                self._routes[domain_name] = domain_name

    def add_route(self, domain: str, orchestrator_domain: str) -> None:
        """Add or update a routing entry at runtime."""
        self._routes[domain] = orchestrator_domain
