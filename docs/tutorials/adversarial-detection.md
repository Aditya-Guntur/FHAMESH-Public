# Tutorial: Adversarial Detection

The `UncertaintyEstimator` scores intents across 4 anomaly dimensions to detect adversarial or anomalous inputs before they reach the data layer. Suspicious intents are rejected by the orchestrator.

## Code Example

```python
from fhamesh.core.message import IntentDescriptor
from fhamesh.core.types import IntentCategory
from fhamesh.orchestrator.uncertainty import UncertaintyEstimator

estimator = UncertaintyEstimator()

scenarios = [
    ("Normal salary query", IntentDescriptor(
        category=IntentCategory.QUERY.value, domain="hr",
        action="lookup_salary", confidence=0.85)),

    ("Suspicious params (password + exec)", IntentDescriptor(
        category=IntentCategory.QUERY.value, domain="hr",
        action="lookup", confidence=0.7,
        parameters={"password": "admin123", "exec": "rm -rf"})),

    ("Parameter stuffing (25 params)", IntentDescriptor(
        category=IntentCategory.QUERY.value, domain="hr",
        action="lookup", confidence=0.7,
        parameters={f"param_{i}": i for i in range(25)})),

    ("Inconsistent domain + action", IntentDescriptor(
        category=IntentCategory.QUERY.value, domain="hr",
        action="delete_everything", confidence=0.7)),
]

for label, intent in scenarios:
    result = estimator.estimate(intent)
    scores = {k: round(v, 2)
              for k, v in result.anomaly_scores.items() if v > 0}
    print(f"{label}")
    print(f"  Adversarial: {result.is_adversarial}")
    print(f"  Anomaly scores: {scores or 'none'}")
    print(f"  Reasoning: {result.reasoning}")
    print()
```

## Expected Output

```
Normal salary query
  Adversarial: False
  Anomaly scores: none
  Reasoning: OK: confidence=1.00

Suspicious params (password + exec)
  Adversarial: True
  Anomaly scores: {'parameter_plausibility': 0.9}
  Reasoning: ADVERSARIAL: anomalous signals [parameter_plausibility=0.90]

Parameter stuffing (25 params)
  Adversarial: True
  Anomaly scores: {'parameter_plausibility': 0.8}
  Reasoning: ADVERSARIAL: anomalous signals [parameter_plausibility=0.80]

Inconsistent domain + action
  Adversarial: False
  Anomaly scores: {'domain_action_consistency': 0.7}
  Reasoning: OK: confidence=0.82
```

## Explanation

The estimator evaluates 4 anomaly dimensions:

### parameter_plausibility

Flags suspicious parameter keys and excessive parameter counts.

- Keys like `password`, `exec`, `token`, `secret` get a high anomaly score (0.9)
- More than 20 parameters triggers a score of 0.8 (parameter stuffing attack)
- Normal queries with sensible parameters score 0.0

### domain_action_consistency

Flags mismatched domain-action pairs.

- "hr" domain + "delete_everything" action is unusual (score 0.7)
- "hr" domain + "lookup_salary" action is expected (score 0.0)

### confidence_calibration

Flags unrealistic confidence scores.

- A confidence of exactly 1.0 is suspicious -- real classifiers rarely produce perfect confidence
- Confidence values in the 0.5-0.9 range are typical

### category_coherence

Flags category-action mismatches.

- A "query" category paired with a "delete" action is inconsistent

### Adversarial Threshold

If any anomaly score exceeds the adversarial threshold (default: 0.8, configurable via `orchestrator.uncertainty.adversarial_threshold`), the intent is marked `is_adversarial = True` and rejected before reaching the data layer.

!!! warning "Defense before data access"
    The uncertainty estimator runs in the orchestrator layer, before any data core queries are executed. This means adversarial inputs are caught and rejected before they can access or modify any data.
