"""Integration test: DataCore pipeline.

Tests the full DataCore pipeline: query validation -> RLS -> storage
-> differential privacy -> PII sanitization.
"""

import pytest

from fhamesh.datacore.pii import PIISanitizer
from fhamesh.datacore.privacy import DifferentialPrivacyEngine
from fhamesh.datacore.query_validator import QueryValidator
from fhamesh.datacore.rls import RowLevelSecurity
from fhamesh.datacore.storage import RLSContext, SQLiteBackend


@pytest.mark.asyncio
class TestDataCorePipeline:
    """Test the full DataCore processing pipeline end-to-end."""

    async def test_full_pipeline_admin_query(self):
        """Admin queries employees — no RLS restrictions, noise applied, PII redacted."""
        # Setup
        backend = SQLiteBackend(":memory:")
        await backend.initialize()
        rls = RowLevelSecurity()
        privacy = DifferentialPrivacyEngine({"default_epsilon": 1.0, "field_sensitivity": {"salary": 50000.0}})
        pii = PIISanitizer()

        # Step 1: Build RLS context
        rls_ctx = rls.build_context_for_table(
            table="employees",
            user_id="admin_user",
            role="admin",
        )
        assert len(rls_ctx.predicates) == 0  # Admin has no restrictions

        # Step 2: Execute query
        query = {"table": "employees", "fields": ["name", "email", "salary"], "filters": {}}
        raw_results = await backend.execute(query, rls_ctx)
        assert len(raw_results["rows"]) == 15  # All 15 seed employees

        # Step 3: Apply privacy noise
        noisy, epsilon = privacy.apply(raw_results, query)
        assert noisy.get("noise_applied") is True
        assert epsilon > 0

        # Step 4: PII sanitization
        sanitized, redacted = pii.sanitize(noisy)
        assert "email" in redacted  # Email should be redacted
        for row in sanitized["rows"]:
            assert "***@" in row["email"]  # Email masked to domain only

        await backend.close()

    async def test_engineering_lead_restricted(self):
        """Engineering lead should only see engineering department."""
        backend = SQLiteBackend(":memory:")
        await backend.initialize()
        rls = RowLevelSecurity()

        rls_ctx = rls.build_context_for_table(
            table="employees",
            user_id="eng_lead",
            role="engineering_lead",
        )

        query = {"table": "employees", "fields": ["name", "department"], "filters": {}}
        results = await backend.execute(query, rls_ctx)

        for row in results["rows"]:
            assert row["department"] == "engineering"

        await backend.close()

    async def test_aggregate_with_noise(self):
        """Aggregate query gets Laplace noise applied."""
        backend = SQLiteBackend(":memory:")
        await backend.initialize()
        privacy = DifferentialPrivacyEngine({"default_epsilon": 0.5, "field_sensitivity": {"salary": 50000.0}})

        query = {"table": "employees", "fields": ["salary"], "filters": {}, "aggregate": "AVG"}
        rls_ctx = RLSContext(user_id="test", role="admin")
        raw = await backend.execute(query, rls_ctx)

        noisy, eps = privacy.apply(raw, query)
        assert noisy.get("noise_applied") is True
        assert eps > 0
        # With epsilon=0.5, noise should be noticeable
        # (can't assert exact values due to randomness)
        assert isinstance(noisy["value"], float)

        await backend.close()
