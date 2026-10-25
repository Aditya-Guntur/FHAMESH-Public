"""Tests for opt-in STREAM_CHUNK synthesis preview.

Streaming is strictly opt-in and requires a _reply_channel on the
inbound envelope (only present when the caller used
transport.request_stream(), never transport.request()), so these
tests check both that chunks flow when everything is configured for
it, and that nothing changes when it isn't.
"""

import pytest

pytest.importorskip("langgraph")

from fhamesh.agents.aggregator_graph import LangGraphAggregator, ResultSynthesis, SynthesisGraph, VerificationResult
from fhamesh.core.message import MessageEnvelope, QueryResult
from fhamesh.core.types import MessageType
from fhamesh.leaf.node import LeafNode
from fhamesh.orchestrator.aggregator import ResultAggregator
from fhamesh.orchestrator.controller import OrchestratorNode


class _FakeChunk:
    def __init__(self, content):
        self.content = content


class _FakeStreamingLLM:
    def __init__(self, words, synthesis=None):
        self._words = words
        self._synthesis = synthesis or ResultSynthesis(summary="".join(words))

    async def astream(self, messages):
        for word in self._words:
            yield _FakeChunk(word)

    def bind_tools(self, tools):
        class _NoToolCalls:
            async def ainvoke(self, messages):
                from langchain_core.messages import AIMessage
                return AIMessage(content="no tools")
        return _NoToolCalls()

    def with_structured_output(self, schema):
        class _Structured:
            def __init__(self, response):
                self._response = response
            async def ainvoke(self, messages):
                return self._response
        if schema is ResultSynthesis:
            return _Structured(self._synthesis)
        return _Structured(VerificationResult(consistent=True))


class _FakeTransport:
    def __init__(self):
        self.published: list[tuple[str, MessageEnvelope]] = []

    async def publish_to_channel(self, channel, envelope):
        self.published.append((channel, envelope))

    async def publish(self, envelope):
        self.published.append(("", envelope))


def _orchestrator_with_streaming(words):
    orch = OrchestratorNode(config={"streaming": {"enabled": True}})
    orch._aggregator = LangGraphAggregator(fallback=ResultAggregator())
    orch._aggregator._graph = SynthesisGraph(_FakeStreamingLLM(words))
    orch._transport = _FakeTransport()
    return orch


class TestStreamingPreview:
    async def test_chunks_sent_when_enabled_and_reply_channel_present(self):
        orch = _orchestrator_with_streaming(["Average", " is", " 42."])
        envelope = MessageEnvelope(
            correlation_id="corr-1",
            source_agent_id="leaf:general:abc",
            payload={"_reply_channel": "fhamesh:reply:xyz"},
        )

        await orch._stream_preview(envelope, [QueryResult(success=True, data={"avg": 42})])

        chunks = [e for _, e in orch._transport.published if e.message_type == MessageType.STREAM_CHUNK.value]
        assert [c.payload["chunk"] for c in chunks] == ["Average", " is", " 42."]
        assert all(c.correlation_id == "corr-1" for c in chunks)
        assert all(c.payload["_reply_channel"] == "fhamesh:reply:xyz" for c in chunks)

    async def test_no_chunks_when_streaming_disabled(self):
        orch = OrchestratorNode(config={"streaming": {"enabled": False}})
        orch._aggregator = LangGraphAggregator(fallback=ResultAggregator())
        orch._aggregator._graph = SynthesisGraph(_FakeStreamingLLM(["should", " not", " send"]))
        orch._transport = _FakeTransport()

        envelope = MessageEnvelope(payload={"_reply_channel": "fhamesh:reply:xyz"})
        await orch._stream_preview(envelope, [QueryResult(success=True, data={"x": 1})])

        assert orch._transport.published == []

    async def test_no_chunks_without_a_reply_channel(self):
        """A plain request() caller never sets _reply_channel in the payload
        it sends — streaming must not activate for it even if enabled."""
        orch = _orchestrator_with_streaming(["should", " not", " send"])
        envelope = MessageEnvelope(payload={})  # no _reply_channel

        await orch._stream_preview(envelope, [QueryResult(success=True, data={"x": 1})])

        assert orch._transport.published == []

    async def test_no_chunks_when_backend_cannot_stream(self):
        orch = OrchestratorNode(config={"streaming": {"enabled": True}})
        orch._aggregator = ResultAggregator()  # merge-only, no can_stream at all
        orch._transport = _FakeTransport()

        envelope = MessageEnvelope(payload={"_reply_channel": "fhamesh:reply:xyz"})
        await orch._stream_preview(envelope, [QueryResult(success=True, data={"x": 1})])

        assert orch._transport.published == []

    async def test_authoritative_summary_still_comes_from_aggregate(self):
        """Streaming is a preview; aggregate() is still the source of truth."""
        orch = _orchestrator_with_streaming(["draft", " preview"])
        orch._aggregator._graph._synthesis_llm = type(
            "S", (), {"ainvoke": staticmethod(lambda messages: _verified_summary())},
        )()

        envelope = MessageEnvelope(payload={"_reply_channel": "fhamesh:reply:xyz"})
        results = [QueryResult(success=True, data={"x": 1})]
        await orch._stream_preview(envelope, results)
        final = await orch._aggregator.aggregate(results)

        assert final.summary == "The verified final answer."


