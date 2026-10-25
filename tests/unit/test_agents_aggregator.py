"""Tests for the LangGraph-backed result synthesizer.

Same approach as the other agent tests: mock the LLM boundary,
exercise the real graph and the merge-only fallback.
"""

import pytest

pytest.importorskip("langgraph")

from fhamesh.agents.aggregator_graph import LangGraphAggregator, ResultSynthesis, SynthesisGraph
from fhamesh.core.message import QueryResult
from fhamesh.orchestrator.aggregator import ResultAggregator


class _FakeStructuredLLM:
    def __init__(self, synthesis: ResultSynthesis | None = None, error: Exception | None = None):
        self._synthesis = synthesis
        self._error = error

    async def ainvoke(self, messages):
        if self._error:
            raise self._error
        return self._synthesis


class _FakeLLM:
    def __init__(self, structured: _FakeStructuredLLM):
        self._structured = structured

    def with_structured_output(self, schema):
        return self._structured


class TestSynthesisGraph:
    async def test_merge_then_synthesize(self):
        synthesis = ResultSynthesis(summary="Average salary is $142,300.")
        graph = SynthesisGraph(_FakeLLM(_FakeStructuredLLM(synthesis)))

        merged = await graph.run([QueryResult(success=True, data={"avg_salary": 142300.0}, noise_applied=True)])

        assert merged.success is True
        assert merged.data == {"avg_salary": 142300.0}
        assert merged.noise_applied is True
        assert merged.summary == "Average salary is $142,300."

    async def test_merge_preserves_existing_aggregation_semantics(self):
        """The merge step is unchanged: budget sums, redactions union, success is AND."""
        synthesis = ResultSynthesis(summary="")
        graph = SynthesisGraph(_FakeLLM(_FakeStructuredLLM(synthesis)))

        results = [
            QueryResult(success=True, data={"a": 1}, privacy_budget_consumed=0.5, fields_redacted=["ssn"]),
            QueryResult(success=True, data={"b": 2}, privacy_budget_consumed=0.3, fields_redacted=["email"]),
        ]
        merged = await graph.run(results)

        assert merged.privacy_budget_consumed == pytest.approx(0.8)
        assert set(merged.fields_redacted) == {"ssn", "email"}

    async def test_no_summary_for_failed_or_empty_results(self):
        graph = SynthesisGraph(_FakeLLM(_FakeStructuredLLM(ResultSynthesis(summary="should not be called"))))

        merged = await graph.run([QueryResult(success=False, error_message="denied")])

        assert merged.summary == ""


class TestLangGraphAggregator:
    async def test_falls_back_when_ollama_unavailable(self):
        aggregator = LangGraphAggregator({"ollama": {"base_url": "http://127.0.0.1:1", "timeout_seconds": 0.5}})

        merged = await aggregator.aggregate([QueryResult(success=True, data={"x": 1})])

        assert merged.success is True
        assert merged.data == {"x": 1}
        assert merged.summary == ""  # fallback never sets a summary

    async def test_falls_back_on_model_error(self):
        aggregator = LangGraphAggregator(fallback=ResultAggregator())
        aggregator._graph = SynthesisGraph(_FakeLLM(_FakeStructuredLLM(error=RuntimeError("boom"))))

        merged = await aggregator.aggregate([QueryResult(success=True, data={"x": 1})])

        assert merged.success is True
        assert merged.summary == ""

    async def test_happy_path_uses_the_graph(self):
        synthesis = ResultSynthesis(summary="There are 42 products in stock.")
        aggregator = LangGraphAggregator(fallback=ResultAggregator())
        aggregator._graph = SynthesisGraph(_FakeLLM(_FakeStructuredLLM(synthesis)))

        merged = await aggregator.aggregate([QueryResult(success=True, data={"count": 42})])

        assert merged.summary == "There are 42 products in stock."
