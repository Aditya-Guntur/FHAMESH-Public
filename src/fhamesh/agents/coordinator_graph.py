"""LangGraph cross-domain consensus agent.

Used when an intent is marked cross_domain=True and its sub-queries
genuinely span more than one domain. Instead of firing independent
sub-queries and merging whatever comes back, this asks each target
domain's own orchestrator — over the mesh's existing PeerMesh, never a
shared database — what it knows that's relevant, then an LLM
negotiates a final plan incorporating that context.

Three nodes:
- gather_peer_context: calls peer_query_fn once per target domain
  (other than the requesting orchestrator's own domain)
- negotiate: an LLM call that adjusts the draft sub-queries using
  whatever peer context came back — it cannot change which table or
  domain a sub-query targets, only fields/filters
- finalize: the same deterministic schema validation every plan goes
  through before reaching DataCore

peer_query_fn is injected so this is testable without a live mesh —
OrchestratorNode wires it to PeerMesh.request_peer.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any, TypedDict

from pydantic import BaseModel, Field

from ..core.message import IntentDescriptor
from ..orchestrator.schema import DomainSchema
from .llm import AGENTS_AVAILABLE

logger = logging.getLogger(__name__)

if AGENTS_AVAILABLE:
    from langgraph.graph import END, START, StateGraph

if TYPE_CHECKING:
    from ..core.message import MessageEnvelope

PeerQueryFn = Callable[[str, dict[str, Any], "MessageEnvelope"], Awaitable[dict[str, Any] | None]]

_NEGOTIATE_PROMPT = (
    "You're reconciling a cross-domain query plan with context each target "
    "domain's own orchestrator just provided about itself. Adjust filters "
    "or fields only where a peer's context justifies it — never invent a "
    "field, and never change which table or domain a sub-query targets. "
    "If no peer context is useful, return the draft sub-queries unchanged."
)


class NegotiatedSubQuery(BaseModel):
    table: str
    fields: list[str] = Field(default_factory=list)
    filters: dict[str, Any] = Field(default_factory=dict)
    domain: str
    depends_on: list[int] = Field(default_factory=list)


class NegotiatedPlan(BaseModel):
    sub_queries: list[NegotiatedSubQuery] = Field(default_factory=list)
    notes: str = Field(default="", description="Brief explanation of what changed and why, if anything")


class CoordinatorState(TypedDict, total=False):
    intent: IntentDescriptor
    draft_sub_queries: list[dict[str, Any]]
    envelope: Any
    peer_context: dict[str, Any]
    plan: NegotiatedPlan
    sub_queries: list[dict[str, Any]]


class CoordinatorGraph:
    """Compiled LangGraph pipeline: gather_peer_context -> negotiate -> finalize."""

    def __init__(self, llm: Any, peer_query_fn: PeerQueryFn, schema: DomainSchema | Any | None = None):
        self._llm = llm.with_structured_output(NegotiatedPlan)
        self._peer_query_fn = peer_query_fn
        self._schema = schema if schema is not None else DomainSchema()
        self._graph = self._build()

    def _build(self) -> Any:
        graph: StateGraph[CoordinatorState] = StateGraph(CoordinatorState)
        graph.add_node("gather_peer_context", self._gather_peer_context)
        graph.add_node("negotiate", self._negotiate)
        graph.add_node("finalize", self._finalize)
        graph.add_edge(START, "gather_peer_context")
        graph.add_edge("gather_peer_context", "negotiate")
        graph.add_edge("negotiate", "finalize")
        graph.add_edge("finalize", END)
        return graph.compile()

    async def _gather_peer_context(self, state: CoordinatorState) -> dict[str, Any]:
        own_domain = state["intent"].domain
        target_domains = {sq["domain"] for sq in state["draft_sub_queries"] if sq["domain"] != own_domain}

        peer_context: dict[str, Any] = {}
        for domain in target_domains:
            try:
                response = await self._peer_query_fn(
                    domain,
                    {"action": "describe_context", "intent": state["intent"].to_dict()},
                    state["envelope"],
                )
            except Exception:
                logger.warning("Peer context request to domain %s failed", domain, exc_info=True)
                response = None
            if response:
                peer_context[domain] = response

        return {"peer_context": peer_context}

    async def _negotiate(self, state: CoordinatorState) -> dict[str, Any]:
        if not state.get("peer_context"):
            # No peer had anything to add — keep the draft plan as-is.
            return {"plan": NegotiatedPlan(sub_queries=[NegotiatedSubQuery(**sq) for sq in state["draft_sub_queries"]])}

        human = (
            f"Draft sub-queries: {state['draft_sub_queries']}\n"
            f"Peer context by domain: {state['peer_context']}"
        )
        plan: NegotiatedPlan = await self._llm.ainvoke([("system", _NEGOTIATE_PROMPT), ("human", human)])
        return {"plan": plan}

    async def _finalize(self, state: CoordinatorState) -> dict[str, Any]:
        plan = state["plan"]
        intent = state["intent"]
        known_tables = set(self._schema.known_tables())

        sub_queries: list[dict[str, Any]] = []
        for sq in plan.sub_queries:
            table = sq.table if sq.table in known_tables else self._schema.resolve_table(sq.domain)
            fields = sq.fields or self._schema.resolve_fields(sq.domain, intent.action)
            sub_queries.append({
                "table": table,
                "fields": fields,
                "filters": sq.filters,
                "justifications": {f: f"Requested via cross-domain consensus on {sq.domain}" for f in fields},
                "domain": sq.domain,
                "depends_on": sq.depends_on,
            })

        if not sub_queries:
            sub_queries = state["draft_sub_queries"]

        return {"sub_queries": sub_queries}

    async def run(
        self,
        intent: IntentDescriptor,
        draft_sub_queries: list[dict[str, Any]],
        envelope: Any,
    ) -> list[dict[str, Any]]:
        result: CoordinatorState = await self._graph.ainvoke(
            {"intent": intent, "draft_sub_queries": draft_sub_queries, "envelope": envelope}
        )
        return result["sub_queries"]
