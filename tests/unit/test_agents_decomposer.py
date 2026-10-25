"""Tests for the LangGraph-backed query planner.

Same approach as test_agents_classifier.py: mock the LLM boundary,
exercise the real graph and the rule-based fallback.
"""

import pytest

pytest.importorskip("langgraph")

from langchain_core.messages import AIMessage

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


class _FakeToolLLM:
    """Never calls a tool — the reasoning loop goes straight to finalize."""

    async def ainvoke(self, messages):
        return AIMessage(content="no tools needed")


class _FakeLLM:
    def __init__(self, structured: _FakeStructuredLLM):
        self._structured = structured

    def bind_tools(self, tools):
        return _FakeToolLLM()

    def with_structured_output(self, schema):
        return self._structured


def _intent(**overrides):
    base = {"category": "query", "domain": "hr", "action": "lookup_salary", "confidence": 0.9, "parameters": {}}
    base.update(overrides)
    return IntentDescriptor(**base)


class _ScriptedToolLLM:
    """Calls a tool N times (by script), then stops."""

    def __init__(self, script: list[dict | None]):
        self._script = script
        self.calls = 0

    async def ainvoke(self, messages):
        tool_call = self._script[self.calls] if self.calls < len(self._script) else None
        self.calls += 1
        if tool_call:
            return AIMessage(content="", tool_calls=[tool_call])
        return AIMessage(content="done reasoning")


class _ScriptedLLM:
    def __init__(self, tool_script: list[dict | None], final_plan: DecompositionPlan):
        self._tool_llm = _ScriptedToolLLM(tool_script)
        self._final_plan = final_plan

    def bind_tools(self, tools):
        return self._tool_llm

    def with_structured_output(self, schema):
        return _FakeStructuredLLM(self._final_plan)


class TestPlanningGraphToolLoop:
    async def test_real_tool_call_reaches_the_schema_registry(self):
        """describe_domain actually runs against a real DynamicSchemaRegistry,
        not a mock — the model just decides to call it."""
        tool_script = [{"name": "describe_domain", "args": {"domain": "hr"}, "id": "call_1"}, None]
        final_plan = DecompositionPlan(sub_queries=[SubQueryPlan(table="employees", fields=["salary"], domain="hr")])
        graph = PlanningGraph(_ScriptedLLM(tool_script, final_plan))

        sub_queries = await graph.run(_intent())

        assert sub_queries[0]["table"] == "employees"

    async def test_runaway_tool_loop_is_capped(self):
        """A model that always wants to call a tool must still terminate."""
        always_call = {"name": "list_domains", "args": {}, "id": "call_x"}
        llm = _ScriptedLLM([always_call] * 20, DecompositionPlan(sub_queries=[]))
        graph = PlanningGraph(llm)

        sub_queries = await graph.run(_intent())

        assert len(sub_queries) == 1  # still produced a valid (deterministic) plan
        assert llm._tool_llm.calls <= 5  # didn't loop forever


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
