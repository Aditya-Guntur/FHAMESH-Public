"""Integration tests for the zero trust security chain."""

import time

import fakeredis
import pytest

from fhamesh.security.credentials import ScopedToken, TokenMinter
from fhamesh.security.policy import PolicyAttestation, PolicyEngine, RateLimiter
from fhamesh.security.rbac import Permission, RBACEnforcer, Role
from fhamesh.security.verifier import CredentialVerifier
from fhamesh.core.message import MessageEnvelope
from fhamesh.core.types import PolicyVerdict


class TestSecurityChain:
    """Test the full security chain: mint -> verify -> policy -> attestation."""

    def test_mint_and_verify(self):
        key = "test_signing_key_must_be_long_enough!!"
        minter = TokenMinter(key)
        verifier = CredentialVerifier({"leaf": key, "orchestrator": key, "datacore": key})

        token = minter.mint(
            issuer_agent_id="leaf:general:abc",
            subject_agent_id="orch:general:def",
            layer="leaf",
            domain="general",
            allowed_actions=["intent_request"],
            role="analyst",
            user_id="alice",
        )

        # Verify signature
        assert minter.verify_signature(token) is True

        # Verify through verifier chain — returns PolicyVerdict
        result = verifier.verify(
            token,
            expected_action="intent_request",
            expected_target="orch:general:def",
        )
        assert result == PolicyVerdict.ALLOW

    def test_expired_token_rejected(self):
        key = "test_signing_key_must_be_long_enough!!"
        minter = TokenMinter(key)
        verifier = CredentialVerifier({"leaf": key})

        token = minter.mint(
            issuer_agent_id="a",
            subject_agent_id="b",
            layer="leaf",
            domain="general",
            allowed_actions=["read"],
            ttl_seconds=-1,  # Already expired
        )

        result = verifier.verify(token, expected_action="read")
        assert result == PolicyVerdict.DENY

    def test_wrong_action_rejected(self):
        key = "test_signing_key_must_be_long_enough!!"
        minter = TokenMinter(key)
        verifier = CredentialVerifier({"leaf": key})

        token = minter.mint(
            issuer_agent_id="a",
            subject_agent_id="b",
            layer="leaf",
            domain="general",
            allowed_actions=["read"],
        )

        result = verifier.verify(token, expected_action="write")
        assert result == PolicyVerdict.DENY

    @pytest.mark.asyncio
    async def test_full_chain_with_policy(self):
        redis = fakeredis.FakeAsyncRedis()
        key = "test_signing_key_must_be_long_enough!!"

        minter = TokenMinter(key)
        rbac = RBACEnforcer({
            "analyst": Role(
                name="analyst",
                permissions=(
                    Permission(resource="employees", action="read"),
                    Permission(resource="products", action="read"),
                ),
            ),
        })
        limiter = RateLimiter(redis, requests_per_minute=100)
        engine = PolicyEngine(rbac, limiter, signing_key=key)

        # Mint token
        token = minter.mint(
            issuer_agent_id="leaf",
            subject_agent_id="orch",
            layer="leaf",
            domain="hr",
            allowed_actions=["read"],
            role="analyst",
            user_id="alice",
        )

        # Evaluate policy
        envelope = MessageEnvelope(source_agent_id="leaf", target_agent_id="orch")
        verdict, attestation = await engine.evaluate(
            envelope, token,
            resource="employees", action="read",
            agent_id="orch",
        )

        assert verdict == PolicyVerdict.ALLOW
        assert attestation is not None

        # Verify attestation signature
        assert engine.verify_attestation(attestation) is True

        await redis.aclose()
