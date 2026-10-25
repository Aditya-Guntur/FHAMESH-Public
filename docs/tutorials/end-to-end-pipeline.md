# Tutorial: End-to-End Pipeline

This tutorial walks through a complete query flowing through all three layers of the FHAMESH mesh: leaf, orchestrator, and data core. This is the sequence exercised by the end-to-end test suite in `tests/e2e/test_full_pipeline.py`.

## Step 1: Leaf Layer -- Sanitize + Classify + Route

The user submits a natural language query. The leaf layer sanitizes, classifies, and routes it.

```
User input: "Show me employee salaries in engineering"

  +-- InputSanitizer -----------------------------------------------+
  |  16 regex patterns checked                                      |
  |  Result: safe=True                                              |
  |  Content hash logged to audit trail                             |
  +----------------------------------------------- ----------------+
          |
  +-- IntentClassifier ---------------------------------------------+
  |  Domain:     hr                                                 |
  |  Category:   navigation                                         |
  |  Action:     lookup_salary                                      |
  |  Confidence: 0.7                                                |
  +-----------------------------------------------------------------+
          |
  +-- EligibilityGate ----------------------------------------------+
  |  User authenticated? Yes                                        |
  |  Domain valid?       Yes                                        |
  |  Action allowed?     Yes                                        |
  +-----------------------------------------------------------------+
          |
      TokenMinter mints ScopedToken(layer=orchestrator, actions=[query])
      MessageEnvelope forwarded to orchestrator channel
```

The sanitizer verifies the input is clean. The classifier identifies this as an HR domain query about salaries. The eligibility gate confirms the user is authorized. A `ScopedToken` is minted and attached to the `MessageEnvelope`.

## Step 2: Orchestrator Layer -- Validate + Uncertainty + Policy

The orchestrator receives the message and runs credential verification, uncertainty estimation, and policy enforcement.

```
  +-- CredentialVerifier -------------------------------------------+
  |  1. Layer "orchestrator" -- known key? Yes                      |
  |  2. HMAC signature valid?              Yes                      |
  |  3. Token expired?                     No                       |
  |  4. Action "query" in allowed_actions? Yes                      |
  |  5. Target matches?                    Yes                      |
  |  Verdict: ALLOW                                                 |
  +-----------------------------------------------------------------+
          |
  +-- UncertaintyEstimator ----------------------------------------+
  |  parameter_plausibility:    0.0                                 |
  |  domain_action_consistency: 0.0                                 |
  |  confidence_calibration:    0.0                                 |
  |  is_adversarial: False                                          |
  +-----------------------------------------------------------------+
          |
  +-- PolicyEngine -------------------------------------------------+
  |  RBAC check: analyst can read salary? Yes                       |
  |  Rate limit: 3/60 requests used                                 |
  |  PolicyAttestation signed and attached                          |
  +-----------------------------------------------------------------+
          |
      New ScopedToken(layer=datacore, actions=[read])
      Structured query forwarded to datacore
```

The credential verifier passes all 5 steps. The uncertainty estimator finds no anomalies. The policy engine confirms the analyst role has read access to the salary field and the rate limit is not exceeded. A new `ScopedToken` is minted for the data core layer.

## Step 3: Data Core Layer -- RLS + Execute + Privacy + PII

The data core receives the structured query, applies row-level security, executes it, adds differential privacy noise, and redacts PII.

```
  +-- RowLevelSecurity --------------------------------------------+
  |  Role: analyst -- no row predicates                             |
  |  (If engineering_lead -- department=engineering)                |
  +----------------------------------------------------------------+
          |
  +-- SQLiteBackend -----------------------------------------------+
  |  SELECT name, department, salary                                |
  |  FROM employees                                                 |
  |  WHERE department = 'engineering'                               |
  |  -- 7 rows returned                                             |
  +----------------------------------------------------------------+
          |
  +-- DifferentialPrivacyEngine -----------------------------------+
  |  salary field: sensitivity=50000, epsilon=1.0                   |
  |  Laplace noise added to each salary value                       |
  |  Budget deducted: 7.0 epsilon (1.0 per row)                    |
  +----------------------------------------------------------------+
          |
  +-- PIISanitizer ------------------------------------------------+
  |  email fields: ***@company.com                                  |
  |  phone fields: [REDACTED]                                       |
  |  ssn fields:   ***6789                                          |
  |  salary, name, department: untouched                            |
  +----------------------------------------------------------------+
          |
      QueryResult returned through orchestrator -> leaf -> user
```

## What the User Receives

The final result has noised salary values and redacted PII:

```python
QueryResult(
    rows=[
        {"name": "Alice Johnson",  "department": "engineering",
         "salary": 141726.40},
        {"name": "Bob Smith",      "department": "engineering",
         "salary": 109527.59},
        {"name": "Carol Davis",    "department": "engineering",
         "salary": 207820.98},
        {"name": "Diana Lee",      "department": "engineering",
         "salary": 179488.88},
        {"name": "Ivan Chen",      "department": "engineering",
         "salary":  85662.40},
        {"name": "Kevin Patel",    "department": "engineering",
         "salary": 114337.60},
        {"name": "Nina Anderson",  "department": "engineering",
         "salary":  57472.41},
    ],
    metadata={
        "table": "employees",
        "filters_applied": {"department": "engineering"},
        "noise_applied": True,
        "pii_redacted": ["email"],
    },
)
```

!!! note "Noised values"
    The salary values shown above are examples with Laplace noise applied. Actual values will differ on each run due to random noise generation.

## Security Properties

This single query passed through all 8 security components:

1. **InputSanitizer** -- verified no injection attacks
2. **TokenMinter** -- created a scoped, signed credential
3. **CredentialVerifier** -- validated the credential with 5 checks
4. **UncertaintyEstimator** -- confirmed no adversarial signals
5. **PolicyEngine** -- enforced RBAC and rate limits
6. **RowLevelSecurity** -- applied row predicates (if applicable)
7. **DifferentialPrivacyEngine** -- added noise to salary values
8. **PIISanitizer** -- redacted email, phone, and SSN fields

The original exact salaries were never exposed. The audit trail records content hashes at every hop -- never raw data.

## Running It Yourself

```bash
pip install -e ".[dev]"
pytest tests/e2e/test_full_pipeline.py -v
```

The end-to-end test suite exercises this exact flow and verifies all security properties hold.
