"""Result aggregation for subtree outputs.

Merges results from multiple sub-queries into a single coherent
QueryResult, tracking total privacy budget and all redactions.
"""

from __future__ import annotations

import logging
from typing import Any

from ..core.message import QueryResult

logger = logging.getLogger(__name__)


class ResultAggregator:
    """Merges sub-query results into a unified QueryResult.

    Strategies:
    - Data: merge dicts (key collision = last wins)
    - Privacy budget: sum across sub-results
    - Redacted fields: union of all redacted field lists
    - Noise: True if any sub-result had noise applied
    - Success: True only if all sub-results succeeded
    """

    def aggregate(self, results: list[QueryResult]) -> QueryResult:
        """Merge a list of sub-query results."""
        if not results:
            return QueryResult(success=False, error_message="No results to aggregate")

        if len(results) == 1:
            return results[0]

        merged_data: dict[str, Any] = {}
        total_budget = 0.0
        all_redacted: list[str] = []
        any_noise = False
        all_success = True
        errors: list[str] = []

        for i, r in enumerate(results):
            if r.success:
                # Namespace sub-results to avoid key collision
                if len(results) > 1:
                    for key, value in r.data.items():
                        merged_key = f"sub_{i}_{key}" if key in merged_data else key
                        merged_data[merged_key] = value
                else:
                    merged_data.update(r.data)
            else:
                all_success = False
                if r.error_message:
                    errors.append(f"sub-query {i}: {r.error_message}")

            total_budget += r.privacy_budget_consumed
            all_redacted.extend(r.fields_redacted)
            any_noise = any_noise or r.noise_applied

        error_msg = "; ".join(errors) if errors else ""

        return QueryResult(
            success=all_success,
            data=merged_data,
            privacy_budget_consumed=total_budget,
            fields_redacted=list(set(all_redacted)),
            noise_applied=any_noise,
            error_message=error_msg,
        )
