"""LangGraph intent-classification agent.

Six nodes:
- recall: reads recent structured turns for this user from
  SessionMemory, so "and in sales?" can be classified using the
  previous turn's domain as context — never raw text is stored or
  recalled, only domain/action/parameters
- reason: a tool-bound LLM that can call list_domains / describe_domain
  before committing to a domain, instead of guessing from a static
  system-prompt list — this is how a dynamically registered domain
  (see DynamicSchemaRegistry) becomes classifiable without a redeploy
- tools: executes whatever tool call "reason" made, loops back to it
- extract: once reasoning is done, one structured-output call produces
  IntentExtraction (category, domain, action, parameters, confidence)
- calibrate: a deterministic safety net that clamps confidence and
  demotes low-confidence extractions to UNKNOWN, exactly like the
  keyword classifier's min_confidence floor
- record: writes the new turn back to SessionMemory for next time

LangGraphClassifier wraps the compiled graph behind BaseClassifier and
falls back to a plain keyword/regex classifier for any input where the
model is unreachable or returns something unusable.
"""

from __future__ import annotations

import hashlib
import logging
from typing import TYPE_CHECKING, Annotated, Any, TypedDict

from pydantic import BaseModel, Field

from ..core.message import IntentDescriptor
from ..core.types import IntentCategory
from ..leaf.classifier import BaseClassifier, IntentClassifier
from ..orchestrator.schema_registry import DynamicSchemaRegistry
from .llm import AGENTS_AVAILABLE, build_ollama_llm
from .tools import build_schema_tools

if TYPE_CHECKING:
    from ..leaf.memory import SessionMemory

logger = logging.getLogger(__name__)

if AGENTS_AVAILABLE:
    from langchain_core.messages import AIMessage, SystemMessage
    from langgraph.graph import END, START, StateGraph
    from langgraph.graph.message import add_messages
    from langgraph.prebuilt import ToolNode, tools_condition

_MAX_TOOL_ROUNDS = 3

_VALID_CATEGORIES = {c.value for c in IntentCategory}

_SYSTEM_PROMPT = (
    "You classify a single user query for a data-access system. Use "
    "list_domains and describe_domain if you're unsure which domain this "
    "belongs to — don't guess at a domain you haven't confirmed exists. "
    "Once you know enough, stop calling tools and wait to be asked for the "
    "final classification. Never invent data or answer the question itself "
    "— you are only classifying it."
)

_EXTRACT_PROMPT = "Based on the conversation above, produce the final structured classification."


class IntentExtraction(BaseModel):
    """Structured output the LLM must produce for one piece of user input."""

    category: str = Field(description="One of: query, command, navigation, unknown")
    domain: str = Field(description="One of: hr, finance, product, general")
    action: str = Field(
        description="Short snake_case action, e.g. lookup_salary, aggregate_revenue, "
        "list_catalog, general_query"
    )
    confidence: float = Field(ge=0.0, le=1.0, description="Confidence in this classification")
    parameters: dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "Extracted filter values such as department, customer, category, "
            "date_from, date_to. If the question genuinely spans more than one "
            "domain, also set cross_domain=true and domains=[...]."
        ),
    )


if AGENTS_AVAILABLE:
    class ClassifierState(TypedDict, total=False):
        text: str
        user_id: str
        history_context: str
        messages: Annotated[list[Any], add_messages]
        tool_rounds: int
        extraction: IntentExtraction
        intent: IntentDescriptor
else:  # pragma: no cover - exercised by the "no [agents] extra" install
    class ClassifierState(TypedDict, total=False):  # type: ignore[no-redef]
        text: str
        user_id: str
        tool_rounds: int
        extraction: Any
        intent: IntentDescriptor


