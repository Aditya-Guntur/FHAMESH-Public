"""Tests for DynamicSchemaRegistry — runtime domain registration."""

import pytest

fakeredis = pytest.importorskip("fakeredis")

from fhamesh.orchestrator.schema_registry import DynamicSchemaRegistry


class TestDynamicSchemaRegistry:
    def test_known_domains_without_registration_matches_base(self):
        registry = DynamicSchemaRegistry()
        assert registry.known_domains() == ["finance", "hr", "product"]

    async def test_register_domain_in_memory_only(self):
        registry = DynamicSchemaRegistry()  # no redis attached
        await registry.register_domain("marketing", "campaigns", {"list_campaigns": ["name", "budget"]})

        assert "marketing" in registry.known_domains()
        assert registry.resolve_table("marketing") == "campaigns"
        assert registry.resolve_fields("marketing", "list_campaigns") == ["name", "budget"]

    async def test_unregistered_domain_falls_back_to_base_schema(self):
        registry = DynamicSchemaRegistry()
        assert registry.resolve_table("hr") == "employees"

    async def test_explicit_table_overrides_dynamic_registration(self):
        registry = DynamicSchemaRegistry()
        await registry.register_domain("marketing", "campaigns", {"list_campaigns": ["name"]})
        assert registry.resolve_table("marketing", explicit="custom_table") == "custom_table"

    async def test_describe_unknown_domain(self):
        registry = DynamicSchemaRegistry()
        description = registry.describe_domain("nonexistent")
        assert "Unknown domain" in description
        assert "hr" in description  # lists known domains as a hint

    async def test_redis_persists_and_shares_registrations(self):
        import fakeredis.aioredis as fakeredis_aio

        redis_client = fakeredis_aio.FakeRedis()

        first = DynamicSchemaRegistry()
        first.set_redis(redis_client)
        await first.load()
        await first.register_domain("marketing", "campaigns", {"list_campaigns": ["name", "budget"]})

        # A second registry instance (simulating a different orchestrator
        # process) sharing the same Redis should see the registration too.
        second = DynamicSchemaRegistry()
        second.set_redis(redis_client)
        await second.load()

        assert "marketing" in second.known_domains()
        assert second.resolve_table("marketing") == "campaigns"

    async def test_load_without_redis_is_a_noop(self):
        registry = DynamicSchemaRegistry()
        await registry.load()  # should not raise
        assert registry.known_domains() == ["finance", "hr", "product"]
