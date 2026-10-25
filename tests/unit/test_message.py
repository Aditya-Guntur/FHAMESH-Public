"""Tests for MessageEnvelope, IntentDescriptor, QueryResult."""

import time

import pytest

from fhamesh.core.message import IntentDescriptor, MessageEnvelope, QueryResult


class TestMessageEnvelope:
    def test_create_default(self):
        env = MessageEnvelope()
        assert len(env.message_id) == 16
        assert env.hop_count == 0
        assert env.max_hops == 10
        assert env.ttl_seconds == 30

    def test_frozen(self):
        env = MessageEnvelope()
        with pytest.raises(AttributeError):
            env.hop_count = 5  # type: ignore

    def test_content_hash_deterministic(self):
        env = MessageEnvelope(payload={"key": "value"})
        assert env.content_hash() == env.content_hash()

    def test_content_hash_changes_with_payload(self):
        env1 = MessageEnvelope(payload={"a": 1})
        env2 = MessageEnvelope(payload={"a": 2})
        assert env1.content_hash() != env2.content_hash()

    def test_is_expired(self):
        env = MessageEnvelope(timestamp=time.time() - 100, ttl_seconds=30)
        assert env.is_expired()

    def test_not_expired(self):
        env = MessageEnvelope(ttl_seconds=30)
        assert not env.is_expired()

    def test_with_hop(self):
        env = MessageEnvelope(hop_count=2)
        hopped = env.with_hop()
        assert hopped.hop_count == 3
        assert env.hop_count == 2

    def test_serialization_roundtrip(self):
        env = MessageEnvelope(
            message_type="test",
            source_agent_id="agent_a",
            target_agent_id="agent_b",
            payload={"data": [1, 2, 3]},
        )
        data = env.to_bytes()
        restored = MessageEnvelope.from_bytes(data)
        assert restored.message_type == "test"
        assert restored.source_agent_id == "agent_a"
        assert restored.payload == {"data": [1, 2, 3]}

    def test_dict_roundtrip(self):
        env = MessageEnvelope(payload={"x": 42})
        d = env.to_dict()
        restored = MessageEnvelope.from_dict(d)
        assert restored.payload == {"x": 42}

    def test_reply(self):
        original = MessageEnvelope(
            message_id="orig123",
            source_agent_id="sender",
            target_agent_id="receiver",
            correlation_id="corr1",
        )
        reply = original.reply(
            message_type="response",
            payload={"result": "ok"},
            source_agent_id="receiver",
        )
        assert reply.target_agent_id == "sender"
        assert reply.source_agent_id == "receiver"
        assert reply.correlation_id == "corr1"
        assert reply.parent_message_id == "orig123"
        assert reply.hop_count == original.hop_count + 1


class TestIntentDescriptor:
    def test_defaults(self):
        intent = IntentDescriptor()
        assert intent.domain == "general"
        assert intent.confidence == 0.0
        assert intent.sanitized is False

    def test_dict_roundtrip(self):
        intent = IntentDescriptor(
            category="query",
            domain="hr",
            action="lookup_salary",
            confidence=0.85,
        )
        d = intent.to_dict()
        restored = IntentDescriptor.from_dict(d)
        assert restored.domain == "hr"
        assert restored.confidence == 0.85


class TestQueryResult:
    def test_success_result(self):
        result = QueryResult(
            success=True,
            data={"rows": [{"id": 1}]},
            privacy_budget_consumed=0.5,
        )
        assert result.success
        assert result.privacy_budget_consumed == 0.5

    def test_error_result(self):
        result = QueryResult(success=False, error_message="denied")
        assert not result.success
        assert result.error_message == "denied"

    def test_dict_roundtrip(self):
        result = QueryResult(success=True, data={"count": 10}, noise_applied=True)
        d = result.to_dict()
        restored = QueryResult.from_dict(d)
        assert restored.noise_applied is True
