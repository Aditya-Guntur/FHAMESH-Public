"""Differential privacy engine for the Data Core.

Implements the Laplace mechanism with configurable epsilon budgets,
per-user budget tracking in Redis, and noise injection for numeric fields.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

import numpy as np
import redis.asyncio as aioredis

logger = logging.getLogger(__name__)


class DifferentialPrivacyEngine:
    """Real differential privacy using the Laplace mechanism.

    - Configurable epsilon per query
    - Per-user privacy budget tracking (Redis-backed)
    - Laplace noise for numeric fields
    - Budget enforcement: queries denied when budget is spent
    """

    BUDGET_KEY_PREFIX = "fhamesh:privacy_budget:"

    def __init__(self, config: dict[str, Any] | None = None):
        config = config or {}
        self._default_epsilon: float = config.get("default_epsilon", 1.0)
        self._max_budget: float = config.get("max_budget_per_user", 10.0)
        self._sensitivity: dict[str, float] = config.get("field_sensitivity", {
            "salary": 50000.0,
            "age": 1.0,
            "order_amount": 1000.0,
            "amount": 1000.0,
            "price": 5000.0,
            "count": 1.0,
        })
        self._budget_reset_hours: int = config.get("budget_reset_interval_hours", 24)
        self._redis: aioredis.Redis | None = None

    def set_redis(self, redis_client: aioredis.Redis) -> None:
        """Inject Redis client for budget tracking."""
        self._redis = redis_client

    async def check_budget(self, user_id: str) -> bool:
        """Check if user has remaining privacy budget."""
        spent = await self._get_spent(user_id)
        return spent < self._max_budget

    async def remaining_budget(self, user_id: str) -> float:
        """Get remaining budget for a user."""
        spent = await self._get_spent(user_id)
        return max(0.0, self._max_budget - spent)

    def apply(
        self,
        data: dict[str, Any],
        query: dict[str, Any],
    ) -> tuple[dict[str, Any], float]:
        """Apply differential privacy noise to query results.

        Returns (noisy_data, total_epsilon_consumed).
        """
        epsilon = query.get("epsilon", self._default_epsilon)
        noisy = dict(data)
        total_epsilon = 0.0

        # Handle aggregate results
        if "value" in data and isinstance(data["value"], (int, float)):
            field_name = "count"
            # Detect which field the aggregate is over
            table = data.get("table", "")
            if table == "employees":
                field_name = "salary"
            elif table == "orders":
                field_name = "amount"
            elif table == "products":
                field_name = "price"

            sensitivity = self._sensitivity.get(field_name, 1.0)
            noise = self._laplace_noise(sensitivity, epsilon)
            noisy["value"] = round(data["value"] + noise, 2)
            noisy["noise_applied"] = True
            total_epsilon += epsilon
            return noisy, total_epsilon

        # Handle row-level results
        rows = data.get("rows", [])
        if rows:
            noisy_rows = []
            for row in rows:
                noisy_row = dict(row)
                for field_name, value in row.items():
                    if isinstance(value, (int, float)) and field_name in self._sensitivity:
                        sensitivity = self._sensitivity[field_name]
                        noise = self._laplace_noise(sensitivity, epsilon)
                        noisy_row[field_name] = round(value + noise, 2)
                        total_epsilon += epsilon
                noisy_rows.append(noisy_row)
            noisy["rows"] = noisy_rows
            noisy["noise_applied"] = True

        return noisy, total_epsilon

    async def deduct_budget(self, user_id: str, epsilon: float) -> None:
        """Record epsilon consumed for this user."""
        if self._redis is None or epsilon <= 0:
            return
        key = f"{self.BUDGET_KEY_PREFIX}{user_id}"
        current = await self._get_spent(user_id)
        new_total = current + epsilon
        ttl = self._budget_reset_hours * 3600
        await self._redis.setex(key, ttl, str(new_total))

    async def _get_spent(self, user_id: str) -> float:
        """Get total epsilon spent by a user."""
        if self._redis is None:
            return 0.0
        key = f"{self.BUDGET_KEY_PREFIX}{user_id}"
        raw = await self._redis.get(key)
        if raw is None:
            return 0.0
        try:
            return float(raw)
        except (ValueError, TypeError):
            return 0.0

    def _laplace_noise(self, sensitivity: float, epsilon: float) -> float:
        """Sample from Laplace(0, sensitivity/epsilon)."""
        if epsilon <= 0:
            return 0.0
        scale = sensitivity / epsilon
        return float(np.random.laplace(0, scale))
