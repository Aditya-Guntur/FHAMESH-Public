"""Scoped tokens and token minting for zero trust authentication.

Every message in the mesh carries a ScopedToken. Tokens are:
- Short-lived (configurable TTL, default 30s)
- Scoped to a specific agent, layer, domain, and set of allowed actions
- HMAC-SHA256 signed so tampering is detectable
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class ScopedToken:
    """An HMAC-signed, short-lived, scoped credential.

    Attached to every MessageEnvelope. Verified by the receiving agent
    before processing. Trust is never inherited — each hop verifies.
    """

    token_id: str = field(default_factory=lambda: uuid.uuid4().hex[:16])
    issuer_agent_id: str = ""
    subject_agent_id: str = ""
    layer: str = ""
    domain: str = ""
    allowed_actions: tuple[str, ...] = ()
    issued_at: float = field(default_factory=time.time)
    expires_at: float = 0.0
    scoped_fields: tuple[str, ...] = ()
    role: str = ""
    user_id: str = ""
    signature: str = ""

    def is_expired(self) -> bool:
        """Check if the token has exceeded its lifetime."""
        return time.time() > self.expires_at

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a plain dictionary."""
        d = asdict(self)
        d["allowed_actions"] = list(self.allowed_actions)
        d["scoped_fields"] = list(self.scoped_fields)
        return d

    def to_json(self) -> str:
        """Serialize to JSON string."""
        return json.dumps(self.to_dict(), sort_keys=True, default=str)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ScopedToken:
        """Construct from a plain dictionary."""
        data = dict(data)
        if "allowed_actions" in data:
            data["allowed_actions"] = tuple(data["allowed_actions"])
        if "scoped_fields" in data:
            data["scoped_fields"] = tuple(data["scoped_fields"])
        valid_fields = {f.name for f in cls.__dataclass_fields__.values()}
        filtered = {k: v for k, v in data.items() if k in valid_fields}
        return cls(**filtered)

    @classmethod
    def from_json(cls, raw: str) -> ScopedToken:
        """Deserialize from JSON string."""
        return cls.from_dict(json.loads(raw))


class TokenMinter:
    """Creates and signs ScopedTokens using HMAC-SHA256.

    Each agent layer has its own signing key. Tokens minted by one layer
    can only be verified by agents that know that layer's key.
    """

    def __init__(self, signing_key: str | bytes):
        if isinstance(signing_key, str):
            signing_key = signing_key.encode("utf-8")
        self._key = signing_key

    def mint(
        self,
        issuer_agent_id: str,
        subject_agent_id: str,
        layer: str,
        domain: str,
        allowed_actions: list[str],
        ttl_seconds: int = 30,
        scoped_fields: list[str] | None = None,
        role: str = "",
        user_id: str = "",
    ) -> ScopedToken:
        """Create a new signed ScopedToken."""
        now = time.time()
        token = ScopedToken(
            issuer_agent_id=issuer_agent_id,
            subject_agent_id=subject_agent_id,
            layer=layer,
            domain=domain,
            allowed_actions=tuple(allowed_actions),
            issued_at=now,
            expires_at=now + ttl_seconds,
            scoped_fields=tuple(scoped_fields or []),
            role=role,
            user_id=user_id,
        )
        signature = self._sign(token)
        # Rebuild with signature (frozen dataclass)
        d = token.to_dict()
        d["signature"] = signature
        return ScopedToken.from_dict(d)

    def _sign(self, token: ScopedToken) -> str:
        """Compute HMAC-SHA256 over canonical token fields (excluding signature)."""
        d = token.to_dict()
        d.pop("signature", None)
        canonical = json.dumps(d, sort_keys=True, default=str)
        return hmac.new(self._key, canonical.encode("utf-8"), hashlib.sha256).hexdigest()

    def verify_signature(self, token: ScopedToken) -> bool:
        """Recompute HMAC and compare against the token's signature."""
        expected = self._sign(token)
        return hmac.compare_digest(expected, token.signature)
