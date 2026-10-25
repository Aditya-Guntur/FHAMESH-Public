"""Tests for the LangGraph-backed intent classifier.

No real Ollama server is used — the LLM boundary is mocked with a fake
structured-output runnable, same philosophy as the fakeredis tests:
exercise the real graph wiring without needing a live model.
"""

import pytest

pytest.importorskip("langgraph")

from langchain_core.messages import AIMessage

from fhamesh.agents.classifier_graph import (
    ClassificationGraph,
    IntentExtraction,
    LangGraphClassifier,
)
from fhamesh.core.types import IntentCategory
from fhamesh.leaf.classifier import IntentClassifier
from fhamesh.leaf.memory import SessionMemory


class _FakeStructuredLLM:
    def __init__(self, extraction: IntentExtraction | None = None, error: Exception | None = None):
        self._extraction = extraction
        self._error = error

    async def ainvoke(self, messages):
        if self._error:
            raise self._error
        return self._extraction


class _FakeToolLLM:
    """Never calls a tool — the reasoning loop goes straight to extract."""

    async def ainvoke(self, messages):
        return AIMessage(content="no tools needed")


class _FakeLLM:
    def __init__(self, structured: _FakeStructuredLLM):
        self._structured = structured

    def bind_tools(self, tools):
        return _FakeToolLLM()

    def with_structured_output(self, schema):
        return self._structured


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
    def __init__(self, tool_script: list[dict | None], extraction: IntentExtraction):
        self._tool_llm = _ScriptedToolLLM(tool_script)
        self._extraction = extraction

    def bind_tools(self, tools):
        return self._tool_llm

    def with_structured_output(self, schema):
        return _FakeStructuredLLM(self._extraction)


class TestClassificationGraphToolLoop:
    async def test_real_tool_call_reaches_the_schema_registry(self):
        tool_script = [{"name": "list_domains", "args": {}, "id": "call_1"}, None]
        extraction = IntentExtraction(category="query", domain="hr", action="lookup_salary", confidence=0.9)
        graph = ClassificationGraph(_ScriptedLLM(tool_script, extraction), min_confidence=0.3)

        intent = await graph.run("show me engineering salaries")

        assert intent.domain == "hr"

    async def test_runaway_tool_loop_is_capped(self):
        always_call = {"name": "list_domains", "args": {}, "id": "call_x"}
        extraction = IntentExtraction(category="query", domain="hr", action="lookup_salary", confidence=0.9)
        llm = _ScriptedLLM([always_call] * 20, extraction)
        graph = ClassificationGraph(llm, min_confidence=0.3)

        intent = await graph.run("salary?")

        assert intent.domain == "hr"
        assert llm._tool_llm.calls <= 4


class _CapturingToolLLM:
    """Records the messages it was called with, so a test can check
    whether recalled history actually made it into the prompt."""

    def __init__(self):
        self.seen_messages = []

    async def ainvoke(self, messages):
        self.seen_messages = list(messages)
        return AIMessage(content="no tools needed")


class _CapturingLLM:
    def __init__(self, extraction: IntentExtraction):
        self.tool_llm = _CapturingToolLLM()
        self._extraction = extraction

    def bind_tools(self, tools):
        return self.tool_llm

    def with_structured_output(self, schema):
        return _FakeStructuredLLM(self._extraction)


