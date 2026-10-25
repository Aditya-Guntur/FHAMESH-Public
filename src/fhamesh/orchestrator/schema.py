"""Known domain -> table/field schema shared by every query planner.

Extracted out of QueryDecomposer so the LangGraph planner agent (see
fhamesh.agents.decomposer_graph) can ground its proposals in exactly
the same schema the rule-based decomposer uses, instead of letting an
LLM invent table or field names.
"""

from __future__ import annotations

from typing import Any

_DOMAIN_TABLES: dict[str, str] = {
    "hr": "employees",
    "finance": "orders",
    "product": "products",
}

_FIELD_MAP: dict[str, dict[str, list[str]]] = {
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

_PARAM_TO_FILTER: dict[str, str] = {
    "department": "department",
    "dept": "department",
    "customer": "customer_name",
    "category": "category",
    "date_from": "date_from",
    "date_to": "date_to",
}


class DomainSchema:
    """Resolves domain/action to known tables, fields, and filters.

    This is the single source of truth both the rule-based decomposer
    and the LLM planner agent ground their sub-queries in.
    """

    def known_tables(self) -> list[str]:
        return sorted(set(_DOMAIN_TABLES.values()))

    def known_domains(self) -> list[str]:
        return sorted(_DOMAIN_TABLES)

    def resolve_table(self, domain: str, explicit: str | None = None) -> str:
        if explicit:
            return explicit
        return _DOMAIN_TABLES.get(domain, "employees")

    def resolve_fields(self, domain: str, action: str, explicit: list[str] | None = None) -> list[str]:
        if explicit:
            return explicit
        domain_fields = _FIELD_MAP.get(domain, {})
        return domain_fields.get(action, domain_fields.get("aggregate", ["*"]))

    def resolve_filters(self, parameters: dict[str, Any]) -> dict[str, Any]:
        filters: dict[str, Any] = {}
        for param_key, filter_key in _PARAM_TO_FILTER.items():
            if param_key in parameters:
                filters[filter_key] = parameters[param_key]
        return filters

    def as_prompt_context(self) -> str:
        """Render the schema as grounding context for an LLM prompt."""
        lines = ["Known domains, tables, and fields:"]
        for domain, table in sorted(_DOMAIN_TABLES.items()):
            actions = _FIELD_MAP.get(domain, {})
            action_lines = ", ".join(f"{a} -> {fields}" for a, fields in actions.items())
            lines.append(f"- {domain}: table={table}; actions: {action_lines}")
        return "\n".join(lines)
