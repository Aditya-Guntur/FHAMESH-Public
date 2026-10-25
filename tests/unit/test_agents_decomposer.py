"""Tests for the LangGraph-backed query planner.

Same approach as test_agents_classifier.py: mock the LLM boundary,
exercise the real graph and the rule-based fallback.
"""

import pytest

pytest.importorskip("langgraph")

from fhamesh.agents.decomposer_graph import (
    DecompositionPlan,
    LangGraphDecomposer,
    PlanningGraph,
    SubQueryPlan,
)
from fhamesh.core.message import IntentDescriptor
from fhamesh.orchestrator.decomposer import QueryDecomposer


class _FakeStructuredLLM:
    def __init__(self, plan: DecompositionPlan | None = None, error: Exception | None = None):
        self._plan = plan
        self._error = error

    async def ainvoke(self, messages):
        if self._error:
            raise self._error
        return self._plan


class _FakeLLM:
    def __init__(self, structured: _FakeStructuredLLM):
        self._structured = structured

    def with_structured_output(self, schema):
        return self._structured


def _intent(**overrides):
    base = dict(category="query", domain="hr", action="lookup_salary", confidence=0.9, parameters={})
    base.update(overrides)
    return IntentDescriptor(**base)


class TestPlanningGraph:
    async def test_plan_then_validate(self):
        plan = DecompositionPlan(sub_queries=[SubQueryPlan(table="employees", fields=["name", "salary"], domain="hr")])
        graph = PlanningGraph(_FakeLLM(_FakeStructuredLLM(plan)))

        sub_queries = await graph.run(_intent())

        assert len(sub_queries) == 1
        assert sub_queries[0]["table"] == "employees"
        assert sub_queries[0]["fields"] == ["name", "salary"]
        assert sub_queries[0]["domain"] == "hr"

    async def test_unknown_table_is_corrected(self):
        """The model hallucinates a table that doesn't exist in the schema."""
        plan = DecompositionPlan(sub_queries=[SubQueryPlan(table="staff_members", fields=[], domain="hr")])
        graph = PlanningGraph(_FakeLLM(_FakeStructuredLLM(plan)))

        sub_queries = await graph.run(_intent())

        assert sub_queries[0]["table"] == "employees"  # corrected to the real table
        assert sub_queries[0]["fields"]  # empty fields were filled in from the schema

    async def test_empty_plan_falls_back_to_deterministic_single_query(self):
        plan = DecompositionPlan(sub_queries=[])
        graph = PlanningGraph(_FakeLLM(_FakeStructuredLLM(plan)))

        sub_queries = await graph.run(_intent())

        assert len(sub_queries) == 1
        assert sub_queries[0]["table"] == "employees"

    async def test_cross_domain_plan_produces_multiple_sub_queries(self):
        plan = DecompositionPlan(sub_queries=[
            SubQueryPlan(table="employees", fields=["name"], domain="hr"),
            SubQueryPlan(table="orders", fields=["amount"], domain="finance"),
        ])
        graph = PlanningGraph(_FakeLLM(_FakeStructuredLLM(plan)))

        sub_queries = await graph.run(_intent(domain="general", parameters={"cross_domain": True}))

        assert len(sub_queries) == 2
        assert {sq["domain"] for sq in sub_queries} == {"hr", "finance"}


class TestLangGraphDecomposer:
    async def test_falls_back_when_ollama_unavailable(self):
        decomposer = LangGraphDecomposer({"ollama": {"base_url": "http://127.0.0.1:1", "timeout_seconds": 0.5}})

        sub_queries = await decomposer.decompose(_intent())

        assert len(sub_queries) == 1
        assert sub_queries[0]["table"] == "employees"

    async def test_falls_back_on_model_error(self):
        decomposer = LangGraphDecomposer(fallback=QueryDecomposer())
        decomposer._graph = PlanningGraph(_FakeLLM(_FakeStructuredLLM(error=RuntimeError("boom"))))

        sub_queries = await decomposer.decompose(_intent())

        assert len(sub_queries) == 1
        assert sub_queries[0]["table"] == "employees"

    async def test_happy_path_uses_the_graph(self):
        plan = DecompositionPlan(sub_queries=[SubQueryPlan(table="products", fields=["name", "price"], domain="product")])
        decomposer = LangGraphDecomposer(fallback=QueryDecomposer())
        decomposer._graph = PlanningGraph(_FakeLLM(_FakeStructuredLLM(plan)))

        sub_queries = await decomposer.decompose(_intent(domain="product", action="lookup_product"))

        assert sub_queries[0]["table"] == "products"
