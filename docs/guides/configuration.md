# Configuration Reference

FHAMESH uses four YAML configuration files in the `config/` directory. All configuration is loaded at startup by `ConfigLoader`.

## Overview

| File | Purpose |
|------|---------|
| `config/default.yaml` | System settings, Redis, security keys, layer parameters, audit |
| `config/policies.yaml` | RBAC roles, permissions, and rate limits |
| `config/privacy.yaml` | Differential privacy parameters and PII masking strategies |
| `config/domains.yaml` | Domain definitions, intent patterns, and table mappings |

## default.yaml

The main configuration file. Contains settings for every layer.

### system

```yaml
system:
  name: "fhamesh"
  log_level: "INFO"
```

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `name` | string | `"fhamesh"` | System name used in logging and agent IDs |
| `log_level` | string | `"INFO"` | Python logging level (DEBUG, INFO, WARNING, ERROR) |

### redis

```yaml
redis:
  url: "redis://localhost:6379"
  session_ttl_seconds: 60
```

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `url` | string | `"redis://localhost:6379"` | Redis connection URL for inter-agent transport |
| `session_ttl_seconds` | int | `60` | Session expiry in Redis |

!!! note "Redis is optional for tests"
    Tests use `fakeredis` and do not require a running Redis instance. The `url` setting is only used by `fhamesh run`, `fhamesh demo`, and `fhamesh interactive`.

### security

```yaml
security:
  token_ttl_seconds: 30
  max_hops: 10
  signing_keys:
    leaf: "change_me_leaf_key_at_least_32_bytes!"
    orchestrator: "change_me_orch_key_at_least_32_bytes!"
    datacore: "change_me_core_key_at_least_32_bytes!"
```

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `token_ttl_seconds` | int | `30` | Default TTL for `ScopedToken` instances |
| `max_hops` | int | `10` | Maximum allowed hops before a message is rejected |
| `signing_keys.leaf` | string | -- | HMAC signing key for the leaf layer |
| `signing_keys.orchestrator` | string | -- | HMAC signing key for the orchestrator layer |
| `signing_keys.datacore` | string | -- | HMAC signing key for the data core layer |

!!! warning "Change the signing keys"
    The default signing keys are placeholders. In production, replace them with cryptographically random strings of at least 32 bytes.

### leaf

```yaml
leaf:
  sanitizer:
    max_length: 2000
  classifier:
    min_confidence: 0.3
  eligibility:
    min_confidence: 0.3
```

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `sanitizer.max_length` | int | `2000` | Maximum allowed input length in characters |
| `classifier.min_confidence` | float | `0.3` | Minimum confidence for a classification to be accepted |
| `eligibility.min_confidence` | float | `0.3` | Minimum confidence for the eligibility gate |

### orchestrator

```yaml
orchestrator:
  validation:
    max_subtree_depth: 5
  uncertainty:
    rejection_threshold: 0.2
    adversarial_threshold: 0.8
  subtree:
    timeout_seconds: 30.0
```

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `validation.max_subtree_depth` | int | `5` | Maximum nesting depth for subtree decomposition |
| `uncertainty.rejection_threshold` | float | `0.2` | Anomaly score below this is accepted |
| `uncertainty.adversarial_threshold` | float | `0.8` | Anomaly score above this is flagged as adversarial |
| `subtree.timeout_seconds` | float | `30.0` | Timeout for subtree execution |

### datacore

```yaml
datacore:
  db_path: "data.db"
  query_validation:
    require_justification: true
    allowed_tables:
      - employees
      - products
      - orders
```

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `db_path` | string | `"data.db"` | Path to the SQLite database file |
| `query_validation.require_justification` | bool | `true` | Whether queries must include a justification field |
| `query_validation.allowed_tables` | list | `[employees, products, orders]` | Tables that can be queried |

### audit

```yaml
audit:
  db_path: "audit.db"
```

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `db_path` | string | `"audit.db"` | Path to the audit trail SQLite database |

---

## policies.yaml

Defines RBAC roles, field-level permissions, and rate limits.

### roles

Each role has:

- `permissions` -- list of resource/action/field tuples
- `max_query_depth` -- maximum subtree nesting for this role
- `rate_limit_per_minute` -- per-role rate limit

```yaml
roles:
  admin:
    permissions:
      - resource: "*"
        action: "*"
    max_query_depth: 10
    rate_limit_per_minute: 1000

  analyst:
    permissions:
      - resource: "employees"
        action: "read"
        fields: [name, department, title, salary]
      - resource: "orders"
        action: "read"
        fields: [order_id, amount, date, customer_name]
    max_query_depth: 3
    rate_limit_per_minute: 60

  viewer:
    permissions:
      - resource: "products"
        action: "read"
        fields: [product_id, name, category, price]
      - resource: "employees"
        action: "read"
        fields: [name, department, title]
    max_query_depth: 1
    rate_limit_per_minute: 30
```

### rate_limits

Global and per-user rate limits:

```yaml
rate_limits:
  global:
    requests_per_minute: 100
    burst: 20
  per_user:
    requests_per_minute: 30
    burst: 10
```

---

## privacy.yaml

Configures differential privacy and PII redaction.

### differential_privacy

```yaml
differential_privacy:
  default_epsilon: 1.0
  max_budget_per_user: 10.0
  budget_reset_interval_hours: 24
  field_sensitivity:
    salary: 50000.0
    age: 1.0
    order_amount: 1000.0
    count: 1.0
```

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `default_epsilon` | float | `1.0` | Default epsilon per query |
| `max_budget_per_user` | float | `10.0` | Total epsilon before queries are denied |
| `budget_reset_interval_hours` | int | `24` | Hours before budget resets |
| `field_sensitivity.<field>` | float | varies | Sensitivity (max impact of one record) per field |

### pii

```yaml
pii:
  mask_fields:
    ssn: "last4"
    email: "email_domain"
    phone: "full"
  detect_patterns: true
```

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `mask_fields.<field>` | string | varies | Masking strategy: `full`, `last4`, or `email_domain` |
| `detect_patterns` | bool | `true` | Whether to scan all string fields for PII patterns |

---

## domains.yaml

Defines the business domains the mesh can route to.

```yaml
domains:
  hr:
    description: "Human Resources queries"
    intent_patterns:
      - "salary|compensation|employee|hiring|department|staff|team|manager"
    orchestrator_domain: "hr"
    datacore_tables:
      - employees

  finance:
    description: "Financial queries"
    intent_patterns:
      - "order|revenue|expense|budget|transaction|payment|invoice|cost"
    orchestrator_domain: "finance"
    datacore_tables:
      - orders

  product:
    description: "Product catalog queries"
    intent_patterns:
      - "product|catalog|item|inventory|stock|price|category"
    orchestrator_domain: "product"
    datacore_tables:
      - products

  general:
    description: "General queries — fallback domain"
    intent_patterns:
      - ".*"
    orchestrator_domain: "general"
    datacore_tables:
      - employees
      - products
      - orders
```

Each domain has:

| Key | Type | Description |
|-----|------|-------------|
| `description` | string | Human-readable description of the domain |
| `intent_patterns` | list[string] | Regex patterns for matching user input to this domain |
| `orchestrator_domain` | string | Name used when routing to orchestrator agents |
| `datacore_tables` | list[string] | Tables this domain is allowed to query |

!!! tip "Pattern evaluation order"
    Domains are evaluated in definition order. The `general` domain uses `".*"` (match anything) and should always be listed last as a fallback.
