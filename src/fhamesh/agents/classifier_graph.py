"""LangGraph intent-classification agent.

Two nodes:
- extract: an LLM call that reads the sanitized text and produces a
  structured IntentExtraction (category, domain, action, parameters,
  confidence)
- calibrate: a deterministic safety net that clamps confidence and
  demotes low-confidence extractions to UNKNOWN, exactly like the
  keyword classifier's min_confidence floor

LangGraphClassifier wraps the compiled graph behind BaseClassifier and
falls back to a plain keyword/regex classifier for any input where the
model is unreachable or returns something unusable.
"""

from __future__ import annotations

import hashlib
import logging
from typing import Any, TypedDict

from pydantic import BaseModel, Field

from ..core.message import IntentDescriptor
from ..core.types import IntentCategory
from ..leaf.classifier import BaseClassifier, IntentClassifier
from .llm import AGENTS_AVAILABLE, build_ollama_llm

logger = logging.getLogger(__name__)

if AGENTS_AVAILABLE:
    from langgraph.graph import END, START, StateGraph

_VALID_CATEGORIES = {c.value for c in IntentCategory}

_SYSTEM_PROMPT = (
    "You classify a single user query for a data-access system with three "
    "domains: hr (employees, salaries, departments), finance (orders, "
    "revenue, invoices), and product (catalog, inventory, pricing). "
    "Respond only with the structured fields asked for. Never invent data "
    "or answer the question itself — you are only classifying it."
)


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


class ClassifierState(TypedDict, total=False):
    text: str
    extraction: IntentExtraction
    intent: IntentDescriptor


class ClassificationGraph:
    """Compiled LangGraph pipeline: extract -> calibrate."""

    def __init__(self, llm: Any, min_confidence: float = 0.3):
        self._llm = llm.with_structured_output(IntentExtraction)
        self._min_confidence = min_confidence
        self._graph = self._build()

    def _build(self) -> Any:
        graph: StateGraph[ClassifierState] = StateGraph(ClassifierState)
        graph.add_node("extract", self._extract)
        graph.add_node("calibrate", self._calibrate)
        graph.add_edge(START, "extract")
        graph.add_edge("extract", "calibrate")
        graph.add_edge("calibrate", END)
        return graph.compile()

    async def _extract(self, state: ClassifierState) -> dict[str, Any]:
        extraction: IntentExtraction = await self._llm.ainvoke(
            [("system", _SYSTEM_PROMPT), ("human", state["text"])]
        )
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

    async def run(self, text: str) -> IntentDescriptor:
        result: ClassifierState = await self._graph.ainvoke({"text": text})
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
    ):
        config = config or {}
        self._min_confidence = config.get("min_confidence", 0.3)
        self._fallback = fallback or IntentClassifier(config)
        self._graph: ClassificationGraph | None = None

        llm = build_ollama_llm(config.get("ollama"))
        if llm is not None:
            self._graph = ClassificationGraph(llm, min_confidence=self._min_confidence)

    async def classify(self, text: str) -> IntentDescriptor:
        if not text.strip():
            return IntentDescriptor(
                category=IntentCategory.UNKNOWN.value,
                confidence=0.0,
                raw_input_hash=hashlib.sha256(text.encode("utf-8")).hexdigest(),
            )

        if self._graph is not None:
            try:
                return await self._graph.run(text)
            except Exception:
                logger.warning("LangGraph classifier unavailable, falling back to regex", exc_info=True)

        return await self._fallback.classify(text)