class TestClassificationGraphMemory:
    async def test_recalled_history_reaches_the_prompt(self):
        memory = SessionMemory()
        await memory.record_turn("alice", "hr", "lookup_salary", {"department": "engineering"})

        extraction = IntentExtraction(category="query", domain="finance", action="aggregate_revenue", confidence=0.9)
        llm = _CapturingLLM(extraction)
        graph = ClassificationGraph(llm, min_confidence=0.3, memory=memory)

        await graph.run("and in sales?", user_id="alice")

        human_messages = [m for m in llm.tool_llm.seen_messages if isinstance(m, tuple) and m[0] == "human"]
        assert any("domain=hr" in m[1] for m in human_messages)
        assert any("and in sales?" in m[1] for m in human_messages)

    async def test_new_turn_is_recorded_after_classification(self):
        memory = SessionMemory()
        extraction = IntentExtraction(category="query", domain="product", action="list_catalog", confidence=0.8)
        graph = ClassificationGraph(_FakeLLM(_FakeStructuredLLM(extraction)), min_confidence=0.3, memory=memory)

        await graph.run("show me the catalog", user_id="alice")

        turns = await memory.recall("alice")
        assert len(turns) == 1
        assert turns[0]["domain"] == "product"
        assert turns[0]["action"] == "list_catalog"

    async def test_no_memory_configured_is_a_noop(self):
        """ClassificationGraph with memory=None (the default) should work exactly as before."""
        extraction = IntentExtraction(category="query", domain="hr", action="lookup_salary", confidence=0.9)
        graph = ClassificationGraph(_FakeLLM(_FakeStructuredLLM(extraction)), min_confidence=0.3)

        intent = await graph.run("salary?", user_id="alice")

        assert intent.domain == "hr"

    async def test_empty_user_id_skips_memory_without_error(self):
        memory = SessionMemory()
        extraction = IntentExtraction(category="query", domain="hr", action="lookup_salary", confidence=0.9)
        graph = ClassificationGraph(_FakeLLM(_FakeStructuredLLM(extraction)), min_confidence=0.3, memory=memory)

        intent = await graph.run("salary?")  # no user_id

        assert intent.domain == "hr"
        assert await memory.recall("") == []


class TestClassificationGraph:
    async def test_extract_then_calibrate(self):
        extraction = IntentExtraction(
            category="query", domain="hr", action="lookup_salary",
            confidence=0.9, parameters={"department": "engineering"},
        )
        graph = ClassificationGraph(_FakeLLM(_FakeStructuredLLM(extraction)), min_confidence=0.3)

        intent = await graph.run("show me engineering salaries")

        assert intent.category == IntentCategory.QUERY.value
        assert intent.domain == "hr"
        assert intent.action == "lookup_salary"
        assert intent.confidence == 0.9
        assert intent.parameters == {"department": "engineering"}
        assert intent.raw_input_hash

    async def test_low_confidence_demoted_to_unknown(self):
        extraction = IntentExtraction(category="query", domain="hr", action="lookup_salary", confidence=0.1)
        graph = ClassificationGraph(_FakeLLM(_FakeStructuredLLM(extraction)), min_confidence=0.3)

        intent = await graph.run("salary??")

        assert intent.category == IntentCategory.UNKNOWN.value

    async def test_invalid_category_from_model_is_corrected(self):
        extraction = IntentExtraction(category="not_a_real_category", domain="hr", action="x", confidence=0.9)
        graph = ClassificationGraph(_FakeLLM(_FakeStructuredLLM(extraction)), min_confidence=0.3)

        intent = await graph.run("something")

        assert intent.category == IntentCategory.QUERY.value


class TestLangGraphClassifier:
    async def test_falls_back_when_ollama_unavailable(self):
        """No real Ollama server is running at this port -> falls back to regex."""
        classifier = LangGraphClassifier({"ollama": {"base_url": "http://127.0.0.1:1", "timeout_seconds": 0.5}})

        intent = await classifier.classify("Show me employee salaries in engineering")

        assert intent.domain == "hr"

    async def test_falls_back_on_model_error(self):
        classifier = LangGraphClassifier(fallback=IntentClassifier())
        classifier._graph = ClassificationGraph(
            _FakeLLM(_FakeStructuredLLM(error=RuntimeError("model exploded"))),
            min_confidence=0.3,
        )

        intent = await classifier.classify("Show me employee salaries in engineering")

        assert intent.domain == "hr"  # answered by the regex fallback, not the broken graph

    async def test_empty_input_short_circuits(self):
        classifier = LangGraphClassifier(fallback=IntentClassifier())

        intent = await classifier.classify("   ")

        assert intent.category == IntentCategory.UNKNOWN.value
        assert intent.confidence == 0.0

    async def test_happy_path_uses_the_graph(self):
        extraction = IntentExtraction(
            category="query", domain="finance", action="aggregate_revenue", confidence=0.85,
        )
        classifier = LangGraphClassifier(fallback=IntentClassifier())
        classifier._graph = ClassificationGraph(_FakeLLM(_FakeStructuredLLM(extraction)), min_confidence=0.3)

        intent = await classifier.classify("what's total revenue this quarter")

        assert intent.domain == "finance"
        assert intent.action == "aggregate_revenue"
