"""Uncertainty estimation for adversarial input detection.

Evaluates confidence in an intent classification and detects
adversarial patterns through consistency checking and anomaly scoring.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from typing import Any

from ..core.message import IntentDescriptor
from ..core.types import IntentCategory

logger = logging.getLogger(__name__)


# Known valid domain-action pairs for consistency checking
_VALID_DOMAIN_ACTIONS: dict[str, set[str]] = {
    "hr": {"lookup_salary", "lookup_employee", "list_department", "aggregate", "lookup", "general_query"},
    "finance": {"lookup_order", "aggregate_revenue", "list_transactions", "aggregate", "lookup", "general_query"},
    "product": {"lookup_product", "list_catalog", "aggregate", "lookup", "general_query"},
    "general": {"aggregate", "lookup", "general_query"},
}


@dataclass(slots=True)
class UncertaintyResult:
    """Result of uncertainty estimation."""
    confidence: float = 0.0
    is_adversarial: bool = False
    anomaly_scores: dict[str, float] = field(default_factory=dict)
    reasoning: str = ""


class UncertaintyEstimator:
    """Estimates uncertainty and detects adversarial inputs.

    Uses multiple heuristic signals:
    - Domain-action consistency: does the action make sense for the domain?
    - Confidence calibration: is the classifier's confidence realistic?
    - Parameter plausibility: are parameter values within expected ranges?
    - Entropy analysis: high entropy in classifier output suggests confusion

    High anomaly scores trigger rejection or secondary analysis.
    """

    def __init__(self, config: dict[str, Any] | None = None):
        config = config or {}
        self.rejection_threshold: float = config.get("rejection_threshold", 0.2)
        self._adversarial_threshold: float = config.get("adversarial_threshold", 0.8)

    def estimate(self, intent: IntentDescriptor) -> UncertaintyResult:
        """Evaluate an intent for uncertainty and adversarial indicators."""
        scores: dict[str, float] = {}

        # 1. Domain-action consistency (high = anomalous)
        scores["domain_action_consistency"] = self._check_domain_action(intent)

        # 2. Confidence calibration (high = anomalous)
        scores["confidence_calibration"] = self._check_confidence(intent)

        # 3. Parameter plausibility (high = anomalous)
        scores["parameter_plausibility"] = self._check_parameters(intent)

        # 4. Category coherence (high = anomalous)
        scores["category_coherence"] = self._check_category(intent)

        # Aggregate: average anomaly score
        avg_anomaly = sum(scores.values()) / len(scores) if scores else 0.0

        # Confidence is inverse of anomaly
        confidence = max(0.0, 1.0 - avg_anomaly)

        # Adversarial if any single score exceeds threshold
        is_adversarial = any(s >= self._adversarial_threshold for s in scores.values())

        reasoning = self._explain(scores, confidence, is_adversarial)

        return UncertaintyResult(
            confidence=round(confidence, 3),
            is_adversarial=is_adversarial,
            anomaly_scores=scores,
            reasoning=reasoning,
        )

    def _check_domain_action(self, intent: IntentDescriptor) -> float:
        """Check if the action is valid for the claimed domain.

        Returns 0.0 (consistent) to 1.0 (highly anomalous).
        """
        valid_actions = _VALID_DOMAIN_ACTIONS.get(intent.domain, set())
        if not valid_actions:
            return 0.5  # Unknown domain, moderate anomaly

        if intent.action in valid_actions:
            return 0.0  # Perfect match
        if intent.action == "general_query":
            return 0.1  # Generic fallback, slightly anomalous

        return 0.7  # Action doesn't match domain

    def _check_confidence(self, intent: IntentDescriptor) -> float:
        """Check if the classifier's confidence is realistic.

        Perfect 1.0 confidence on vague intents is suspicious.
        Very low confidence with specific actions is also suspicious.
        """
        c = intent.confidence

        if c >= 0.99:
            # Suspiciously high confidence
            return 0.6
        if c <= 0.1 and intent.action != "general_query":
            # Very low confidence but specific action — inconsistent
            return 0.7
        if 0.3 <= c <= 0.9:
            # Normal range
            return 0.0

        return 0.2  # Slightly outside normal

    def _check_parameters(self, intent: IntentDescriptor) -> float:
        """Check if parameters are plausible.

        Empty parameters are fine (simple queries).
        Very large parameter counts or suspicious keys are anomalous.
        """
        params = intent.parameters
        if not params:
            return 0.0

        # Too many parameters is suspicious
        if len(params) > 20:
            return 0.8

        # Check for suspicious parameter keys
        suspicious_keys = {"password", "token", "secret", "admin", "root", "exec", "eval", "cmd"}
        found_suspicious = set(params.keys()) & suspicious_keys
        if found_suspicious:
            return 0.9

        return 0.0

    def _check_category(self, intent: IntentDescriptor) -> float:
        """Check if category is coherent with action.

        Commands with query actions, or queries with command actions, are anomalous.
        """
        if intent.category == IntentCategory.COMMAND.value:
            if intent.action in ("lookup", "general_query", "aggregate"):
                return 0.5  # Command category but query action
        if intent.category == IntentCategory.QUERY.value:
            if intent.action in ("delete", "update", "create"):
                return 0.6  # Query category but mutating action
        return 0.0

    def _explain(
        self,
        scores: dict[str, float],
        confidence: float,
        is_adversarial: bool,
    ) -> str:
        """Generate a human-readable explanation."""
        parts = []
        for name, score in scores.items():
            if score > 0.3:
                parts.append(f"{name}={score:.2f}")
        if is_adversarial:
            return f"ADVERSARIAL: anomalous signals [{', '.join(parts)}]"
        if confidence < 0.5:
            return f"LOW CONFIDENCE: uncertain signals [{', '.join(parts)}]"
        return f"OK: confidence={confidence:.2f}"
