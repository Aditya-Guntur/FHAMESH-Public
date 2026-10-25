"""Tests for SQLiteBackend storage layer."""

import pytest

from fhamesh.datacore.storage import RLSContext, SQLiteBackend


@pytest.mark.asyncio
class TestSQLiteBackend:
    async def test_initialize_creates_tables(self):
        backend = SQLiteBackend(":memory:")
        await backend.initialize()
        # Query employees table — should have seed data
        result = await backend.execute(
            {"table": "employees", "fields": ["name"], "filters": {}},
            RLSContext(user_id="test", role="admin"),
        )
        assert "rows" in result
        assert len(result["rows"]) > 0
        await backend.close()

    async def test_query_with_filter(self):
        backend = SQLiteBackend(":memory:")
        await backend.initialize()
        result = await backend.execute(
            {
                "table": "employees",
                "fields": ["name", "department"],
                "filters": {"department": "engineering"},
            },
            RLSContext(user_id="test", role="admin"),
        )
        rows = result["rows"]
        assert all(r["department"] == "engineering" for r in rows)
        await backend.close()

    async def test_aggregate_query(self):
        backend = SQLiteBackend(":memory:")
        await backend.initialize()
        result = await backend.execute(
            {
                "table": "employees",
                "fields": ["salary"],
                "filters": {},
                "aggregate": "AVG",
            },
            RLSContext(user_id="test", role="admin"),
        )
        assert "value" in result
        assert isinstance(result["value"], (int, float))
        assert result["value"] > 0
        await backend.close()

    async def test_rls_predicate_applied(self):
        backend = SQLiteBackend(":memory:")
        await backend.initialize()
        # RLS predicates use dict format {column: value}, merged into WHERE clause
        rls = RLSContext(
            user_id="test",
            role="engineering_lead",
            department="engineering",
            predicates={"department": "engineering"},
        )
        result = await backend.execute(
            {"table": "employees", "fields": ["name", "department"], "filters": {}},
            rls,
        )
        rows = result["rows"]
        assert all(r["department"] == "engineering" for r in rows)
        await backend.close()

    async def test_products_table(self):
        backend = SQLiteBackend(":memory:")
        await backend.initialize()
        result = await backend.execute(
            {"table": "products", "fields": ["name", "price"], "filters": {}},
            RLSContext(user_id="test", role="admin"),
        )
        assert len(result["rows"]) > 0
        await backend.close()

    async def test_orders_table(self):
        backend = SQLiteBackend(":memory:")
        await backend.initialize()
        result = await backend.execute(
            {"table": "orders", "fields": ["customer_name", "amount"], "filters": {}},
            RLSContext(user_id="test", role="admin"),
        )
        assert len(result["rows"]) > 0
        await backend.close()
