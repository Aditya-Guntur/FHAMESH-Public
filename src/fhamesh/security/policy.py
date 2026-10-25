"""Policy engine and rate limiter for the agent mesh.

Evaluates a chain of policy rules against incoming requests.
Produces PolicyAttestations that downstream agents can verify.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import time
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any

import redis.asyncio as aioredis

from ..core.message import MessageEnvelope
from ..core.types import PolicyVerdict
from .credentials import ScopedToken
from .rbac import RBACEnforcer

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class PolicyAttestation:
    """Signed statement that a policy check was performed.

    Attached to messages so downstream agents can verify
    that the upstream agent enforced policy at its boundary.
    """
    attestation_id: str = field(default_factory=lambda: uuid.uuid4().hex[:16])
    agent_id: str = ""
    policy_name: str = ""
    verdict: str = ""
    checked_at: float = field(default_factory=time.time)
    details: str = ""
    signature: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), sort_keys=True, default=str)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PolicyAttestation:
        valid_fields = {f.name for f in cls.__dataclass_fields__.values()}
        return cls(**{k: v for k, v in data.items() if k in valid_fields})

    @classmethod
    def from_json(cls, raw: str) -> PolicyAttestation:
        return cls.from_dict(json.loads(raw))


class PolicyEngine:
    """Evaluates policy rules against a request.

    Combines RBAC checks, rate limiting, and custom rules.
    Produces a PolicyAttestation on success that is carried forward.
    """

    def __init__(
        self,
        rbac: RBACEnforcer,
        rate_limiter: RateLimiter,
        signing_key: str | bytes = b"policy_signing_key",
    ):
        self._rbac = rbac
        self._rate_limiter = rate_limiter
        if isinstance(signing_key, str):
            signing_key = signing_key.encode("utf-8")
        self._signing_key = signing_key

    async def evaluate(
        self,
        envelope: MessageEnvelope,
        token: ScopedToken,
        resource: str = "",
        action: str = "read",
        fields: list[str] | None = None,
        agent_id: str = "",
    ) -> tuple[PolicyVerdict, PolicyAttestation | None]:
        """Run all policy checks. Returns (verdict, attestation).

        Checks in order:
        1. Rate limit
        2. RBAC permission
        First failure wins — no further checks run.
        """
        # 1. Rate limit check
        rate_key = f"rate:{token.user_id or token.issuer_agent_id}"
        if not await self._rate_limiter.check(rate_key):
            logger.warning("Rate limit exceeded for %s", rate_key)
            return PolicyVerdict.RATE_LIMITED, None

        await self._rate_limiter.record(rate_key)

        # 2. RBAC check
        if token.role:
            if not self._rbac.check(token.role, resource, action, fields):
                logger.warning(
                    "RBAC denied: role=%s resource=%s action=%s",
                    token.role, resource, action,
                )
                return PolicyVerdict.DENY, None

        # All checks passed — produce attestation
        attestation = self._create_attestation(agent_id, "rbac_and_rate_limit")
        return PolicyVerdict.ALLOW, attestation

    def _create_attestation(self, agent_id: str, policy_name: str) -> PolicyAttestation:
        """Create a signed attestation that policy was checked."""
        att = PolicyAttestation(
            agent_id=agent_id,
            policy_name=policy_name,
            verdict=PolicyVerdict.ALLOW.name,
            checked_at=time.time(),
        )
        sig = self._sign_attestation(att)
        d = att.to_dict()
        d["signature"] = sig
        return PolicyAttestation.from_dict(d)

    def _sign_attestation(self, att: PolicyAttestation) -> str:
        """HMAC-SHA256 sign the attestation."""
        d = att.to_dict()
        d.pop("signature", None)
        canonical = json.dumps(d, sort_keys=True, default=str)
        return hmac.new(
            self._signing_key, canonical.encode("utf-8"), hashlib.sha256
        ).hexdigest()

    def verify_attestation(self, att: PolicyAttestation) -> bool:
        """Verify an attestation's signature."""
        expected = self._sign_attestation(att)
        return hmac.compare_digest(expected, att.signature)


class RateLimiter:
    """Redis-backed sliding window rate limiter.

    Uses sorted sets in Redis to implement a sliding window counter.
    Each request is a timestamped entry; expired entries are pruned.
    """

    def __init__(
        self,
        redis_client: aioredis.Redis,
        requests_per_minute: int = 60,
        burst: int = 10,
    ):
        self._redis = redis_client
        self._rpm = requests_per_minute
        self._burst = burst
        self._window_seconds = 60

    async def check(self, key: str) -> bool:
        """Check if the key is within its rate limit.

        Returns True if the request is allowed, False if rate-limited.
        """
        now = time.time()
        window_start = now - self._window_seconds
        redis_key = f"fhamesh:ratelimit:{key}"

        # Count requests in the current window
        count = await self._redis.zcount(redis_key, window_start, now)
        return count < self._rpm

    async def record(self, key: str) -> None:
        """Record a request for rate limiting."""
        now = time.time()
        redis_key = f"fhamesh:ratelimit:{key}"
        member = f"{now}:{uuid.uuid4().hex[:8]}"

        pipe = self._redis.pipeline()
        pipe.zadd(redis_key, {member: now})
        # Prune entries older than the window
        pipe.zremrangebyscore(redis_key, 0, now - self._window_seconds)
        pipe.expire(redis_key, self._window_seconds + 10)
        await pipe.execute()
