"""LangGraph result-synthesis agent.

Five nodes:
- merge: the same deterministic merge ResultAggregator already does
  (sum privacy budget, union redacted fields, OR noise flags). This
  stays deterministic on purpose — privacy accounting is not something
  an LLM should approximate.
- reason: a tool-bound LLM that can call compute_percentage_change /
  format_currency on the already privacy-protected data instead of
  doing arithmetic itself
- tools: executes whatever tool call "reason" made, loops back to it
- synthesize: once reasoning is done, one structured-output call
  writes the summary
- verify: a second, independent LLM call checks the summary against
  the actual data and corrects or drops it if it doesn't hold up —
  catches a hallucinated or rounded-wrong number before it reaches
  the user

The model never sees anything that wasn't already safe to return to
the user — merge happens first, on data that's already DP-noised and
PII-redacted. ResultAggregator (merge-only, no summary) is the
fallback.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from typing import Annotated, Any, TypedDict

from pydantic import BaseModel, Field

from ..core.message import QueryResult
from ..orchestrator.aggregator import BaseAggregator, ResultAggregator
from .llm import AGENTS_AVAILABLE, build_ollama_llm
from .tools import build_synthesis_tools

logger = logging.getLogger(__name__)

if AGENTS_AVAILABLE:
    from langchain_core.messages import AIMessage, SystemMessage
    from langgraph.graph import END, START, StateGraph
    from langgraph.graph.message import add_messages
    from langgraph.prebuilt import ToolNode, tools_condition

_MAX_TOOL_ROUNDS = 3

_SYSTEM_PROMPT = (
    "You write a one or two sentence natural-language summary of already "
    "privacy-protected query result data for a business user. Only state "
    "what is in the data — never add or infer. If you need a percentage "
    "change or a formatted currency amount, call the tool for it instead "
    "of computing it yourself. Don't mention privacy mechanics unless the "
    "data itself flags that noise was applied."
)

_SYNTHESIZE_PROMPT = "Based on the conversation above, write the final summary."

_VERIFY_PROMPT = (
    "You fact-check a summary against the data it's supposed to describe. "
    "Flag anything invented, rounded in a misleading way, or not actually "
    "present in the data. If the summary is fine, say so and leave "
    "corrected_summary empty."
)


class ResultSynthesis(BaseModel):
    summary: str = Field(description="One or two sentence natural-language summary of the result data")


class VerificationResult(BaseModel):
    consistent: bool = Field(description="True if the summary accurately reflects the data")
    corrected_summary: str = Field(
        default="",
        description="A corrected summary using only facts in the data, if consistent is false. "
        "Leave empty if consistent is true.",
    )
    issues: list[str] = Field(default_factory=list, description="Specific problems found, if any")


if AGENTS_AVAILABLE:
    class AggregatorState(TypedDict, total=False):
        results: list[QueryResult]
        merged: QueryResult
        messages: Annotated[list[Any], add_messages]
        tool_rounds: int
        summary: str
else:  # pragma: no cover - exercised by the "no [agents] extra" install
    class AggregatorState(TypedDict, total=False):  # type: ignore[no-redef]
        results: list[QueryResult]
        merged: QueryResult
        tool_rounds: int
        summary: str


class SynthesisGraph:
    """Compiled LangGraph pipeline: merge -> reason <-> tools -> synthesize -> verify."""

    def __init__(self, llm: Any, merger: ResultAggregator | None = None):
        self._raw_llm = llm
        self._tools = build_synthesis_tools()
        self._tool_llm = llm.bind_tools(self._tools)
        self._synthesis_llm = llm.with_structured_output(ResultSynthesis)
        self._verify_llm = llm.with_structured_output(VerificationResult)
        self._merger = merger or ResultAggregator()
        self._graph = self._build()

    def _build(self) -> Any:
        graph: StateGraph[AggregatorState] = StateGraph(AggregatorState)
        graph.add_node("merge", self._merge)
        graph.add_node("reason", self._reason)
        graph.add_node("tools", ToolNode(self._tools))
        graph.add_node("synthesize", self._synthesize)
        graph.add_node("verify", self._verify)
        graph.add_edge(START, "merge")
        graph.add_conditional_edges("merge", self._route_after_merge, {"reason": "reason", "end": END})
        graph.add_conditional_edges("reason", self._route_after_reason, {"tools": "tools", "synthesize": "synthesize"})
        graph.add_edge("tools", "reason")
        graph.add_edge("synthesize", "verify")
        graph.add_edge("verify", END)
        return graph.compile()

    def _route_after_merge(self, state: AggregatorState) -> str:
        merged = state["merged"]
        return "reason" if merged.success and merged.data else "end"

    def _route_after_reason(self, state: AggregatorState) -> str:
        if state.get("tool_rounds", 0) >= _MAX_TOOL_ROUNDS:
            return "synthesize"
        return tools_condition(dict(state), messages_key="messages").replace("__end__", "synthesize")

    async def _merge(self, state: AggregatorState) -> dict[str, Any]:
        merged = await self._merger.aggregate(state["results"])
        return {"merged": merged}

    async def _reason(self, state: AggregatorState) -> dict[str, Any]:
        existing = state.get("messages") or []
        new_messages: list[Any] = []

        if not existing:
            merged = state["merged"]
            human = f"Result data (already privacy-protected): {merged.data}"
            if merged.noise_applied:
                human += "\nDifferential privacy noise has been applied to numeric values."
            if merged.fields_redacted:
                human += f"\nFields redacted before you saw them: {merged.fields_redacted}"
            new_messages = [SystemMessage(content=_SYSTEM_PROMPT), ("human", human)]
            existing = new_messages

        response: AIMessage = await self._tool_llm.ainvoke(existing)
        increment = 1 if getattr(response, "tool_calls", None) else 0
        return {"messages": [*new_messages, response], "tool_rounds": state.get("tool_rounds", 0) + increment}

    async def _synthesize(self, state: AggregatorState) -> dict[str, Any]:
        messages = list(state.get("messages", [])) + [("human", _SYNTHESIZE_PROMPT)]
        synthesis: ResultSynthesis = await self._synthesis_llm.ainvoke(messages)
        return {"summary": synthesis.summary}

    async def _verify(self, state: AggregatorState) -> dict[str, Any]:
        summary = state.get("summary", "")
        if not summary:
            return {}

        merged = state["merged"]
        human = f"Data: {merged.data}\nDraft summary: {summary}"
        result: VerificationResult = await self._verify_llm.ainvoke(
            [("system", _VERIFY_PROMPT), ("human", human)]
        )

        if result.consistent:
            return {}
        if result.corrected_summary:
            logger.warning("Synthesis verification corrected the summary: %s", result.issues)
            return {"summary": result.corrected_summary}
        logger.warning("Synthesis verification rejected the summary with no correction: %s", result.issues)
        return {"summary": ""}

    async def run(self, results: list[QueryResult]) -> QueryResult:
        state = await self._graph.ainvoke({"results": results})
        merged: QueryResult = state["merged"]
        merged.summary = state.get("summary", "")
        return merged

    async def astream(self, results: list[QueryResult]) -> AsyncIterator[str]:
        """Stream a live text preview of the summary as it's generated.

        This is a separate, simpler pass than run(): no tool loop, no
        verification — just the raw model streaming tokens for a fast
        first-byte UX while the user waits. run() is still what
        produces the authoritative, verified QueryResult.summary;
        callers that stream should still call run() afterward (or in
        parallel) and treat these chunks as a preview, not the final
        answer. Yields nothing if there's no data to summarize.
        """
        merged = await self._merger.aggregate(results)
        if not merged.success or not merged.data:
            return

        human = f"Result data (already privacy-protected): {merged.data}"
        if merged.noise_applied:
            human += "\nDifferential privacy noise has been applied to numeric values."

        async for chunk in self._raw_llm.astream([("system", _SYSTEM_PROMPT), ("human", human)]):
            content = getattr(chunk, "content", "")
            if content:
                yield content


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

    @property
    def can_stream(self) -> bool:
        """True if there's a live model to stream a preview from."""
        return self._graph is not None

    async def astream_summary(self, results: list[QueryResult]) -> AsyncIterator[str]:
        """Stream a live text preview. Yields nothing if can_stream is False.

        Callers must still call aggregate() for the authoritative,
        verified QueryResult.summary — this is a preview, not a
        replacement.
        """
        if self._graph is None:
            return
        try:
            async for chunk in self._graph.astream(results):
                yield chunk
        except Exception:
            logger.warning("Streaming synthesis preview failed, no chunks sent", exc_info=True)
