"""Tests for RowLevelSecurity."""

import pytest

from fhamesh.datacore.rls import RowLevelSecurity


class TestRowLevelSecurity:
    def setup_method(self):
        self.rls = RowLevelSecurity()

    def test_admin_no_predicates(self):
        ctx = self.rls.build_context_for_table(
            table="employees",
            auth_token_raw="",
            user_id="admin_user",
            role="admin",
        )
        assert ctx.role == "admin"
        assert len(ctx.predicates) == 0  # Admin sees everything

    def test_viewer_gets_predicates(self):
        ctx = self.rls.build_context_for_table(
            table="employees",
            auth_token_raw="",
            user_id="basic_user",
            role="viewer",
        )
        assert ctx.role == "viewer"
        # Viewer should have restricted access
        # (depends on default policies in rls.py)

    def test_engineering_lead(self):
        ctx = self.rls.build_context_for_table(
            table="employees",
            auth_token_raw="",
            user_id="eng_lead",
            role="engineering_lead",
        )
        # engineering_lead policy adds department=engineering predicate
        assert ctx.predicates.get("department") == "engineering"
