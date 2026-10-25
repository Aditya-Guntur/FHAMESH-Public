"""Tests for RBAC enforcement."""

import pytest

from fhamesh.security.rbac import Permission, RBACEnforcer, Role


class TestRBACEnforcer:
    def setup_method(self):
        self.rbac = RBACEnforcer({
            "admin": Role(
                name="admin",
                permissions=(Permission(resource="*", action="*"),),
                max_query_depth=10,
                rate_limit_per_minute=120,
            ),
            "analyst": Role(
                name="analyst",
                permissions=(
                    Permission(resource="employees", action="read", fields=("name", "department", "salary")),
                    Permission(resource="products", action="read"),
                    Permission(resource="orders", action="read"),
                ),
                max_query_depth=3,
                rate_limit_per_minute=60,
            ),
            "viewer": Role(
                name="viewer",
                permissions=(
                    Permission(resource="products", action="read", fields=("name", "price")),
                ),
                max_query_depth=1,
                rate_limit_per_minute=20,
            ),
        })

    def test_admin_can_do_anything(self):
        assert self.rbac.check("admin", "employees", "read") is True
        assert self.rbac.check("admin", "anything", "write") is True

    def test_analyst_can_read_employees(self):
        assert self.rbac.check("analyst", "employees", "read") is True

    def test_analyst_cannot_write(self):
        assert self.rbac.check("analyst", "employees", "write") is False

    def test_viewer_limited_fields(self):
        assert self.rbac.check("viewer", "products", "read", ["name"]) is True
        assert self.rbac.check("viewer", "products", "read", ["name", "cost"]) is False

    def test_unknown_role(self):
        assert self.rbac.check("hacker", "employees", "read") is False

    def test_from_config(self):
        config = {
            "roles": {
                "tester": {
                    "permissions": [
                        {"resource": "tests", "action": "read", "fields": ["name"]},
                    ],
                    "max_query_depth": 2,
                    "rate_limit_per_minute": 10,
                },
            },
        }
        rbac = RBACEnforcer.from_config(config)
        assert rbac.check("tester", "tests", "read") is True
        assert rbac.check("tester", "tests", "write") is False

    def test_get_allowed_fields(self):
        fields = self.rbac.get_allowed_fields("analyst", "employees")
        assert "name" in fields
        assert "salary" in fields

    def test_get_max_depth(self):
        assert self.rbac.get_max_depth("admin") == 10
        assert self.rbac.get_max_depth("viewer") == 1

    def test_get_rate_limit(self):
        assert self.rbac.get_rate_limit("analyst") == 60

    def test_list_roles(self):
        roles = self.rbac.list_roles()
        assert "admin" in roles
        assert "analyst" in roles
        assert "viewer" in roles
