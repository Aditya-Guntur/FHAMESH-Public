"""Tests for the LangGraph cross-domain consensus agent.

peer_query_fn is a plain async callable in these tests — CoordinatorGraph
never touches PeerMesh or the transport directly, so no live mesh is
needed to exercise the real graph wiring.
"""

import pytest

pytest.importorskip("langgraph")

from fhamesh.agents.coordinator_graph import CoordinatorGraph, NegotiatedPlan, NegotiatedSubQuery
from fhamesh.core.message import IntentDescriptor


class _FakeStructuredLLM:
    def __init__(self, plan: NegotiatedPlan | None = None, error: Exception | None = None):
        self._plan = plan
        self._error = error
        self.last_messages = None

    async def ainvoke(self, messages):
        self.last_messages = messages
        if self._error:
            raise self._error
        return self._plan


class _FakeLLM:
    def __init__(self, structured: _FakeStructuredLLM):
        self._structured = structured

    def with_structured_output(self, schema):
        return self._structured


def _intent(**overrides):
    base = {"category": "query", "domain": "general", "action": "compare", "confidence": 0.8,
            "parameters": {"cross_domain": True}}
    base.update(overrides)
    return IntentDescriptor(**base)


def _draft_sub_queries():
    return [
        {"table": "employees", "fields": ["name"], "filters": {}, "justifications": {}, "domain": "hr", "depends_on": []},
        {"table": "orders", "fields": ["amount"], "filters": {}, "justifications": {}, "domain": "finance", "depends_on": []},
    ]


class TestCoordinatorGraph:
    async def test_peer_context_is_gathered_per_domain(self):
        queried_domains = []

        async def peer_query(domain, query, envelope):
            queried_domains.append(domain)
            return {"domain": domain, "known_fields": ["x"]}

        plan = NegotiatedPlan(sub_queries=[NegotiatedSubQuery(**sq) for sq in _draft_sub_queries()])
        llm = _FakeStructuredLLM(plan)
        graph = CoordinatorGraph(_FakeLLM(llm), peer_query)

        await graph.run(_intent(), _draft_sub_queries(), envelope=None)

        assert set(queried_domains) == {"hr", "finance"}

    async def test_own_domain_is_never_queried_as_a_peer(self):
        queried_domains = []

        async def peer_query(domain, query, envelope):
            queried_domains.append(domain)
            return {"domain": domain}

        plan = NegotiatedPlan(sub_queries=[NegotiatedSubQuery(**sq) for sq in _draft_sub_queries()])
        graph = CoordinatorGraph(_FakeLLM(_FakeStructuredLLM(plan)), peer_query)

        await graph.run(_intent(domain="hr"), _draft_sub_queries(), envelope=None)

        assert "hr" not in queried_domains
        assert "finance" in queried_domains

    async def test_peer_suggested_filter_reaches_the_final_plan(self):
        async def peer_query(domain, query, envelope):
            if domain == "hr":
                return {"domain": "hr", "suggested_filter": {"department": "engineering"}}
            return None

        plan = NegotiatedPlan(sub_queries=[
            NegotiatedSubQuery(table="employees", fields=["name", "department"], domain="hr",
                                filters={"department": "engineering"}),
            NegotiatedSubQuery(table="orders", fields=["amount"], domain="finance"),
        ])
        graph = CoordinatorGraph(_FakeLLM(_FakeStructuredLLM(plan)), peer_query)

        sub_queries = await graph.run(_intent(), _draft_sub_queries(), envelope=None)

        hr_query = next(sq for sq in sub_queries if sq["domain"] == "hr")
        assert hr_query["filters"] == {"department": "engineering"}

    async def test_no_peer_response_skips_negotiation_llm_call(self):
        async def peer_query(domain, query, envelope):
            return None  # every peer is unreachable

        structured = _FakeStructuredLLM(error=AssertionError("negotiate should not have been called"))
        graph = CoordinatorGraph(_FakeLLM(structured), peer_query)

        sub_queries = await graph.run(_intent(), _draft_sub_queries(), envelope=None)

        assert len(sub_queries) == 2  # draft plan preserved unchanged
        assert structured.last_messages is None

    async def test_failed_peer_request_does_not_abort_coordination(self):
        async def peer_query(domain, query, envelope):
            if domain == "hr":
                raise ConnectionError("peer unreachable")
            return {"domain": "finance"}

        plan = NegotiatedPlan(sub_queries=[NegotiatedSubQuery(**sq) for sq in _draft_sub_queries()])
        graph = CoordinatorGraph(_FakeLLM(_FakeStructuredLLM(plan)), peer_query)

        sub_queries = await graph.run(_intent(), _draft_sub_queries(), envelope=None)

        assert len(sub_queries) == 2

    async def test_unknown_table_from_negotiation_is_corrected(self):
        async def peer_query(domain, query, envelope):
            return {"domain": domain}

        plan = NegotiatedPlan(sub_queries=[
            NegotiatedSubQuery(table="staff_members", fields=[], domain="hr"),
        ])
        graph = CoordinatorGraph(_FakeLLM(_FakeStructuredLLM(plan)), peer_query)

        sub_queries = await graph.run(_intent(), _draft_sub_queries(), envelope=None)

        assert sub_queries[0]["table"] == "employees"  # corrected via DomainSchema
