"""Integration test: Zero trust authentication chain.

Tests the full security chain: minting -> signing -> verification
across multiple layers, ensuring tokens cannot be reused or tampered with.
"""

import time

import pytest

from fhamesh.security.credentials import ScopedToken, TokenMinter
from fhamesh.security.verifier import CredentialVerifier
from fhamesh.core.types import AgentLayer, PolicyVerdict


class TestZeroTrustChain:
    """Verify the complete zero-trust authentication chain."""

    def test_leaf_to_orchestrator_token_chain(self):
        """A leaf mints a token, the orchestrator verifies it."""
        key = "leaf_key_for_signing_tokens_32c!!"
        leaf_minter = TokenMinter(key)
        # Verifier knows the leaf key
        orch_verifier = CredentialVerifier({"leaf": key})

        token = leaf_minter.mint(
            issuer_agent_id="leaf:general:abc",
            subject_agent_id="orch:general:def",
            layer="leaf",
            domain="general",
            allowed_actions=["intent_request"],
            role="analyst",
            user_id="alice",
        )

        result = orch_verifier.verify(token, expected_action="intent_request")
        assert result == PolicyVerdict.ALLOW

    def test_token_rejected_wrong_action(self):
        """Token minted for intent_request should not authorize data_query."""
        key = "shared_key_for_all_the_tests_32c!"
        minter = TokenMinter(key)
        verifier = CredentialVerifier({"leaf": key})

        token = minter.mint(
            issuer_agent_id="leaf:general:abc",
            subject_agent_id="orch:general:def",
            layer="leaf",
            domain="general",
            allowed_actions=["intent_request"],
        )

        result = verifier.verify(token, expected_action="data_query")
        assert result == PolicyVerdict.DENY

    def test_expired_token_rejected(self):
        """An expired token must be rejected."""
        key = "shared_key_for_all_the_tests_32c!"
        minter = TokenMinter(key)
        verifier = CredentialVerifier({"leaf": key})

        token = minter.mint(
            issuer_agent_id="leaf:general:abc",
            subject_agent_id="orch:general:def",
            layer="leaf",
            domain="general",
            allowed_actions=["intent_request"],
            ttl_seconds=0,  # Expires immediately
        )

        time.sleep(0.01)

        result = verifier.verify(token, expected_action="intent_request")
        assert result == PolicyVerdict.DENY

    def test_tampered_token_rejected(self):
        """A tampered token must fail signature verification."""
        key = "shared_key_for_all_the_tests_32c!"
        minter = TokenMinter(key)
        verifier = CredentialVerifier({"leaf": key})

        token = minter.mint(
            issuer_agent_id="leaf:general:abc",
            subject_agent_id="orch:general:def",
            layer="leaf",
            domain="general",
            allowed_actions=["intent_request"],
        )

        # Tamper with the role (escalation attempt)
        d = token.to_dict()
        d["role"] = "admin"
        tampered = ScopedToken.from_dict(d)

        result = verifier.verify(tampered, expected_action="intent_request")
        assert result == PolicyVerdict.DENY

    def test_cross_layer_token_isolation(self):
        """Tokens signed by one layer's key must not verify with another layer's key."""
        leaf_key = "leaf_signing_key_at_least_32_bytes!"
        orch_key = "orch_signing_key_at_least_32_bytes!"
        leaf_minter = TokenMinter(leaf_key)

        # Leaf mints a token
        token = leaf_minter.mint(
            issuer_agent_id="leaf:general:abc",
            subject_agent_id="orch:general:def",
            layer="leaf",
            domain="general",
            allowed_actions=["intent_request"],
        )

        # Verifier only knows the orchestrator key (not the real leaf key)
        orch_verifier = CredentialVerifier({"leaf": orch_key})
        result = orch_verifier.verify(token, expected_action="intent_request")
        assert result == PolicyVerdict.DENY
