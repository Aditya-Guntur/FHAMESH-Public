"""Credential verification — the core of zero trust enforcement.

Called on EVERY inbound message. Trust is never inherited; it is
re-established at every boundary crossing.
"""

from __future__ import annotations

import logging
from typing import Any

from ..core.types import AgentLayer, PolicyVerdict
from .credentials import ScopedToken, TokenMinter

logger = logging.getLogger(__name__)


class CredentialVerifier:
    """Validates inbound ScopedTokens at every agent boundary.

    Each layer has its own signing key. The verifier holds all keys
    so it can validate tokens from any layer.
    """

    def __init__(self, signing_keys: dict[str, str | bytes]):
        """Initialize with a mapping of layer name -> signing key."""
        self._minters: dict[str, TokenMinter] = {}
        for layer, key in signing_keys.items():
            self._minters[layer] = TokenMinter(key)

    def verify(
        self,
        token: ScopedToken,
        expected_action: str,
        expected_target: str = "",
    ) -> PolicyVerdict:
        """Full token verification chain.

        Checks:
        1. Token layer has a known signing key
        2. HMAC signature is valid (tamper detection)
        3. Token is not expired
        4. Requested action is in the token's allowed_actions
        5. Target agent matches subject_agent_id (if specified)

        Returns PolicyVerdict.ALLOW on success, DENY on failure.
        """
        # 1. Layer known?
        minter = self._minters.get(token.layer)
        if minter is None:
            logger.warning("Unknown token layer: %s", token.layer)
            return PolicyVerdict.DENY

        # 2. Signature valid?
        if not minter.verify_signature(token):
            logger.warning("Invalid signature on token %s", token.token_id)
            return PolicyVerdict.DENY

        # 3. Expired?
        if token.is_expired():
            logger.warning("Expired token %s", token.token_id)
            return PolicyVerdict.DENY

        # 4. Action authorized?
        if token.allowed_actions and expected_action not in token.allowed_actions:
            # Wildcard check
            if "*" not in token.allowed_actions:
                logger.warning(
                    "Action '%s' not in allowed actions %s for token %s",
                    expected_action, token.allowed_actions, token.token_id,
                )
                return PolicyVerdict.DENY

        # 5. Target match?
        if expected_target and token.subject_agent_id:
            if token.subject_agent_id != expected_target:
                logger.warning(
                    "Token subject %s does not match target %s",
                    token.subject_agent_id, expected_target,
                )
                return PolicyVerdict.DENY

        return PolicyVerdict.ALLOW

    def extract_token(self, raw: str) -> ScopedToken | None:
        """Parse a token from its JSON string representation."""
        if not raw:
            return None
        try:
            return ScopedToken.from_json(raw)
        except (ValueError, KeyError) as exc:
            logger.warning("Failed to parse token: %s", exc)
            return None
