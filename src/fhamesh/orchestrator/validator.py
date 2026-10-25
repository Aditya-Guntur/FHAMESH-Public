"""Execution path validation for the orchestration layer.

Validates that an intent + envelope form a valid execution path
before any processing occurs.
"""

from __future__ import annotations

import logging
from typing import Any

from ..core.message import IntentDescriptor, MessageEnvelope

logger = logging.getLogger(__name__)


class ExecutionPathValidator:
    """Validates structural integrity of incoming requests.

    Checks:
    - Intent was sanitized by a Leaf node
    - Eligibility gate was passed
    - Subtree depth is within limits
    - Required fields are present
    - Correlation chain is valid
    """

    def __init__(self, config: dict[str, Any] | None = None):
        config = config or {}
        self._max_subtree_depth: int = config.get("max_subtree_depth", 5)

    def validate(
        self,
        intent: IntentDescriptor,
        envelope: MessageEnvelope,
    ) -> tuple[bool, str]:
        """Run all validation checks.

        Returns (valid: bool, reason: str).
        """
        # 1. Must be sanitized
        if not intent.sanitized:
            return False, "Intent not marked as sanitized by leaf"

        # 2. Must have passed eligibility
        if not intent.eligibility_passed:
            return False, "Intent did not pass eligibility gate"

        # 3. Subtree depth check
        if envelope.hop_count > self._max_subtree_depth:
            return False, (
                f"Subtree depth {envelope.hop_count} exceeds maximum "
                f"{self._max_subtree_depth}"
            )

        # 4. Must have a category
        if not intent.category:
            return False, "Intent has no category"

        # 5. Must have a domain
        if not intent.domain:
            return False, "Intent has no domain"

        # 6. Must have correlation for traceability
        if not envelope.correlation_id:
            return False, "Missing correlation_id for traceability"

        # 7. Must have come from somewhere
        if not envelope.source_agent_id:
            return False, "Missing source_agent_id"

        return True, "ok"
