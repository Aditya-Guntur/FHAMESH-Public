"""Integration test: classification -> planning -> synthesis chained together.

The unit tests exercise each LangGraph agent in isolation. This checks
they actually compose: the classifier's IntentDescriptor is what the
planner consumes, and the planner's sub-queries line up with what
DataCore would need, ending in a synthesized QueryResult. No real
Ollama server or Redis — the LLM boundary is mocked at each graph.
"""

import pytest

pytest.importorskip("langgraph")

from fhamesh.agents.aggregator_graph import ResultSynthesis, SynthesisGraph
from fhamesh.agents.classifier_graph import ClassificationGraph, IntentExtraction
from fhamesh.agents.decomposer_graph import DecompositionPlan, PlanningGraph, SubQueryPlan
from fhamesh.core.message import QueryResult


class _FakeStructuredLLM:
    def __init__(self, response):
        self._response = response

    async def ainvoke(self, messages):
        return self._response


class _FakeLLM:
    def __init__(self, response):
        self._response = response

    def with_structured_output(self, schema):
        return _FakeStructuredLLM(self._response)


class TestLangGraphPipeline:
    async def test_classify_then_plan_then_synthesize(self):
        # 1. Classification agent reads the sanitized user text
        extraction = IntentExtraction(
            category="query", domain="hr", action="lookup_salary",
            confidence=0.92, parameters={"department": "engineering"},
        )
        classifier = ClassificationGraph(_FakeLLM(extraction), min_confidence=0.3)
        intent = await classifier.run("What is the average salary in engineering?")

        assert intent.domain == "hr"
        assert intent.parameters == {"department": "engineering"}

        # 2. Planning agent reads the classifier's own IntentDescriptor
        plan = DecompositionPlan(sub_queries=[
            SubQueryPlan(table="employees", fields=["department", "salary"], domain="hr",
                         filters={"department": "engineering"}),
        ])
        planner = PlanningGraph(_FakeLLM(plan))
        sub_queries = await planner.run(intent)

        assert len(sub_queries) == 1
        assert sub_queries[0]["table"] == "employees"
        assert sub_queries[0]["filters"] == {"department": "engineering"}

        # 3. DataCore would run sub_queries[0] and return a privacy-protected
        #    result; the synthesis agent only ever sees that, never raw rows.
        dc_result = QueryResult(
            success=True,
            data={"avg_salary": 142300.0},
            privacy_budget_consumed=0.5,
            noise_applied=True,
        )
        synthesis = ResultSynthesis(summary="Average engineering salary is approximately $142,300.")
        synthesizer = SynthesisGraph(_FakeLLM(synthesis))
        final = await synthesizer.run([dc_result])

        assert final.success is True
        assert final.summary == "Average engineering salary is approximately $142,300."
        assert final.privacy_budget_consumed == 0.5

    async def test_low_confidence_classification_still_produces_a_safe_plan(self):
        """An UNKNOWN-category intent should still decompose to something valid,
        not raise — the planner's validate_plan node is the safety net."""
        extraction = IntentExtraction(category="query", domain="hr", action="x", confidence=0.05)
        classifier = ClassificationGraph(_FakeLLM(extraction), min_confidence=0.3)
        intent = await classifier.run("???")

        plan = DecompositionPlan(sub_queries=[])  # model proposes nothing usable
        planner = PlanningGraph(_FakeLLM(plan))
        sub_queries = await planner.run(intent)

        assert len(sub_queries) == 1
        assert sub_queries[0]["table"]  # deterministic fallback always resolves a table
