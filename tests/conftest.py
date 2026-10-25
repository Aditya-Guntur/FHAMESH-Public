"""Shared fixtures for FHAMESH tests.

All tests use fakeredis — no real Redis server needed.
"""

from __future__ import annotations

import asyncio
from typing import AsyncIterator

import fakeredis
import pytest
import pytest_asyncio

from fhamesh.bus.transport import RedisTransport
from fhamesh.core.registry import AgentRegistry
from fhamesh.security.audit import AuditLogger
from fhamesh.security.credentials import TokenMinter
from fhamesh.security.verifier import CredentialVerifier


@pytest.fixture(scope="session")
def event_loop():
    """Create a session-scoped event loop for async tests."""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture
def fake_redis():
    """Provide a fakeredis instance (sync fixture for simple use)."""
    return fakeredis.FakeAsyncRedis()


@pytest_asyncio.fixture
async def redis_client():
    """Provide an async fakeredis client."""
    client = fakeredis.FakeAsyncRedis()
    yield client
    await client.aclose()


@pytest.fixture
def signing_key() -> str:
    """Shared signing key for tests."""
    return "test_signing_key_32bytes_minimum!!"


@pytest.fixture
def token_minter(signing_key: str) -> TokenMinter:
    """Provide a TokenMinter with test key."""
    return TokenMinter(signing_key)


@pytest.fixture
def verifier(signing_key: str) -> CredentialVerifier:
    """Provide a CredentialVerifier that knows all layer keys."""
    return CredentialVerifier({"leaf": signing_key, "orchestrator": signing_key, "datacore": signing_key})


@pytest_asyncio.fixture
async def audit_logger(tmp_path) -> AsyncIterator[AuditLogger]:
    """Provide an initialized AuditLogger with temp DB."""
    logger = AuditLogger(str(tmp_path / "test_audit.db"))
    await logger.initialize()
    yield logger
    await logger.close()


@pytest_asyncio.fixture
async def registry(redis_client) -> AgentRegistry:
    """Provide an AgentRegistry backed by fakeredis."""
    return AgentRegistry(redis_client)