class ClassificationGraph:
    """Compiled LangGraph pipeline: recall -> reason <-> tools -> extract -> calibrate -> record."""

    def __init__(
        self,
        llm: Any,
        min_confidence: float = 0.3,
        schema: Any | None = None,
        memory: SessionMemory | None = None,
    ):
        self._schema = schema if schema is not None else DynamicSchemaRegistry()
        self._memory = memory
        self._tools = build_schema_tools(self._schema)
        self._tool_llm = llm.bind_tools(self._tools)
        self._structured_llm = llm.with_structured_output(IntentExtraction)
        self._min_confidence = min_confidence
        self._graph = self._build()

    def _build(self) -> Any:
        graph: StateGraph[ClassifierState] = StateGraph(ClassifierState)
        graph.add_node("recall", self._recall)
        graph.add_node("reason", self._reason)
        graph.add_node("tools", ToolNode(self._tools))
        graph.add_node("extract", self._extract)
        graph.add_node("calibrate", self._calibrate)
        graph.add_node("record", self._record)
        graph.add_edge(START, "recall")
        graph.add_edge("recall", "reason")
        graph.add_conditional_edges("reason", self._route_after_reason, {"tools": "tools", "extract": "extract"})
        graph.add_edge("tools", "reason")
        graph.add_edge("extract", "calibrate")
        graph.add_edge("calibrate", "record")
        graph.add_edge("record", END)
        return graph.compile()

    def _route_after_reason(self, state: ClassifierState) -> str:
        if state.get("tool_rounds", 0) >= _MAX_TOOL_ROUNDS:
            return "extract"
        return tools_condition(dict(state), messages_key="messages").replace("__end__", "extract")

    async def _recall(self, state: ClassifierState) -> dict[str, Any]:
        if self._memory is None:
            return {"history_context": ""}
        turns = await self._memory.recall(state.get("user_id", ""))
        return {"history_context": self._memory.as_prompt_context(turns)}

    async def _reason(self, state: ClassifierState) -> dict[str, Any]:
        existing = state.get("messages") or []
        new_messages: list[Any] = []

        if not existing:
            human = state["text"]
            history_context = state.get("history_context", "")
            if history_context:
                human = f"{history_context}\n\nCurrent message: {state['text']}"
            new_messages = [SystemMessage(content=_SYSTEM_PROMPT), ("human", human)]
            existing = new_messages

        response: AIMessage = await self._tool_llm.ainvoke(existing)
        increment = 1 if getattr(response, "tool_calls", None) else 0
        return {"messages": [*new_messages, response], "tool_rounds": state.get("tool_rounds", 0) + increment}

    async def _extract(self, state: ClassifierState) -> dict[str, Any]:
        messages = list(state.get("messages", [])) + [("human", _EXTRACT_PROMPT)]
        extraction: IntentExtraction = await self._structured_llm.ainvoke(messages)
        return {"extraction": extraction}

    async def _calibrate(self, state: ClassifierState) -> dict[str, Any]:
        extraction = state["extraction"]
        text = state["text"]
        input_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()

        confidence = max(0.0, min(1.0, extraction.confidence))
        category = (
            extraction.category if extraction.category in _VALID_CATEGORIES
            else IntentCategory.QUERY.value
        )
        if confidence < self._min_confidence:
            category = IntentCategory.UNKNOWN.value

        intent = IntentDescriptor(
            category=category,
            domain=extraction.domain or "general",
            action=extraction.action or "general_query",
            confidence=round(confidence, 3),
            parameters=extraction.parameters,
            raw_input_hash=input_hash,
        )
        return {"intent": intent}

    async def _record(self, state: ClassifierState) -> dict[str, Any]:
        if self._memory is not None:
            intent = state["intent"]
            await self._memory.record_turn(state.get("user_id", ""), intent.domain, intent.action, intent.parameters)
        return {}

    async def run(self, text: str, user_id: str = "") -> IntentDescriptor:
        result: ClassifierState = await self._graph.ainvoke({"text": text, "user_id": user_id})
        return result["intent"]


class LangGraphClassifier(BaseClassifier):
    """BaseClassifier backed by a LangGraph agent, with a regex fallback.

    Any failure while talking to the model (Ollama down, model not
    pulled, timeout, malformed output) falls back to the keyword/regex
    IntentClassifier for that single call — the mesh keeps working,
    just with less precise classification until the model is back.
    """

    def __init__(
        self,
        config: dict[str, Any] | None = None,
        fallback: BaseClassifier | None = None,
        schema: Any | None = None,
        memory: SessionMemory | None = None,
    ):
        config = config or {}
        self._min_confidence = config.get("min_confidence", 0.3)
        self._fallback = fallback or IntentClassifier(config)
        self._graph: ClassificationGraph | None = None

        llm = build_ollama_llm(config.get("ollama"))
        if llm is not None:
            self._graph = ClassificationGraph(llm, min_confidence=self._min_confidence, schema=schema, memory=memory)

    @property
    def active_backend(self) -> str:
        """Returns 'langgraph' if the agent graph is ready, else the fallback's class name."""
        return "langgraph" if self._graph is not None else type(self._fallback).__name__

    async def classify(self, text: str, user_id: str = "") -> IntentDescriptor:
        if not text.strip():
            return IntentDescriptor(
                category=IntentCategory.UNKNOWN.value,
                confidence=0.0,
                raw_input_hash=hashlib.sha256(text.encode("utf-8")).hexdigest(),
            )

        if self._graph is not None:
            try:
                return await self._graph.run(text, user_id=user_id)
            except Exception:
                logger.warning("LangGraph classifier unavailable, falling back to regex", exc_info=True)

        return await self._fallback.classify(text, user_id=user_id)
