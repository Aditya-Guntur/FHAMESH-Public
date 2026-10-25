# Privacy & PII

FHAMESH provides two privacy mechanisms in the data core layer: differential privacy (adding noise to numeric results) and PII detection/redaction (masking sensitive fields).

## Differential Privacy

### How It Works

The `DifferentialPrivacyEngine` adds Laplace noise to numeric query results. This prevents attackers from reconstructing exact values even if they can issue repeated queries.

The noise is drawn from a Laplace distribution:

```
noise ~ Laplace(0, sensitivity / epsilon)
```

Where:

- **sensitivity** -- the maximum change one individual record can cause in the query result
- **epsilon** -- the privacy budget for this query (lower epsilon = more noise = stronger privacy)

### Configuration

Differential privacy parameters are defined in `config/privacy.yaml`:

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

| Parameter | Description |
|-----------|-------------|
| `default_epsilon` | Epsilon value used when not specified per-query |
| `max_budget_per_user` | Total epsilon budget per user before queries are denied |
| `budget_reset_interval_hours` | Hours before the per-user budget resets |
| `field_sensitivity` | Maximum change one record can cause, per field |

### Epsilon Budget

Every query consumes epsilon from the user's budget. When the budget is exhausted, further queries are denied until the reset interval passes.

For example, with `max_budget_per_user: 10.0` and `default_epsilon: 1.0`, a user can make 10 queries before being blocked.

!!! warning "Budget exhaustion"
    The budget mechanism prevents attackers from averaging out the noise over many queries. Without it, an attacker could issue thousands of identical queries and compute the mean to recover the true value.

### Noise Scale

The noise scale for a field is `sensitivity / epsilon`. For the salary field with sensitivity 50,000 and epsilon 1.0:

```
scale = 50000 / 1.0 = 50000
```

This means each noised salary value will differ from the true value by roughly +/- 50,000 on average. Higher epsilon (e.g., 5.0) reduces the noise scale to 10,000.

## PII Detection & Redaction

### Detection Patterns

The `PIISanitizer` scans every field in query results using 5 regex patterns:

| Pattern | Matches | Example |
|---------|---------|---------|
| Email | `user@domain.com` format | `alice@company.com` |
| Phone | Common phone number formats | `555-123-4567` |
| SSN | Social Security number format | `123-45-6789` |
| Credit Card | 13-19 digit card numbers | `4111111111111111` |
| IP Address | IPv4 addresses | `192.168.1.1` |

### Masking Strategies

Three masking strategies are available:

#### `full`

Replaces the entire value with `[REDACTED]`. Used for phone numbers by default.

```
555-123-4567  -->  [REDACTED]
```

#### `last4`

Keeps the last 4 characters, replaces the rest with `***`. Used for SSNs by default.

```
123-45-6789  -->  ***6789
```

#### `email_domain`

Hides the local part, keeps the domain. Used for email addresses by default.

```
alice@company.com  -->  ***@company.com
```

### Configuration

PII masking strategies are defined in `config/privacy.yaml`:

```yaml
pii:
  mask_fields:
    ssn: "last4"
    email: "email_domain"
    phone: "full"
  detect_patterns: true
```

When `detect_patterns` is `true`, the sanitizer scans all string fields for PII patterns, even if the field name is not in `mask_fields`. This catches PII in unexpected places (e.g., a "notes" field containing a phone number).

!!! tip "Non-PII fields pass through"
    Fields like `name`, `department`, and `salary` (numeric) are not affected by PII redaction. Only string fields matching PII patterns are masked.

### Pipeline Position

PII redaction is the last step in the data core pipeline, applied after storage queries and differential privacy:

```
SQLiteBackend (execute query)
       |
DifferentialPrivacyEngine (add noise to numeric fields)
       |
PIISanitizer (mask PII in string fields)
       |
QueryResult returned
```

This ordering ensures that:

1. Numeric fields get noise added first (before PII scanning, which only affects strings)
2. PII is the last thing removed, so no downstream component can accidentally re-expose it
