# Tutorial: Differential Privacy

The `DifferentialPrivacyEngine` adds Laplace noise to numeric query results to prevent reconstruction of exact values. Each query consumes epsilon from a per-user budget.

## Code Example

```python
from fhamesh.datacore.privacy import DifferentialPrivacyEngine

engine = DifferentialPrivacyEngine(config={
    "default_epsilon": 1.0,
    "max_budget_per_user": 10.0,
    "field_sensitivity": {"salary": 50000.0},
})

# Simulate an aggregate query result
original = {"value": 120333.33, "table": "employees"}
print(f"Original average salary: ${original['value']:,.2f}")
print()

# Apply noise 5 times — each run is different
print("5 noised results (epsilon=1.0, sensitivity=50000):")
for i in range(5):
    noisy, eps = engine.apply(original, {"epsilon": 1.0})
    diff = noisy["value"] - original["value"]
    print(f"  Run {i+1}: ${noisy['value']:>12,.2f}  "
          f"(noise: {'+' if diff >= 0 else ''}{diff:,.2f}, "
          f"epsilon consumed: {eps})")
```

## Expected Output

```
Original average salary: $120,333.33

5 noised results (epsilon=1.0, sensitivity=50000):
  Run 1: $ 140,059.73  (noise: +19,726.40, epsilon consumed: 1.0)
  Run 2: $ 174,805.74  (noise: +54,472.41, epsilon consumed: 1.0)
  Run 3: $ 102,512.35  (noise: -17,820.98, epsilon consumed: 1.0)
  Run 4: $  45,844.45  (noise: -74,488.88, epsilon consumed: 1.0)
  Run 5: $  90,995.73  (noise: -29,337.60, epsilon consumed: 1.0)
```

!!! note "Random noise"
    The exact values will differ on each run because the noise is drawn randomly from a Laplace distribution.

## Explanation

The noise is drawn from `Laplace(0, sensitivity / epsilon)`. With sensitivity=50,000 and epsilon=1.0, the scale is 50,000. This means values will typically deviate by tens of thousands of dollars from the true average.

**Key parameters**:

- **sensitivity** (50,000): The maximum change one individual record can cause in the aggregate result. For salary queries, one person's salary can be at most $50,000 different from the mean.
- **epsilon** (1.0): The privacy budget for this query. Lower epsilon means more noise (stronger privacy). Higher epsilon means less noise (weaker privacy).
- **budget** (10.0): The total epsilon a user can consume. After 10 queries at epsilon=1.0, further queries are denied.

**Why it matters**: Even if an attacker can query the system repeatedly, they cannot reconstruct the exact original value because:

1. Each response has different random noise
2. Their budget runs out after a fixed number of queries

!!! warning "Budget exhaustion"
    After `max_budget_per_user` (10.0) epsilon is consumed, the engine will deny further queries for that user until the budget resets (configurable via `budget_reset_interval_hours` in `config/privacy.yaml`).
