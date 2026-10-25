"""Tests for the LangGraph-backed result synthesizer.

Same approach as the other agent tests: mock the LLM boundary,
exercise the real graph and the merge-only fallback.
"""

import pytest

pytest.importorskip("langgraph")

from langchain_core.messages import AIMessage

from fhamesh.agents.aggregator_graph import (
    LangGraphAggregator,
    ResultSynthesis,
    SynthesisGraph,
    VerificationResult,
)
from fhamesh.core.message import QueryResult
from fhamesh.orchestrator.aggregator import ResultAggregator


class _FakeStructuredLLM:
    def __init__(self, response=None, error: Exception | None = None):
        self._response = response
        self._error = error

    async def ainvoke(self, messages):
        if self._error:
            raise self._error
        return self._response


class _FakeToolLLM:
    """Never calls a tool — the reasoning loop goes straight to synthesize."""

    async def ainvoke(self, messages):
        return AIMessage(content="no tools needed")


class _FakeLLM:
    """bind_tools() always skips straight to synthesis; with_structured_output()
    returns the synthesis fake or the verify fake depending on which schema
    is requested, mirroring how SynthesisGraph actually calls both."""

    def __init__(self, synthesis=None, synth_error=None, verify=None):
        self._synthesis = _FakeStructuredLLM(synthesis, error=synth_error)
        self._verify = _FakeStructuredLLM(verify or VerificationResult(consistent=True))

    def bind_tools(self, tools):
        return _FakeToolLLM()

    def with_structured_output(self, schema):
        return self._synthesis if schema is ResultSynthesis else self._verify


class TestSynthesisGraph:
    async def test_merge_then_synthesize(self):
        synthesis = ResultSynthesis(summary="Average salary is $142,300.")
        graph = SynthesisGraph(_FakeLLM(synthesis))

        merged = await graph.run([QueryResult(success=True, data={"avg_salary": 142300.0}, noise_applied=True)])

        assert merged.success is True
        assert merged.data == {"avg_salary": 142300.0}
        assert merged.noise_applied is True
        assert merged.summary == "Average salary is $142,300."

    async def test_merge_preserves_existing_aggregation_semantics(self):
        """The merge step is unchanged: budget sums, redactions union, success is AND."""
        graph = SynthesisGraph(_FakeLLM(ResultSynthesis(summary="")))

        results = [
            QueryResult(success=True, data={"a": 1}, privacy_budget_consumed=0.5, fields_redacted=["ssn"]),
            QueryResult(success=True, data={"b": 2}, privacy_budget_consumed=0.3, fields_redacted=["email"]),
        ]
        merged = await graph.run(results)

        assert merged.privacy_budget_consumed == pytest.approx(0.8)
        assert set(merged.fields_redacted) == {"ssn", "email"}

    async def test_no_summary_for_failed_or_empty_results(self):
        graph = SynthesisGraph(_FakeLLM(ResultSynthesis(summary="should not be called")))

        merged = await graph.run([QueryResult(success=False, error_message="denied")])

        assert merged.summary == ""


class _ScriptedToolLLM:
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
    def __init__(self, tool_script: list[dict | None], synthesis: ResultSynthesis):
        self._tool_llm = _ScriptedToolLLM(tool_script)
        self._synthesis = synthesis

    def bind_tools(self, tools):
        return self._tool_llm

    def with_structured_output(self, schema):
        if schema is ResultSynthesis:
            return _FakeStructuredLLM(self._synthesis)
        return _FakeStructuredLLM(VerificationResult(consistent=True))


class TestSynthesisToolLoop:
    async def test_real_tool_call_computes_a_real_percentage(self):
        """compute_percentage_change actually runs — not mocked away."""
        tool_script = [
            {"name": "compute_percentage_change", "args": {"old_value": 100, "new_value": 150}, "id": "call_1"},
            None,
        ]
        synthesis = ResultSynthesis(summary="Revenue grew 50%.")
        graph = SynthesisGraph(_ScriptedLLM(tool_script, synthesis))

        merged = await graph.run([QueryResult(success=True, data={"old": 100, "new": 150})])

        assert merged.summary == "Revenue grew 50%."

    async def test_runaway_tool_loop_is_capped(self):
        always_call = {"name": "format_currency", "args": {"amount": 100.0}, "id": "call_x"}
        llm = _ScriptedLLM([always_call] * 20, ResultSynthesis(summary="ok"))
        graph = SynthesisGraph(llm)

        merged = await graph.run([QueryResult(success=True, data={"x": 1})])

        assert merged.summary == "ok"
        assert llm._tool_llm.calls <= 4


