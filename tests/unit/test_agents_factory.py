"""Tests for the classifier/decomposer/aggregator backend factory."""

import pytest

from fhamesh.agents import factory
from fhamesh.leaf.classifier import IntentClassifier
from fhamesh.orchestrator.aggregator import ResultAggregator
from fhamesh.orchestrator.decomposer import QueryDecomposer


class TestBuildClassifier:
    def test_auto_uses_langgraph_when_available(self):
        clf = factory.build_classifier({"backend": "auto"})
        assert type(clf).__name__ == "LangGraphClassifier"

    def test_forced_regex_skips_langgraph(self):
        clf = factory.build_classifier({"backend": "regex"})
        assert isinstance(clf, IntentClassifier)

    def test_auto_falls_back_to_regex_when_agents_extra_missing(self, monkeypatch):
        monkeypatch.setattr(factory, "AGENTS_AVAILABLE", False)
        clf = factory.build_classifier({"backend": "auto"})
        assert isinstance(clf, IntentClassifier)

    def test_forced_langgraph_raises_when_extra_missing(self, monkeypatch):
        monkeypatch.setattr(factory, "AGENTS_AVAILABLE", False)
        with pytest.raises(RuntimeError, match="classifier"):
            factory.build_classifier({"backend": "langgraph"})


class TestBuildDecomposer:
    def test_auto_uses_langgraph_when_available(self):
        dec = factory.build_decomposer({"backend": "auto"})
        assert type(dec).__name__ == "LangGraphDecomposer"

    def test_forced_rules_skips_langgraph(self):
        dec = factory.build_decomposer({"backend": "rules"})
        assert isinstance(dec, QueryDecomposer)

    def test_auto_falls_back_to_rules_when_agents_extra_missing(self, monkeypatch):
        monkeypatch.setattr(factory, "AGENTS_AVAILABLE", False)
        dec = factory.build_decomposer({"backend": "auto"})
        assert isinstance(dec, QueryDecomposer)


class TestBuildAggregator:
    def test_auto_uses_langgraph_when_available(self):
        agg = factory.build_aggregator({"backend": "auto"})
        assert type(agg).__name__ == "LangGraphAggregator"

    def test_forced_merge_skips_langgraph(self):
        agg = factory.build_aggregator({"backend": "merge"})
        assert isinstance(agg, ResultAggregator)

    def test_auto_falls_back_to_merge_when_agents_extra_missing(self, monkeypatch):
        monkeypatch.setattr(factory, "AGENTS_AVAILABLE", False)
        agg = factory.build_aggregator({"backend": "auto"})
        assert isinstance(agg, ResultAggregator)


class TestAgentsConfigPropagation:
    def test_ollama_settings_reach_the_classifier(self):
        clf = factory.build_classifier(
            {"backend": "auto", "min_confidence": 0.5},
            {"ollama": {"model": "llama3.2", "base_url": "http://127.0.0.1:1", "timeout_seconds": 0.1}},
        )
        # LangGraphClassifier always keeps a regex fallback ready
        assert isinstance(clf._fallback, IntentClassifier)
        assert clf._min_confidence == 0.5
