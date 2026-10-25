"""Intent classification for the edge layer.

Provides a working keyword+regex classifier out of the box.
Designed to be subclassed — plug in any NLU model (Ollama, HuggingFace,
spaCy, etc.) by overriding the classify() method.
"""

from __future__ import annotations

import abc
import hashlib
import logging
import re
from typing import Any

from ..core.message import IntentDescriptor
from ..core.types import IntentCategory

logger = logging.getLogger(__name__)


class BaseClassifier(abc.ABC):
    """Abstract interface for intent classifiers.

    Subclass this to plug in any classification backend. classify() is
    async so backends that reason over an LLM (see fhamesh.agents) can
    await a model call without blocking the agent's event loop.
    """

    @abc.abstractmethod
    async def classify(self, text: str, user_id: str = "") -> IntentDescriptor:
        """Classify sanitized user input into an IntentDescriptor.

        user_id is optional context for backends that keep short-term
        session memory (see fhamesh.leaf.memory.SessionMemory) — the
        regex classifier ignores it.
        """
        ...


class IntentClassifier(BaseClassifier):
    """Keyword + regex intent classifier.

    This is a real, working classifier — not a stub. It uses pattern
    matching to identify intent category, domain, and action. For
    production use, subclass and override classify() with an ML model.

    Patterns are loaded from the domains config.
    """

    def __init__(self, config: dict[str, Any] | None = None):
        config = config or {}
        self._min_confidence = config.get("min_confidence", 0.3)
        self._domain_patterns: dict[str, list[re.Pattern[str]]] = {}
        self._action_patterns: dict[str, list[tuple[str, re.Pattern[str]]]] = {}
        self._load_default_patterns()

    async def classify(self, text: str, user_id: str = "") -> IntentDescriptor:
        """Classify user input into structured intent.

        Returns IntentDescriptor with category, domain, action, and confidence.
        """
        text_lower = text.lower().strip()
        input_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()

        if not text_lower:
            return IntentDescriptor(
                category=IntentCategory.UNKNOWN.value,
                confidence=0.0,
                raw_input_hash=input_hash,
            )

        # Determine category
        category = self._classify_category(text_lower)

        # Determine domain and confidence
        domain, domain_confidence = self._classify_domain(text_lower)

        # Determine action
        action, action_confidence = self._classify_action(text_lower, domain)

        # Combined confidence
        confidence = (domain_confidence + action_confidence) / 2.0

        return IntentDescriptor(
            category=category,
            domain=domain,
            action=action,
            confidence=round(confidence, 3),
            raw_input_hash=input_hash,
        )

    def _classify_category(self, text: str) -> str:
        """Determine if the input is a query, command, or navigation."""
        command_words = {"set", "update", "change", "modify", "delete", "remove", "create", "add"}
        nav_words = {"go", "navigate", "open", "show", "display", "view"}
        query_words = {"what", "who", "where", "when", "how", "why", "find", "search", "list", "get", "fetch"}

        words = set(text.split())
        first_word = text.split()[0] if text.split() else ""

        if first_word in command_words or words & command_words:
            return IntentCategory.COMMAND.value
        if first_word in nav_words:
            return IntentCategory.NAVIGATION.value
        if "?" in text or first_word in query_words or words & query_words:
            return IntentCategory.QUERY.value

        # Default to query for natural language
        return IntentCategory.QUERY.value

    def _classify_domain(self, text: str) -> tuple[str, float]:
        """Match input against domain patterns. Returns (domain, confidence)."""
        best_domain = "general"
        best_score = 0.0

        for domain, patterns in self._domain_patterns.items():
            if domain == "general":
                continue
            for pattern in patterns:
                matches = pattern.findall(text)
                if matches:
                    score = min(1.0, len(matches) * 0.3 + 0.4)
                    if score > best_score:
                        best_score = score
                        best_domain = domain

        if best_score == 0.0:
            return "general", 0.3

        return best_domain, best_score

    def _classify_action(self, text: str, domain: str) -> tuple[str, float]:
        """Determine the specific action within a domain."""
        actions = self._action_patterns.get(domain, [])
        for action_name, pattern in actions:
            if pattern.search(text):
                return action_name, 0.7

        # Fallback actions by category
        if any(w in text for w in ("average", "avg", "mean", "sum", "total", "count")):
            return "aggregate", 0.6
        if any(w in text for w in ("list", "show", "all", "find", "search", "get")):
            return "lookup", 0.5

        return "general_query", 0.3

    def _load_default_patterns(self) -> None:
        """Load built-in domain and action patterns."""
        self._domain_patterns = {
            "hr": [
                re.compile(r"\b(salary|salaries|compensation|pay|wage)\b"),
                re.compile(r"\b(employee|employees|staff|personnel|worker)\b"),
                re.compile(r"\b(department|team|manager|hire|hiring|recruit)\b"),
                re.compile(r"\b(title|position|role|job)\b"),
            ],
            "finance": [
                re.compile(r"\b(order|orders|purchase|transaction)\b"),
                re.compile(r"\b(revenue|income|expense|cost|budget)\b"),
                re.compile(r"\b(invoice|payment|billing|amount)\b"),
            ],
            "product": [
                re.compile(r"\b(product|products|catalog|item|inventory)\b"),
                re.compile(r"\b(stock|price|pricing|category)\b"),
            ],
            "general": [re.compile(r".*")],
        }

        self._action_patterns = {
            "hr": [
                ("lookup_salary", re.compile(r"\b(salary|salaries|compensation|pay|wage)\b")),
                ("lookup_employee", re.compile(r"\b(employee|staff|personnel)\b.*\b(info|detail|data)\b")),
                ("list_department", re.compile(r"\b(department|team)\b.*\b(list|members|people)\b")),
            ],
            "finance": [
                ("lookup_order", re.compile(r"\b(order|orders)\b.*\b(detail|info|status)\b")),
                ("aggregate_revenue", re.compile(r"\b(revenue|total|sum)\b.*\b(order|sale)\b")),
                ("list_transactions", re.compile(r"\b(transaction|payment|invoice)\b.*\b(list|all|recent)\b")),
            ],
            "product": [
                ("lookup_product", re.compile(r"\b(product|item)\b.*\b(detail|info|price)\b")),
                ("list_catalog", re.compile(r"\b(catalog|inventory|stock)\b.*\b(list|all|available)\b")),
            ],
        }

    def configure_domain_patterns(
        self,
        domain: str,
        patterns: list[str],
    ) -> None:
        """Add or replace domain patterns at runtime."""
        self._domain_patterns[domain] = [re.compile(p) for p in patterns]
