"""Row-Level Security for the Data Core.

Filters query results based on the caller's identity and role.
Policies define which rows each role can see.
"""

from __future__ import annotations

import logging
from typing import Any

from ..security.credentials import ScopedToken
from .storage import RLSContext

logger = logging.getLogger(__name__)

# Default RLS policies: role -> table -> predicates
_DEFAULT_POLICIES: dict[str, dict[str, dict[str, Any]]] = {
    "admin": {},  # No restrictions
    "analyst": {
        "employees": {},  # Can see all employees (but field access is controlled by RBAC)
        "orders": {},
    },
    "viewer": {
        "employees": {},  # Can see all employees (limited fields via RBAC)
        "products": {},
    },
    "hr_manager": {
        "employees": {},  # Can see all employees
    },
    "engineering_lead": {
        "employees": {"department": "engineering"},  # Only engineering dept
    },
    "finance_viewer": {
        "orders": {},
        "employees": {"department": "finance"},
    },
}


class RowLevelSecurity:
    """Filters query results based on caller identity.

    Each role has RLS policies that define row-level predicates.
    These predicates are injected into the query's WHERE clause.
    """

    def __init__(self, config: dict[str, Any] | None = None):
        config = config or {}
        self._policies = config.get("policies", _DEFAULT_POLICIES)

    def build_context(
        self,
        auth_token_raw: str = "",
        user_id: str = "",
        role: str = "viewer",
    ) -> RLSContext:
        """Build an RLS context from authentication info."""
        department = ""

        if auth_token_raw:
            try:
                token = ScopedToken.from_json(auth_token_raw)
                user_id = token.user_id or user_id
                role = token.role or role
                department = token.domain if token.domain not in ("general",) else ""
            except (ValueError, KeyError):
                pass

        # Look up predicates for this role
        predicates = self._get_predicates(role)

        return RLSContext(
            user_id=user_id,
            role=role,
            department=department,
            predicates=predicates,
        )

    def build_context_for_table(
        self,
        table: str,
        auth_token_raw: str = "",
        user_id: str = "",
        role: str = "viewer",
    ) -> RLSContext:
        """Build an RLS context specific to a table."""
        context = self.build_context(auth_token_raw, user_id, role)

        # Get table-specific predicates
        role_policies = self._policies.get(role, {})
        table_predicates = role_policies.get(table, {})

        if table_predicates:
            context.predicates.update(table_predicates)

        return context

    def _get_predicates(self, role: str) -> dict[str, Any]:
        """Get base predicates for a role (non-table-specific)."""
        # Admin has no restrictions
        if role == "admin":
            return {}

        role_policies = self._policies.get(role, {})

        # Collect any common predicates across all tables
        common: dict[str, Any] = {}
        for table, preds in role_policies.items():
            if isinstance(preds, dict):
                common.update(preds)

        return common

    def check_table_access(self, role: str, table: str) -> bool:
        """Check if a role has any access to a table."""
        if role == "admin":
            return True
        role_policies = self._policies.get(role, {})
        if not role_policies:
            return True  # No explicit policy = allow (controlled by RBAC instead)
        return table in role_policies
