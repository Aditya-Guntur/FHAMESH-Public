"""Tests for SessionMemory — structured-turn short-term memory."""

import pytest

fakeredis = pytest.importorskip("fakeredis")

from fhamesh.leaf.memory import SessionMemory


class TestSessionMemoryInMemory:
    async def test_record_and_recall(self):
        memory = SessionMemory()
        await memory.record_turn("alice", "hr", "lookup_salary", {"department": "engineering"})

        turns = await memory.recall("alice")

        assert len(turns) == 1
        assert turns[0]["domain"] == "hr"
        assert turns[0]["parameters"] == {"department": "engineering"}

    async def test_unknown_user_recalls_nothing(self):
        memory = SessionMemory()
        assert await memory.recall("nobody") == []

    async def test_empty_user_id_is_a_noop(self):
        memory = SessionMemory()
        await memory.record_turn("", "hr", "lookup_salary", {})
        assert await memory.recall("") == []

    async def test_trims_to_max_turns(self):
        memory = SessionMemory(max_turns=2)
        await memory.record_turn("alice", "hr", "a1", {})
        await memory.record_turn("alice", "finance", "a2", {})
        await memory.record_turn("alice", "product", "a3", {})

        turns = await memory.recall("alice")

        assert len(turns) == 2
        assert [t["domain"] for t in turns] == ["finance", "product"]

    async def test_users_are_isolated(self):
        memory = SessionMemory()
        await memory.record_turn("alice", "hr", "a1", {})
        await memory.record_turn("bob", "finance", "a2", {})

        assert [t["domain"] for t in await memory.recall("alice")] == ["hr"]
        assert [t["domain"] for t in await memory.recall("bob")] == ["finance"]

    def test_prompt_context_formatting(self):
        memory = SessionMemory()
        context = memory.as_prompt_context([{"domain": "hr", "action": "lookup_salary", "parameters": {}}])
        assert "domain=hr" in context
        assert "action=lookup_salary" in context

    def test_empty_prompt_context_for_no_turns(self):
        memory = SessionMemory()
        assert memory.as_prompt_context([]) == ""


class TestSessionMemoryRedis:
    async def test_redis_persists_and_shares_across_instances(self):
        import fakeredis.aioredis as fakeredis_aio

        redis_client = fakeredis_aio.FakeRedis()

        first = SessionMemory(max_turns=3)
        first.set_redis(redis_client)
        await first.record_turn("alice", "hr", "lookup_salary", {"department": "engineering"})

        second = SessionMemory(max_turns=3)
        second.set_redis(redis_client)
        turns = await second.recall("alice")

        assert len(turns) == 1
        assert turns[0]["domain"] == "hr"

    async def test_redis_trims_to_max_turns(self):
        import fakeredis.aioredis as fakeredis_aio

        memory = SessionMemory(max_turns=2)
        memory.set_redis(fakeredis_aio.FakeRedis())
        await memory.record_turn("alice", "hr", "a1", {})
        await memory.record_turn("alice", "finance", "a2", {})
        await memory.record_turn("alice", "product", "a3", {})

        turns = await memory.recall("alice")

        assert len(turns) == 2
        assert [t["domain"] for t in turns] == ["finance", "product"]
