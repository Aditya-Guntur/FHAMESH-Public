"""LangGraph query-planning agent.

Two nodes:
- plan: an LLM call that reads the already-classified IntentDescriptor
  (never raw user text) plus the known domain/table/field schema, and
  proposes the minimal set of sub-queries needed to answer it
- validate_plan: a deterministic safety net — every proposed sub-query
  is checked against DomainSchema; an unknown table or empty field
  list is corrected with the same resolution QueryDecomposer uses, so
  a bad model output can never produce an invalid query

QueryDecomposer (rule-based) is kept as the fallback. The LLM never
sees any row data here — decomposition happens before DataCore
executes anything.
"""

from __future__ import annotations

import logging
from typing import Any, TypedDict

from pydantic import BaseModel, Field

from ..core.message import IntentDescriptor
from ..orchestrator.decomposer import BaseDecomposer, QueryDecomposer
from ..orchestrator.schema import DomainSchema
from .llm import AGENTS_AVAILABLE, build_ollama_llm

logger = logging.getLogger(__name__)

if AGENTS_AVAILABLE:
    from langgraph.graph import END, START, StateGraph

_SYSTEM_PROMPT = (
    "You plan data queries for a system that only knows a fixed schema. "
    "Propose the minimal set of sub-queries needed to answer the user's "
    "intent. Use ONLY the tables and fields given to you — never invent "
    "one. Most intents need exactly one sub-query; only split into more "
    "when the intent genuinely spans multiple domains or asks to compare "
    "across tables."
)


class SubQueryPlan(BaseModel):
    table: str = Field(description="One of the known tables")
    fields: list[str] = Field(description="Fields to retrieve, from the known schema")
    filters: dict[str, Any] = Field(default_factory=dict)
    domain: str = Field(default="", description="Domain this sub-query targets")
    depends_on: list[int] = Field(
        default_factory=list,
        description="Indices of earlier sub-queries this one depends on, usually empty",
    )


class DecompositionPlan(BaseModel):
    sub_queries: list[SubQueryPlan] = Field(default_factory=list)


class PlannerState(TypedDict, total=False):
    intent: IntentDescriptor
    plan: DecompositionPlan
    sub_queries: list[dict[str, Any]]


class PlanningGraph:
    """Compiled LangGraph pipeline: plan -> validate_plan."""

    def __init__(self, llm: Any, schema: DomainSchema | None = None):
        self._llm = llm.with_structured_output(DecompositionPlan)
        self._schema = schema or DomainSchema()
        self._graph = self._build()

    def _build(self) -> Any:
        graph: StateGraph[PlannerState] = StateGraph(PlannerState)
        graph.add_node("plan", self._plan)
        graph.add_node("validate_plan", self._validate_plan)
        graph.add_edge(START, "plan")
        graph.add_edge("plan", "validate_plan")
        graph.add_edge("validate_plan", END)
        return graph.compile()

    async def _plan(self, state: PlannerState) -> dict[str, Any]:
        intent = state["intent"]
        human = (
            f"{self._schema.as_prompt_context()}\n\n"
            f"User intent: category={intent.category} domain={intent.domain} "
            f"action={intent.action} parameters={intent.parameters}"
        )
        plan: DecompositionPlan = await self._llm.ainvoke([("system", _SYSTEM_PROMPT), ("human", human)])
        return {"plan": plan}

    async def _validate_plan(self, state: PlannerState) -> dict[str, Any]:
        intent = state["intent"]
        plan = state["plan"]
        known_tables = set(self._schema.known_tables())

        sub_queries: list[dict[str, Any]] = []
        for sq in plan.sub_queries:
            domain = sq.domain or intent.domain
            table = sq.table if sq.table in known_tables else self._schema.resolve_table(domain)
            fields = sq.fields or self._schema.resolve_fields(domain, intent.action)
            justifications = {f: f"Requested via {intent.action} on {domain}" for f in fields}
            sub_queries.append({
                "table": table,
                "fields": fields,
                "filters": sq.filters,
                "justifications": justifications,
                "domain": domain,
                "depends_on": sq.depends_on,
            })

        if not sub_queries:
            sub_queries = [self._deterministic_single_query(intent)]

        return {"sub_queries": sub_queries}

    def _deterministic_single_query(self, intent: IntentDescriptor) -> dict[str, Any]:
        table = self._schema.resolve_table(intent.domain, intent.parameters.get("table"))
        fields = self._schema.resolve_fields(intent.domain, intent.action, intent.parameters.get("fields"))
        return {
            "table": table,
            "fields": fields,
            "filters": self._schema.resolve_filters(intent.parameters),
            "justifications": {f: f"Requested via {intent.action} on {intent.domain}" for f in fields},
            "domain": intent.domain,
            "depends_on": [],
        }

    async def run(self, intent: IntentDescriptor) -> list[dict[str, Any]]:
        result: PlannerState = await self._graph.ainvoke({"intent": intent})
        return result["sub_queries"]


class LangGraphDecomposer(BaseDecomposer):
    """BaseDecomposer backed by a LangGraph planner agent, with a rule fallback.

    Any failure while talking to the model, or a plan the model
    produces with no usable sub-queries, falls back to the rule-based
    QueryDecomposer for that single call.
    """

    def __init__(
        self,
        config: dict[str, Any] | None = None,
        fallback: BaseDecomposer | None = None,
    ):
        config = config or {}
        self._fallback = fallback or QueryDecomposer(config)
        self._graph: PlanningGraph | None = None

        llm = build_ollama_llm(config.get("ollama"))
        if llm is not None:
            self._graph = PlanningGraph(llm)

    async def decompose(self, intent: IntentDescriptor) -> list[dict[str, Any]]:
        if self._graph is not None:
            try:
                sub_queries = await self._graph.run(intent)
                if sub_queries:
                    return sub_queries
            except Exception:
                logger.warning("LangGraph planner unavailable, falling back to rules", exc_info=True)

        return await self._fallback.decompose(intent)
