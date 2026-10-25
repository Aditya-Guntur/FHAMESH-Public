"""Shared LLM client factory for LangGraph-backed reasoning agents.

Guards the langchain-ollama import so the rest of fhamesh can be
imported and run with zero extra dependencies. Callers check
AGENTS_AVAILABLE and fall back to a deterministic backend when it's
False, or when construction/inference raises at runtime (Ollama not
running, model not pulled, network error, etc).
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

try:
    from langchain_ollama import ChatOllama

    AGENTS_AVAILABLE = True
except ImportError:  # pragma: no cover - exercised by the "no [agents] extra" install
    ChatOllama = None  # type: ignore[assignment, misc]
    AGENTS_AVAILABLE = False


def build_ollama_llm(config: dict[str, Any] | None = None) -> ChatOllama | None:
    """Construct a ChatOllama client from config.

    Returns None if langchain-ollama isn't installed. Does not check
    whether an Ollama server is actually reachable — that's a runtime
    concern handled by the caller's fallback logic.
    """
    if not AGENTS_AVAILABLE:
        logger.debug("langchain-ollama not installed; LangGraph backends unavailable")
        return None

    config = config or {}
    timeout = config.get("timeout_seconds", 10.0)
    return ChatOllama(
        model=config.get("model", "llama3.2"),
        base_url=config.get("base_url", "http://localhost:11434"),
        temperature=config.get("temperature", 0.0),
        client_kwargs={"timeout": timeout},
        async_client_kwargs={"timeout": timeout},
    )