async def _verified_summary():
    return ResultSynthesis(summary="The verified final answer.")


class _FakeStreamingTransport:
    """request_stream() replays a scripted sequence of orchestrator
    responses; publish_to_channel() records what the leaf relayed."""

    def __init__(self, scripted_responses):
        self._scripted = scripted_responses
        self.relayed: list[tuple[str, MessageEnvelope]] = []

    async def request_stream(self, envelope, timeout=15.0):
        for response in self._scripted:
            yield response

    async def publish_to_channel(self, channel, envelope):
        self.relayed.append((channel, envelope))

    async def publish(self, envelope):
        self.relayed.append(("", envelope))


class TestLeafStreamingRelay:
    async def test_relays_chunks_then_the_final_response(self):
        leaf = LeafNode(config={"streaming": {"enabled": True}})
        chunk1 = MessageEnvelope(
            correlation_id="corr-1", message_type=MessageType.STREAM_CHUNK.value,
            payload={"chunk": "Average"},
        )
        chunk2 = MessageEnvelope(
            correlation_id="corr-1", message_type=MessageType.STREAM_CHUNK.value,
            payload={"chunk": " is 42."},
        )
        final_response = MessageEnvelope(
            correlation_id="corr-1", message_type=MessageType.INTENT_RESPONSE.value,
            payload={"result": {"success": True, "summary": "Average is 42."}},
        )
        leaf._transport = _FakeStreamingTransport([chunk1, chunk2, final_response])

        original = MessageEnvelope(
            correlation_id="corr-1",
            source_agent_id="client:1",
            payload={"_reply_channel": "fhamesh:reply:caller"},
        )
        forward = MessageEnvelope(correlation_id="corr-1")

        result = await leaf._forward_streaming(original, forward, "fhamesh:reply:caller")

        # Two chunks relayed live, addressed to the ORIGINAL caller's reply channel
        relayed_chunks = [e for ch, e in leaf._transport.relayed if e.message_type == MessageType.STREAM_CHUNK.value]
        assert [c.payload["chunk"] for c in relayed_chunks] == ["Average", " is 42."]
        assert all(ch == "fhamesh:reply:caller" for ch, e in leaf._transport.relayed
                   if e.message_type == MessageType.STREAM_CHUNK.value)

        # Final response returned (not relayed via send — _process_raw_message handles that)
        assert result is not None
        assert result.message_type == MessageType.INTENT_RESPONSE.value
        assert result.payload["result"]["summary"] == "Average is 42."

    async def test_no_final_response_is_a_timeout(self):
        leaf = LeafNode(config={"streaming": {"enabled": True}})
        leaf._transport = _FakeStreamingTransport([])  # orchestrator never responds

        original = MessageEnvelope(correlation_id="corr-1", payload={"_reply_channel": "fhamesh:reply:caller"})
        forward = MessageEnvelope(correlation_id="corr-1")

        result = await leaf._forward_streaming(original, forward, "fhamesh:reply:caller")

        assert result is not None
        assert result.payload["error"] == "Orchestrator timeout"