class TestVerification:
    async def test_consistent_summary_passes_through_unchanged(self):
        synthesis = ResultSynthesis(summary="Average salary is $142,300.")
        verify = VerificationResult(consistent=True)
        graph = SynthesisGraph(_FakeLLM(synthesis, verify=verify))

        merged = await graph.run([QueryResult(success=True, data={"avg_salary": 142300.0})])

        assert merged.summary == "Average salary is $142,300."

    async def test_inconsistent_summary_gets_corrected(self):
        synthesis = ResultSynthesis(summary="Average salary is $999,000.")  # hallucinated
        verify = VerificationResult(
            consistent=False,
            corrected_summary="Average salary is $142,300.",
            issues=["Summary stated $999,000 but data shows $142,300"],
        )
        graph = SynthesisGraph(_FakeLLM(synthesis, verify=verify))

        merged = await graph.run([QueryResult(success=True, data={"avg_salary": 142300.0})])

        assert merged.summary == "Average salary is $142,300."

    async def test_inconsistent_summary_with_no_correction_is_dropped(self):
        synthesis = ResultSynthesis(summary="Something made up.")
        verify = VerificationResult(consistent=False, corrected_summary="", issues=["Not grounded in data"])
        graph = SynthesisGraph(_FakeLLM(synthesis, verify=verify))

        merged = await graph.run([QueryResult(success=True, data={"x": 1})])

        assert merged.summary == ""  # safer to show nothing than a known-bad summary

    async def test_verification_is_skipped_when_there_is_no_summary(self):
        """No summary (failed/empty result) means verify should never even call the model."""
        verify_llm = _FakeStructuredLLM(error=AssertionError("verify should not have been called"))
        llm = _FakeLLM(ResultSynthesis(summary=""))
        llm._verify = verify_llm
        graph = SynthesisGraph(llm)

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
        aggregator._graph = SynthesisGraph(_FakeLLM(synth_error=RuntimeError("boom")))

        merged = await aggregator.aggregate([QueryResult(success=True, data={"x": 1})])

        assert merged.success is True
        assert merged.summary == ""

    async def test_happy_path_uses_the_graph(self):
        synthesis = ResultSynthesis(summary="There are 42 products in stock.")
        aggregator = LangGraphAggregator(fallback=ResultAggregator())
        aggregator._graph = SynthesisGraph(_FakeLLM(synthesis))

        merged = await aggregator.aggregate([QueryResult(success=True, data={"count": 42})])

        assert merged.summary == "There are 42 products in stock."


class _FakeChunk:
    def __init__(self, content):
        self.content = content


class _FakeStreamingLLM:
    """Supports astream() for the preview path; with_structured_output()
    would raise if the streaming path accidentally tried to use it."""

    def __init__(self, words):
        self._words = words

    async def astream(self, messages):
        for word in self._words:
            yield _FakeChunk(word)

    def bind_tools(self, tools):
        return _FakeToolLLM()

    def with_structured_output(self, schema):
        return _FakeStructuredLLM(error=AssertionError("structured output should not run during astream"))


class TestSynthesisStreaming:
    async def test_astream_yields_text_chunks(self):
        graph = SynthesisGraph(_FakeStreamingLLM(["Average", " salary", " is", " $142,300."]))

        chunks = [c async for c in graph.astream([QueryResult(success=True, data={"avg_salary": 142300.0})])]

        assert "".join(chunks) == "Average salary is $142,300."

    async def test_astream_yields_nothing_for_failed_result(self):
        graph = SynthesisGraph(_FakeStreamingLLM(["should", " not", " appear"]))

        chunks = [c async for c in graph.astream([QueryResult(success=False, error_message="denied")])]

        assert chunks == []

    async def test_aggregator_can_stream_reflects_graph_availability(self):
        streaming = LangGraphAggregator(fallback=ResultAggregator())
        streaming._graph = SynthesisGraph(_FakeStreamingLLM(["ok"]))
        assert streaming.can_stream is True

        no_model = LangGraphAggregator({"ollama": {"base_url": "http://127.0.0.1:1"}})
        no_model._graph = None
        assert no_model.can_stream is False

    async def test_aggregator_astream_summary_delegates_to_graph(self):
        aggregator = LangGraphAggregator(fallback=ResultAggregator())
        aggregator._graph = SynthesisGraph(_FakeStreamingLLM(["Average", " is", " 42."]))

        chunks = [c async for c in aggregator.astream_summary([QueryResult(success=True, data={"x": 42})])]

        assert "".join(chunks) == "Average is 42."

    async def test_astream_summary_yields_nothing_without_a_graph(self):
        aggregator = LangGraphAggregator(fallback=ResultAggregator())
        aggregator._graph = None

        chunks = [c async for c in aggregator.astream_summary([QueryResult(success=True, data={"x": 1})])]

        assert chunks == []
