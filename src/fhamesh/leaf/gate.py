"""Eligibility gating — pre-flight checks before forwarding to orchestrator.

Determines whether a request is sufficiently well-formed to proceed.
"""

from __future__ import annotations

import logging
from typing import Any

from ..core.message import IntentDescriptor
from ..core.types import IntentCategory
from ..security.credentials import ScopedToken

logger = logging.getLogger(__name__)


class EligibilityGate:
    """Pre-flight checks on classified intents.

    An intent must pass all gates before being forwarded to an orchestrator.
    """

    def __init__(self, config: dict[str, Any] | None = None):
        config = config or {}
        self._min_confidence: float = config.get("min_confidence", 0.3)

    async def check(
        self,
        intent: IntentDescriptor,
        token: ScopedToken | None = None,
    ) -> tuple[bool, str]:
        """Run all eligibility checks.

        Returns (eligible: bool, reason: str).
        """
        # 1. Must have authentication
        if token is None:
            return False, "No authentication token"

        # 2. Token must not be expired
        if token.is_expired():
            return False, "Authentication token expired"

        # 3. Intent must not be UNKNOWN
        if intent.category == IntentCategory.UNKNOWN.value:
            return False, "Unrecognized intent category"

        # 4. Confidence threshold
        if intent.confidence < self._min_confidence:
            return False, (
                f"Confidence {intent.confidence:.3f} below threshold "
                f"{self._min_confidence:.3f}"
            )

        # 5. Must have a domain
        if not intent.domain:
            return False, "No domain identified"

        # 6. Must have an action
        if not intent.action:
            return False, "No action identified"

        return True, "ok"
