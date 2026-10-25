"""Tests for ScopedToken and TokenMinter."""

import time

import pytest

from fhamesh.security.credentials import ScopedToken, TokenMinter


class TestScopedToken:
    def test_create(self):
        token = ScopedToken(
            issuer_agent_id="agent_a",
            subject_agent_id="agent_b",
            layer="leaf",
            domain="hr",
            allowed_actions=("read",),
        )
        assert token.issuer_agent_id == "agent_a"
        assert token.allowed_actions == ("read",)

    def test_frozen(self):
        token = ScopedToken()
        with pytest.raises(AttributeError):
            token.layer = "hacked"  # type: ignore

    def test_is_expired(self):
        token = ScopedToken(expires_at=time.time() - 10)
        assert token.is_expired()

    def test_not_expired(self):
        token = ScopedToken(expires_at=time.time() + 100)
        assert not token.is_expired()

    def test_json_roundtrip(self):
        token = ScopedToken(
            issuer_agent_id="a",
            allowed_actions=("read", "write"),
            scoped_fields=("name", "salary"),
        )
        json_str = token.to_json()
        restored = ScopedToken.from_json(json_str)
        assert restored.allowed_actions == ("read", "write")
        assert restored.scoped_fields == ("name", "salary")


class TestTokenMinter:
    def test_mint_produces_signed_token(self):
        minter = TokenMinter("test_key_at_least_32_bytes!!!!!!!")
        token = minter.mint(
            issuer_agent_id="leaf:general:abc",
            subject_agent_id="orch:general:def",
            layer="leaf",
            domain="general",
            allowed_actions=["intent_request"],
        )
        assert token.signature != ""
        assert token.issuer_agent_id == "leaf:general:abc"
        assert not token.is_expired()

    def test_verify_valid_signature(self):
        minter = TokenMinter("test_key_at_least_32_bytes!!!!!!!")
        token = minter.mint(
            issuer_agent_id="a",
            subject_agent_id="b",
            layer="leaf",
            domain="general",
            allowed_actions=["read"],
        )
        assert minter.verify_signature(token) is True

    def test_verify_tampered_signature(self):
        minter = TokenMinter("test_key_at_least_32_bytes!!!!!!!")
        token = minter.mint(
            issuer_agent_id="a",
            subject_agent_id="b",
            layer="leaf",
            domain="general",
            allowed_actions=["read"],
        )
        d = token.to_dict()
        d["signature"] = "tampered_" + d["signature"]
        tampered = ScopedToken.from_dict(d)
        assert minter.verify_signature(tampered) is False

    def test_different_keys_different_signatures(self):
        minter1 = TokenMinter("key_one_at_least_32_bytes_long!!!")
        minter2 = TokenMinter("key_two_at_least_32_bytes_long!!!")
        token = minter1.mint(
            issuer_agent_id="a",
            subject_agent_id="b",
            layer="leaf",
            domain="general",
            allowed_actions=["read"],
        )
        assert minter2.verify_signature(token) is False

    def test_ttl_sets_expiry(self):
        minter = TokenMinter("test_key_at_least_32_bytes!!!!!!!")
        token = minter.mint(
            issuer_agent_id="a",
            subject_agent_id="b",
            layer="leaf",
            domain="general",
            allowed_actions=["read"],
            ttl_seconds=60,
        )
        assert token.expires_at > time.time()
        assert token.expires_at <= time.time() + 61
