"""Tests for DifferentialPrivacyEngine."""

import pytest

from fhamesh.datacore.privacy import DifferentialPrivacyEngine


class TestDifferentialPrivacyEngine:
    def setup_method(self):
        self.engine = DifferentialPrivacyEngine({
            "default_epsilon": 1.0,
            "max_budget_per_user": 10.0,
            "field_sensitivity": {
                "salary": 50000.0,
                "age": 1.0,
                "price": 5000.0,
                "count": 1.0,
            },
        })

    def test_apply_noise_to_aggregate(self):
        data = {"value": 75000.0, "table": "employees"}
        query = {"epsilon": 1.0}
        noisy, eps = self.engine.apply(data, query)
        assert noisy.get("noise_applied") is True
        assert eps > 0

    def test_apply_noise_to_rows(self):
        data = {
            "rows": [
                {"name": "Alice", "salary": 80000},
                {"name": "Bob", "salary": 70000},
            ],
        }
        query = {"epsilon": 1.0}
        noisy, eps = self.engine.apply(data, query)
        rows = noisy["rows"]
        original_salaries = [80000, 70000]
        noisy_salaries = [r["salary"] for r in rows]
        assert noisy_salaries != original_salaries
        assert eps > 0

    def test_no_noise_on_non_numeric(self):
        data = {
            "rows": [
                {"name": "Alice", "department": "Engineering"},
            ],
        }
        query = {}
        noisy, eps = self.engine.apply(data, query)
        assert noisy["rows"][0]["name"] == "Alice"
        assert eps == 0.0

    def test_epsilon_zero_no_noise(self):
        data = {"value": 100.0, "table": "employees"}
        query = {"epsilon": 0.0}
        noisy, eps = self.engine.apply(data, query)
        assert noisy["value"] == 100.0
        assert eps == 0.0

    @pytest.mark.asyncio
    async def test_budget_check_without_redis(self):
        ok = await self.engine.check_budget("user1")
        assert ok is True

    @pytest.mark.asyncio
    async def test_budget_tracking_with_redis(self, redis_client):
        self.engine.set_redis(redis_client)
        ok = await self.engine.check_budget("user1")
        assert ok is True

        await self.engine.deduct_budget("user1", 5.0)
        remaining = await self.engine.remaining_budget("user1")
        assert remaining == 5.0

    @pytest.mark.asyncio
    async def test_budget_exhaustion(self, redis_client):
        self.engine.set_redis(redis_client)
        await self.engine.deduct_budget("user2", 10.0)
        ok = await self.engine.check_budget("user2")
        assert ok is False
