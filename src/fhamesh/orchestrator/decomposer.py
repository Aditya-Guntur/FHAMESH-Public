"""Query decomposition for complex multi-domain requests.

Breaks down complex intents into sub-queries that can be handled
by individual DataCore nodes or peer orchestrators.
"""

from __future__ import annotations

import abc
import logging
from typing import Any

from ..core.message import IntentDescriptor

logger = logging.getLogger(__name__)


class BaseDecomposer(abc.ABC):
    """Abstract interface for query decomposers.

    Subclass this to plug in any decomposition backend. decompose() is
    async so backends that reason over an LLM (see fhamesh.agents) can
    await a model call without blocking the agent's event loop.
    """

    @abc.abstractmethod
    async def decompose(self, intent: IntentDescriptor) -> list[dict[str, Any]]:
        """Decompose an intent into executable sub-queries."""
        ...


class QueryDecomposer(BaseDecomposer):
    """Decomposes complex intents into executable sub-queries.

    A sub-query is a dict with:
    - table: target data table
    - fields: list of fields to retrieve
    - filters: dict of filter conditions
    - justifications: dict of field -> reason (for DataCore validation)
    - domain: target domain
    - depends_on: list of sub-query indices (for ordering)

    Single-step intents return a list of one sub-query.
    For production, subclass and add ML-based decomposition.
    """

    def __init__(self, config: dict[str, Any] | None = None):
        config = config or {}
        self._decomposition_rules: dict[str, Any] = config.get("rules", {})

    async def decompose(self, intent: IntentDescriptor) -> list[dict[str, Any]]:
        """Decompose an intent into sub-queries."""
        if self._is_simple(intent):
            return [self._to_single_query(intent)]

        return self._apply_rules(intent)

    def _is_simple(self, intent: IntentDescriptor) -> bool:
        """Determine if an intent maps to a single data query."""
        # Multi-domain parameters trigger decomposition
        params = intent.parameters
        if params.get("cross_domain"):
            return False
        if params.get("compare"):
            return False
        if isinstance(params.get("tables"), list) and len(params["tables"]) > 1:
            return False
        return True

    def _to_single_query(self, intent: IntentDescriptor) -> dict[str, Any]:
        """Convert a simple intent to a single sub-query."""
        table = self._resolve_table(intent)
        fields = self._resolve_fields(intent)
        filters = self._resolve_filters(intent)
        justifications = {f: f"Requested via {intent.action} on {intent.domain}" for f in fields}

        return {
            "table": table,
            "fields": fields,
            "filters": filters,
            "justifications": justifications,
            "domain": intent.domain,
            "depends_on": [],
        }

    def _apply_rules(self, intent: IntentDescriptor) -> list[dict[str, Any]]:
        """Apply decomposition rules for complex intents."""
        sub_queries = []
        params = intent.parameters

        # Cross-domain: one sub-query per domain
        if params.get("cross_domain"):
            domains = params.get("domains", [intent.domain])
            for i, domain in enumerate(domains):
                sub_intent = IntentDescriptor(
                    category=intent.category,
                    domain=domain,
                    action=intent.action,
                    confidence=intent.confidence,
                    parameters={k: v for k, v in params.items() if k not in ("cross_domain", "domains")},
                    sanitized=intent.sanitized,
                    eligibility_passed=intent.eligibility_passed,
                )
                sq = self._to_single_query(sub_intent)
                sq["depends_on"] = []
                sub_queries.append(sq)

        # Multi-table comparison
        elif params.get("compare"):
            tables = params.get("tables", [])
            for i, table in enumerate(tables):
                fields = self._resolve_fields(intent)
                filters = self._resolve_filters(intent)
                justifications = {f: f"Comparison query on {table}" for f in fields}
                sub_queries.append({
                    "table": table,
                    "fields": fields,
                    "filters": filters,
                    "justifications": justifications,
                    "domain": intent.domain,
                    "depends_on": [],
                })

        # Multi-table with dependencies
        elif isinstance(params.get("tables"), list):
            for i, table in enumerate(params["tables"]):
                fields = self._resolve_fields(intent)
                filters = self._resolve_filters(intent)
                justifications = {f: f"Multi-table query part {i+1}" for f in fields}
                sub_queries.append({
                    "table": table,
                    "fields": fields,
                    "filters": filters,
                    "justifications": justifications,
                    "domain": intent.domain,
                    "depends_on": list(range(i)) if params.get("sequential") else [],
                })

        if not sub_queries:
            return [self._to_single_query(intent)]

        return sub_queries

    def _resolve_table(self, intent: IntentDescriptor) -> str:
        """Map domain + action to a database table."""
        domain_tables = {
            "hr": "employees",
            "finance": "orders",
            "product": "products",
        }
        # Check explicit parameter first
        if "table" in intent.parameters:
            return intent.parameters["table"]
        return domain_tables.get(intent.domain, "employees")

    def _resolve_fields(self, intent: IntentDescriptor) -> list[str]:
        """Determine which fields to request based on intent."""
        if "fields" in intent.parameters:
            return intent.parameters["fields"]

        # Default fields by domain and action
        field_map = {
            "hr": {
                "lookup_salary": ["name", "department", "salary"],
                "lookup_employee": ["name", "department", "title", "email"],
                "list_department": ["name", "department", "title"],
                "aggregate": ["department", "salary"],
            },
            "finance": {
                "lookup_order": ["order_id", "customer_name", "amount", "date"],
                "aggregate_revenue": ["amount", "date"],
                "list_transactions": ["order_id", "customer_name", "amount", "date"],
                "aggregate": ["amount", "date"],
            },
            "product": {
                "lookup_product": ["product_id", "name", "category", "price"],
                "list_catalog": ["product_id", "name", "category", "price"],
                "aggregate": ["category", "price"],
            },
        }

        domain_fields = field_map.get(intent.domain, {})
        fields = domain_fields.get(intent.action, domain_fields.get("aggregate", ["*"]))
        return fields

    def _resolve_filters(self, intent: IntentDescriptor) -> dict[str, Any]:
        """Extract filter conditions from intent parameters."""
        filters = {}
        param_to_filter = {
            "department": "department",
            "dept": "department",
            "customer": "customer_name",
            "category": "category",
            "date_from": "date_from",
            "date_to": "date_to",
        }
        for param_key, filter_key in param_to_filter.items():
            if param_key in intent.parameters:
                filters[filter_key] = intent.parameters[param_key]
        return filters
