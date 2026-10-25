"""LangGraph result-synthesis agent.

Two nodes:
- merge: the same deterministic merge ResultAggregator already does
  (sum privacy budget, union redacted fields, OR noise flags). This
  stays deterministic on purpose — privacy accounting is not something
  an LLM should approximate.
- synthesize: an LLM call that reads the merged, already
  privacy-protected data (post differential-privacy noise, post PII
  redaction) and writes a short natural-language summary. The model
  never sees anything that wasn't already safe to return to the user.

ResultAggregator (merge-only, no summary) is kept as the fallback.
"""

from __future__ import annotations

import logging
from typing import Any, TypedDict

from pydantic import BaseModel, Field

from ..core.message import QueryResult
from ..orchestrator.aggregator import BaseAggregator, ResultAggregator
from .llm import AGENTS_AVAILABLE, build_ollama_llm

logger = logging.getLogger(__name__)

if AGENTS_AVAILABLE:
    from langgraph.graph import END, START, StateGraph

_SYSTEM_PROMPT = (
    "You write a one or two sentence natural-language summary of already "
    "privacy-protected query result data for a business user. Only state "
    "what is in the data — never add, infer, or round numbers in a way that "
    "changes their meaning. Don't mention privacy mechanics unless the data "
    "itself flags that noise was applied."
)


class ResultSynthesis(BaseModel):
    summary: str = Field(description="One or two sentence natural-language summary of the result data")


class AggregatorState(TypedDict, total=False):
    results: list[QueryResult]
    merged: QueryResult
    summary: str


class SynthesisGraph:
    """Compiled LangGraph pipeline: merge -> synthesize."""

    def __init__(self, llm: Any, merger: ResultAggregator | None = None):
        self._llm = llm.with_structured_output(ResultSynthesis)
        self._merger = merger or ResultAggregator()
        self._graph = self._build()

    def _build(self) -> Any:
        graph: StateGraph[AggregatorState] = StateGraph(AggregatorState)
        graph.add_node("merge", self._merge)
        graph.add_node("synthesize", self._synthesize)
        graph.add_edge(START, "merge")
        graph.add_edge("merge", "synthesize")
        graph.add_edge("synthesize", END)
        return graph.compile()

    async def _merge(self, state: AggregatorState) -> dict[str, Any]:
        merged = await self._merger.aggregate(state["results"])
        return {"merged": merged}

    async def _synthesize(self, state: AggregatorState) -> dict[str, Any]:
        merged = state["merged"]
        if not merged.success or not merged.data:
            return {"summary": ""}

        human = f"Result data (already privacy-protected): {merged.data}"
        if merged.noise_applied:
            human += "\nDifferential privacy noise has been applied to numeric values."
        if merged.fields_redacted:
            human += f"\nFields redacted before you saw them: {merged.fields_redacted}"

        synthesis: ResultSynthesis = await self._llm.ainvoke(
            [("system", _SYSTEM_PROMPT), ("human", human)]
        )
        return {"summary": synthesis.summary}

    async def run(self, results: list[QueryResult]) -> QueryResult:
        state = await self._graph.ainvoke({"results": results})
        merged: QueryResult = state["merged"]
        merged.summary = state.get("summary", "")
        return merged


class LangGraphAggregator(BaseAggregator):
    """BaseAggregator backed by a LangGraph synthesis agent, with a merge-only fallback.

    The merge step is always deterministic. Only the natural-language
    summary depends on the model; if it's unreachable the result is
    still correct, just without a summary field.
    """

    def __init__(
        self,
        config: dict[str, Any] | None = None,
        fallback: BaseAggregator | None = None,
    ):
        config = config or {}
        self._fallback = fallback or ResultAggregator()
        self._graph: SynthesisGraph | None = None

        llm = build_ollama_llm(config.get("ollama"))
        if llm is not None:
            self._graph = SynthesisGraph(llm)

    @property
    def active_backend(self) -> str:
        """Returns 'langgraph' if the agent graph is ready, else the fallback's class name."""
        return "langgraph" if self._graph is not None else type(self._fallback).__name__

    async def aggregate(self, results: list[QueryResult]) -> QueryResult:
        if self._graph is not None:
            try:
                return await self._graph.run(results)
            except Exception:
                logger.warning("LangGraph synthesis unavailable, falling back to merge-only", exc_info=True)

        return await self._fallback.aggregate(results)
