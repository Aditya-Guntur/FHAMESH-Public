"""Role-Based Access Control for the agent mesh.

Roles define what resources an identity can access, at what
granularity (field-level), and with what constraints (depth, rate).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class Permission:
    """A single permission entry — resource + action + optional field list."""
    resource: str
    action: str
    fields: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class Role:
    """A named role with a set of permissions and constraints."""
    name: str
    permissions: tuple[Permission, ...] = ()
    max_query_depth: int = 3
    rate_limit_per_minute: int = 60


class RBACEnforcer:
    """Evaluates whether a role is authorized for a given action.

    Loaded from config/policies.yaml. Supports wildcard ('*') resources
    and actions for admin roles.
    """

    def __init__(self, roles: dict[str, Role] | None = None):
        self._roles: dict[str, Role] = roles or {}

    @classmethod
    def from_config(cls, policies_config: dict[str, Any]) -> RBACEnforcer:
        """Build from the policies config dictionary."""
        roles = {}
        for role_name, role_data in policies_config.get("roles", {}).items():
            perms = []
            for p in role_data.get("permissions", []):
                perms.append(Permission(
                    resource=p.get("resource", ""),
                    action=p.get("action", ""),
                    fields=tuple(p.get("fields", [])),
                ))
            roles[role_name] = Role(
                name=role_name,
                permissions=tuple(perms),
                max_query_depth=role_data.get("max_query_depth", 3),
                rate_limit_per_minute=role_data.get("rate_limit_per_minute", 60),
            )
        return cls(roles)

    def check(
        self,
        role_name: str,
        resource: str,
        action: str,
        fields: list[str] | None = None,
    ) -> bool:
        """Check if the role has permission for resource.action.

        If fields are specified, also checks field-level access.
        Supports wildcard ('*') for admin-style permissions.
        """
        role = self._roles.get(role_name)
        if role is None:
            logger.warning("Unknown role: %s", role_name)
            return False

        for perm in role.permissions:
            resource_match = perm.resource == "*" or perm.resource == resource
            action_match = perm.action == "*" or perm.action == action
            if resource_match and action_match:
                if fields and perm.fields:
                    unauthorized = set(fields) - set(perm.fields)
                    if unauthorized:
                        logger.warning(
                            "Role %s cannot access fields %s on %s",
                            role_name, unauthorized, resource,
                        )
                        return False
                return True

        logger.warning("Role %s has no permission for %s.%s", role_name, resource, action)
        return False

    def get_allowed_fields(self, role_name: str, resource: str) -> list[str]:
        """Return which fields a role can access for a resource."""
        role = self._roles.get(role_name)
        if role is None:
            return []
        for perm in role.permissions:
            resource_match = perm.resource == "*" or perm.resource == resource
            if resource_match:
                if perm.fields:
                    return list(perm.fields)
                return ["*"]  # wildcard = all fields
        return []

    def get_max_depth(self, role_name: str) -> int:
        """Return the max subtree depth for a role."""
        role = self._roles.get(role_name)
        return role.max_query_depth if role else 0

    def get_rate_limit(self, role_name: str) -> int:
        """Return the rate limit (requests/min) for a role."""
        role = self._roles.get(role_name)
        return role.rate_limit_per_minute if role else 0

    def list_roles(self) -> list[str]:
        """Return all known role names."""
        return list(self._roles.keys())
