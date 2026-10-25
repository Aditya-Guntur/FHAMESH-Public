"""Backend factories for the pluggable classifier/decomposer/aggregator.

Picks the LangGraph agent or the deterministic implementation based on
config, so LeafNode and OrchestratorNode don't need to know which
backend they ended up with.

backend values:
- "auto" (default): use the LangGraph agent if the [agents] extra is
  installed, otherwise the deterministic one. Construction never fails
  for "auto" even if Ollama itself is unreachable — that failure is
  handled per-call by the agent's own fallback.
- "langgraph": force the LangGraph agent; raises if the [agents]
  extra isn't installed.
- "regex" / "rules" / "merge": force the deterministic implementation,
  skip LangGraph entirely.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from .llm import AGENTS_AVAILABLE

if TYPE_CHECKING:
    from ..leaf.classifier import BaseClassifier
    from ..orchestrator.aggregator import BaseAggregator
    from ..orchestrator.decomposer import BaseDecomposer

logger = logging.getLogger(__name__)

# Imports of fhamesh.leaf / fhamesh.orchestrator are deliberately deferred
# to inside each build_*() function. Both those packages' __init__.py
# import this module (via LeafNode / OrchestratorNode), so importing them
# at module load time here would create a circular import.


def _merged(cfg: dict[str, Any] | None, agents_cfg: dict[str, Any] | None) -> dict[str, Any]:
    merged = dict(cfg or {})
    merged["ollama"] = (agents_cfg or {}).get("ollama", {})
    return merged


def _require_agents_extra(backend: str, section: str) -> None:
    if backend == "langgraph" and not AGENTS_AVAILABLE:
        raise RuntimeError(
            f"{section}.backend is 'langgraph' but the [agents] extra isn't "
            "installed. Run: pip install -e '.[agents]'"
        )


def build_classifier(
    cfg: dict[str, Any] | None = None,
    agents_cfg: dict[str, Any] | None = None,
    schema: Any | None = None,
) -> BaseClassifier:
    from ..leaf.classifier import IntentClassifier

    cfg = cfg or {}
    backend = cfg.get("backend", "auto")
    _require_agents_extra(backend, "classifier")

    if backend == "regex" or not AGENTS_AVAILABLE:
        return IntentClassifier(cfg)

    from .classifier_graph import LangGraphClassifier

    return LangGraphClassifier(_merged(cfg, agents_cfg), schema=schema)


def build_decomposer(
    cfg: dict[str, Any] | None = None,
    agents_cfg: dict[str, Any] | None = None,
    schema: Any | None = None,
) -> BaseDecomposer:
    from ..orchestrator.decomposer import QueryDecomposer

    cfg = cfg or {}
    backend = cfg.get("backend", "auto")
    _require_agents_extra(backend, "decomposition")

    if backend == "rules" or not AGENTS_AVAILABLE:
        return QueryDecomposer(cfg, schema=schema)

    from .decomposer_graph import LangGraphDecomposer

    return LangGraphDecomposer(_merged(cfg, agents_cfg), schema=schema)


def build_aggregator(
    cfg: dict[str, Any] | None = None,
    agents_cfg: dict[str, Any] | None = None,
) -> BaseAggregator:
    from ..orchestrator.aggregator import ResultAggregator

    cfg = cfg or {}
    backend = cfg.get("backend", "auto")
    _require_agents_extra(backend, "aggregation")

    if backend == "merge" or not AGENTS_AVAILABLE:
        return ResultAggregator()

    from .aggregator_graph import LangGraphAggregator

    return LangGraphAggregator(_merged(cfg, agents_cfg))
