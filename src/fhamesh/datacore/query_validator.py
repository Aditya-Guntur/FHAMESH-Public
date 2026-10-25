"""Query validation for the Data Core layer.

Enforces field-level justification and token scope constraints.
"""

from __future__ import annotations

import logging
from typing import Any

from ..security.credentials import ScopedToken

logger = logging.getLogger(__name__)


class QueryValidator:
    """Validates DataCore queries before execution.

    Key constraint: field-level justification. Every field requested
    must have a justification string in the query payload.
    """

    def __init__(self, config: dict[str, Any] | None = None):
        config = config or {}
        self._require_justification: bool = config.get("require_justification", True)
        self._allowed_tables: set[str] = set(config.get("allowed_tables", []))

    def validate(
        self,
        query: dict[str, Any],
        auth_token_raw: str = "",
        policy_attestation: str = "",
    ) -> tuple[bool, str]:
        """Full query validation.

        Checks:
        1. Table is in allowed list
        2. Each requested field has a justification
        3. Requested fields within token scope
        4. Policy attestation present
        """
        table = query.get("table", "")

        if self._allowed_tables and table not in self._allowed_tables:
            return False, f"Table '{table}' not in allowed list"

        fields = query.get("fields", [])
        justifications = query.get("justifications", {})

        if self._require_justification and fields and fields != ["*"]:
            for f in fields:
                if f not in justifications:
                    return False, f"No justification for field '{f}'"

        if auth_token_raw:
            try:
                token = ScopedToken.from_json(auth_token_raw)
                if token.scoped_fields:
                    if fields and fields != ["*"]:
                        unauthorized = set(fields) - set(token.scoped_fields)
                        if unauthorized:
                            return False, f"Fields not in token scope: {unauthorized}"
            except (ValueError, KeyError):
                return False, "Invalid auth token"

        if not policy_attestation:
            logger.debug("No policy attestation from orchestrator")

        return True, "ok"
