"""LangGraph query-planning agent.

Four nodes, a real ReAct-style tool loop plus two deterministic safety nets:
- reason: a tool-bound LLM that can call list_domains / describe_domain
  to explore the schema (including domains registered at runtime)
  instead of having it dumped whole into the prompt
- tools: executes whatever tool call "reason" made, loops back to it
- finalize: once reasoning is done, one structured-output call turns
  the conversation into a DecompositionPlan
- validate_plan: a deterministic safety net — every proposed sub-query
  is checked against the schema; an unknown table or empty field list
  is corrected with the same resolution QueryDecomposer uses, so a bad
  model output can never produce an invalid query

QueryDecomposer (rule-based) is kept as the fallback. The LLM never
sees any row data here — decomposition happens before DataCore
executes anything.
"""

from __future__ import annotations

import logging
from typing import Annotated, Any, TypedDict

from pydantic import BaseModel, Field

from ..core.message import IntentDescriptor
from ..orchestrator.decomposer import BaseDecomposer, QueryDecomposer
from ..orchestrator.schema import DomainSchema
from ..orchestrator.schema_registry import DynamicSchemaRegistry
from .llm import AGENTS_AVAILABLE, build_ollama_llm
from .tools import build_schema_tools

logger = logging.getLogger(__name__)

if AGENTS_AVAILABLE:
    from langchain_core.messages import AIMessage, SystemMessage
    from langgraph.graph import END, START, StateGraph
    from langgraph.graph.message import add_messages
    from langgraph.prebuilt import ToolNode, tools_condition

_MAX_TOOL_ROUNDS = 4

_SYSTEM_PROMPT = (
    "You plan data queries for a system with a schema you don't fully know "
    "yet. Use list_domains and describe_domain to look up what's actually "
    "available before proposing anything — never guess a table or field "
    "name. Most intents need exactly one sub-query; only split into more "
    "when the intent genuinely spans multiple domains or asks to compare "
    "across tables. Once you know enough, stop calling tools."
)

_FINALIZE_PROMPT = (
    "Based on the conversation above, produce the final structured plan: "
    "the minimal set of sub-queries needed to answer the user's intent, "
    "using only tables/fields you actually saw described."
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


if AGENTS_AVAILABLE:
    class PlannerState(TypedDict, total=False):
        intent: IntentDescriptor
        messages: Annotated[list[Any], add_messages]
        tool_rounds: int
        plan: DecompositionPlan
        sub_queries: list[dict[str, Any]]
else:  # pragma: no cover - exercised by the "no [agents] extra" install
    class PlannerState(TypedDict, total=False):  # type: ignore[no-redef]
        intent: IntentDescriptor
        tool_rounds: int
        plan: Any
        sub_queries: list[dict[str, Any]]


class PlanningGraph:
    """Compiled LangGraph pipeline: reason <-> tools -> finalize -> validate_plan."""

    def __init__(self, llm: Any, schema: DomainSchema | Any | None = None):
        self._schema = schema if schema is not None else DynamicSchemaRegistry()
        self._tools = build_schema_tools(self._schema)
        self._tool_llm = llm.bind_tools(self._tools)
        self._structured_llm = llm.with_structured_output(DecompositionPlan)
        self._graph = self._build()

    def _build(self) -> Any:
        graph: StateGraph[PlannerState] = StateGraph(PlannerState)
        graph.add_node("reason", self._reason)
        graph.add_node("tools", ToolNode(self._tools))
        graph.add_node("finalize", self._finalize)
        graph.add_node("validate_plan", self._validate_plan)
        graph.add_edge(START, "reason")
        graph.add_conditional_edges("reason", self._route_after_reason, {"tools": "tools", "finalize": "finalize"})
        graph.add_edge("tools", "reason")
        graph.add_edge("finalize", "validate_plan")
        graph.add_edge("validate_plan", END)
        return graph.compile()

    def _route_after_reason(self, state: PlannerState) -> str:
        if state.get("tool_rounds", 0) >= _MAX_TOOL_ROUNDS:
            return "finalize"
        return tools_condition(dict(state), messages_key="messages").replace("__end__", "finalize")

    async def _reason(self, state: PlannerState) -> dict[str, Any]:
        existing = state.get("messages") or []
        new_messages: list[Any] = []

        if not existing:
            intent = state["intent"]
            human = (
                f"User intent: category={intent.category} domain={intent.domain} "
                f"action={intent.action} parameters={intent.parameters}"
            )
            new_messages = [SystemMessage(content=_SYSTEM_PROMPT), ("human", human)]
            existing = new_messages

        response: AIMessage = await self._tool_llm.ainvoke(existing)
        increment = 1 if getattr(response, "tool_calls", None) else 0
        # new_messages (the seed, only present on the first call) plus the
        # response both get appended to state via the add_messages reducer.
        return {"messages": [*new_messages, response], "tool_rounds": state.get("tool_rounds", 0) + increment}

    async def _finalize(self, state: PlannerState) -> dict[str, Any]:
        messages = list(state.get("messages", [])) + [("human", _FINALIZE_PROMPT)]
        plan: DecompositionPlan = await self._structured_llm.ainvoke(messages)
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
        schema: DomainSchema | Any | None = None,
    ):
        config = config or {}
        self._fallback = fallback or QueryDecomposer(config, schema=schema)
        self._graph: PlanningGraph | None = None

        llm = build_ollama_llm(config.get("ollama"))
        if llm is not None:
            self._graph = PlanningGraph(llm, schema=schema)

    @property
    def active_backend(self) -> str:
        """Returns 'langgraph' if the agent graph is ready, else the fallback's class name."""
        return "langgraph" if self._graph is not None else type(self._fallback).__name__

    async def decompose(self, intent: IntentDescriptor) -> list[dict[str, Any]]:
        if self._graph is not None:
            try:
                sub_queries = await self._graph.run(intent)
                if sub_queries:
                    return sub_queries
            except Exception:
                logger.warning("LangGraph planner unavailable, falling back to rules", exc_info=True)

        return await self._fallback.decompose(intent)
