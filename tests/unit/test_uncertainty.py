"""Tests for UncertaintyEstimator."""

import pytest

from fhamesh.core.message import IntentDescriptor
from fhamesh.core.types import IntentCategory
from fhamesh.orchestrator.uncertainty import UncertaintyEstimator


class TestUncertaintyEstimator:
    def setup_method(self):
        self.estimator = UncertaintyEstimator()

    def test_normal_intent_high_confidence(self):
        intent = IntentDescriptor(
            category=IntentCategory.QUERY.value,
            domain="hr",
            action="lookup_salary",
            confidence=0.8,
        )
        result = self.estimator.estimate(intent)
        assert result.confidence > 0.5
        assert result.is_adversarial is False

    def test_suspicious_parameters(self):
        intent = IntentDescriptor(
            category=IntentCategory.QUERY.value,
            domain="hr",
            action="lookup",
            confidence=0.7,
            parameters={"password": "admin123", "exec": "rm -rf"},
        )
        result = self.estimator.estimate(intent)
        assert result.is_adversarial is True

    def test_too_many_parameters(self):
        intent = IntentDescriptor(
            category=IntentCategory.QUERY.value,
            domain="hr",
            action="lookup",
            confidence=0.7,
            parameters={f"param_{i}": i for i in range(25)},
        )
        result = self.estimator.estimate(intent)
        assert result.anomaly_scores["parameter_plausibility"] > 0.7

    def test_perfect_confidence_suspicious(self):
        intent = IntentDescriptor(
            category=IntentCategory.QUERY.value,
            domain="general",
            action="general_query",
            confidence=1.0,
        )
        result = self.estimator.estimate(intent)
        assert result.anomaly_scores["confidence_calibration"] > 0.3

    def test_inconsistent_domain_action(self):
        intent = IntentDescriptor(
            category=IntentCategory.QUERY.value,
            domain="hr",
            action="delete_everything",
            confidence=0.7,
        )
        result = self.estimator.estimate(intent)
        assert result.anomaly_scores["domain_action_consistency"] > 0.5

    def test_result_has_reasoning(self):
        intent = IntentDescriptor(
            category=IntentCategory.QUERY.value,
            domain="hr",
            action="lookup",
            confidence=0.7,
        )
        result = self.estimator.estimate(intent)
        assert isinstance(result.reasoning, str)
        assert len(result.reasoning) > 0
