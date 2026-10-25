"""Tests for PolicyEngine and RateLimiter."""

import time

import fakeredis
import pytest

from fhamesh.core.message import MessageEnvelope
from fhamesh.core.types import PolicyVerdict
from fhamesh.security.credentials import ScopedToken, TokenMinter
from fhamesh.security.policy import PolicyAttestation, PolicyEngine, RateLimiter
from fhamesh.security.rbac import Permission, RBACEnforcer, Role


@pytest.mark.asyncio
class TestRateLimiter:
    async def test_within_limit(self):
        redis = fakeredis.FakeAsyncRedis()
        limiter = RateLimiter(redis, requests_per_minute=10)
        ok = await limiter.check("test_user")
        assert ok is True
        await redis.aclose()

    async def test_exceeds_limit(self):
        redis = fakeredis.FakeAsyncRedis()
        limiter = RateLimiter(redis, requests_per_minute=3)
        for _ in range(3):
            await limiter.record("test_user")
        ok = await limiter.check("test_user")
        assert ok is False
        await redis.aclose()


@pytest.mark.asyncio
class TestPolicyEngine:
    async def test_allow_with_valid_role(self):
        redis = fakeredis.FakeAsyncRedis()
        rbac = RBACEnforcer({
            "analyst": Role(
                name="analyst",
                permissions=(Permission(resource="employees", action="read"),),
            ),
        })
        limiter = RateLimiter(redis, requests_per_minute=100)
        engine = PolicyEngine(rbac, limiter, signing_key="test_key")

        minter = TokenMinter("test_key_for_minting_tokens!!!!!!")
        token = minter.mint(
            issuer_agent_id="leaf",
            subject_agent_id="orch",
            layer="leaf",
            domain="hr",
            allowed_actions=["read"],
            role="analyst",
            user_id="alice",
        )

        envelope = MessageEnvelope(source_agent_id="leaf", target_agent_id="orch")
        verdict, attestation = await engine.evaluate(
            envelope, token, resource="employees", action="read", agent_id="orch",
        )
        assert verdict == PolicyVerdict.ALLOW
        assert attestation is not None
        assert attestation.signature != ""
        await redis.aclose()

    async def test_deny_unauthorized_role(self):
        redis = fakeredis.FakeAsyncRedis()
        rbac = RBACEnforcer({
            "viewer": Role(
                name="viewer",
                permissions=(Permission(resource="products", action="read"),),
            ),
        })
        limiter = RateLimiter(redis, requests_per_minute=100)
        engine = PolicyEngine(rbac, limiter)

        minter = TokenMinter("test_key_for_minting_tokens!!!!!!")
        token = minter.mint(
            issuer_agent_id="leaf",
            subject_agent_id="orch",
            layer="leaf",
            domain="hr",
            allowed_actions=["read"],
            role="viewer",
            user_id="bob",
        )

        envelope = MessageEnvelope()
        verdict, _ = await engine.evaluate(
            envelope, token, resource="employees", action="read",
        )
        assert verdict == PolicyVerdict.DENY
        await redis.aclose()

    async def test_rate_limited(self):
        redis = fakeredis.FakeAsyncRedis()
        rbac = RBACEnforcer({
            "admin": Role(
                name="admin",
                permissions=(Permission(resource="*", action="*"),),
            ),
        })
        limiter = RateLimiter(redis, requests_per_minute=2)
        engine = PolicyEngine(rbac, limiter)

        minter = TokenMinter("test_key_for_minting_tokens!!!!!!")
        token = minter.mint(
            issuer_agent_id="leaf",
            subject_agent_id="orch",
            layer="leaf",
            domain="general",
            allowed_actions=["read"],
            role="admin",
            user_id="alice",
        )
        envelope = MessageEnvelope()

        # First two should pass
        for _ in range(2):
            v, _ = await engine.evaluate(envelope, token, resource="x", action="read")
            assert v == PolicyVerdict.ALLOW

        # Third should be rate limited
        v, _ = await engine.evaluate(envelope, token, resource="x", action="read")
        assert v == PolicyVerdict.RATE_LIMITED
        await redis.aclose()


class TestPolicyAttestation:
    def test_json_roundtrip(self):
        att = PolicyAttestation(
            agent_id="orch1",
            policy_name="rbac",
            verdict="ALLOW",
        )
        json_str = att.to_json()
        restored = PolicyAttestation.from_json(json_str)
        assert restored.agent_id == "orch1"
        assert restored.verdict == "ALLOW"
