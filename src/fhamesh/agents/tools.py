"""Tools the reasoning agents can call mid-graph.

Keeping schema lookup and arithmetic as real tool calls — rather than
dumping everything into the system prompt or trusting the model's own
math — is the point: the model decides when it needs information it
doesn't have, calls a deterministic function to get it, and continues
reasoning with the result. New domains registered at runtime (see
DynamicSchemaRegistry) become visible through list_domains /
describe_domain without touching a prompt.
"""

from __future__ import annotations

from typing import Any

from langchain_core.tools import tool

from ..orchestrator.schema_registry import DynamicSchemaRegistry


def build_schema_tools(schema: DynamicSchemaRegistry | Any | None) -> list[Any]:
    """Build the planner's schema-exploration tools, bound to one schema/registry instance."""
    registry = schema if schema is not None else DynamicSchemaRegistry()

    @tool
    def list_domains() -> list[str]:
        """List every known domain (table group) the system can query right now,
        including domains registered at runtime. Call this first if you're not
        sure what domains exist."""
        return registry.known_domains()

    @tool
    def describe_domain(domain: str) -> str:
        """Describe one domain: its table name and the actions/fields available
        on it. Call this before proposing a sub-query for a domain you haven't
        already seen described in this conversation."""
        return registry.describe_domain(domain)

    return [list_domains, describe_domain]


@tool
def compute_percentage_change(old_value: float, new_value: float) -> str:
    """Compute the percentage change from old_value to new_value. Use this
    instead of doing the arithmetic yourself — it's exact, you might not be."""
    if old_value == 0:
        return "undefined (division by zero)"
    pct = ((new_value - old_value) / old_value) * 100
    return f"{pct:+.1f}%"


@tool
def format_currency(amount: float, currency: str = "USD") -> str:
    """Format a numeric amount as a currency string, e.g. 142300.0 -> '$142,300.00'."""
    symbol = {"USD": "$", "EUR": "€", "GBP": "£"}.get(currency.upper(), currency.upper() + " ")
    return f"{symbol}{amount:,.2f}"


def build_synthesis_tools() -> list[Any]:
    """Build the synthesizer's numeric-formatting tools."""
    return [compute_percentage_change, format_currency]
