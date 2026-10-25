# Tutorial: PII Redaction

The `PIISanitizer` scans every field in query results for PII patterns (email, phone, SSN, credit card, IP address) and applies masking strategies. Non-PII fields pass through untouched.

## Code Example

```python
from fhamesh.datacore.pii import PIISanitizer

sanitizer = PIISanitizer()

# Employee record with PII
row = {"name": "Alice Johnson", "salary": 125000,
       "email": "alice@company.com",
       "phone": "555-123-4567", "ssn": "123-45-6789"}

sanitized, redacted_fields = sanitizer.sanitize(row)
print("Original:")
for k, v in row.items():
    print(f"  {k}: {v}")
print()
print("After PII redaction:")
for k, v in sanitized.items():
    marker = " <- REDACTED" if k in redacted_fields else ""
    print(f"  {k}: {v}{marker}")
```

## Expected Output

```
Original:
  name: Alice Johnson
  salary: 125000
  email: alice@company.com
  phone: 555-123-4567
  ssn: 123-45-6789

After PII redaction:
  name: Alice Johnson
  salary: 125000
  email: ***@company.com    <- REDACTED (email_domain strategy)
  phone: [REDACTED]         <- REDACTED (full strategy)
  ssn: ***6789              <- REDACTED (last4 strategy)
```

## Explanation

The `sanitize()` method returns a tuple of `(sanitized_row, redacted_fields)`. The sanitized row has PII values replaced according to the masking strategy. The `redacted_fields` set tells you which fields were modified.

### Masking Strategies

| Strategy | What It Does | Example |
|----------|-------------|---------|
| `email_domain` | Hides the local part, keeps the domain | `alice@company.com` becomes `***@company.com` |
| `full` | Complete redaction | `555-123-4567` becomes `[REDACTED]` |
| `last4` | Keeps the last 4 characters | `123-45-6789` becomes `***6789` |

### Which Strategy Is Used

The strategy is determined by the field name, as configured in `config/privacy.yaml`:

```yaml
pii:
  mask_fields:
    ssn: "last4"
    email: "email_domain"
    phone: "full"
```

### Fields That Pass Through

Non-PII fields are not modified:

- `name` -- "Alice Johnson" stays as-is (names are not considered PII by the default patterns)
- `salary` -- numeric values are not scanned for PII patterns

!!! tip "Pattern detection"
    When `detect_patterns: true` is set in `config/privacy.yaml`, the sanitizer also scans all string fields for PII patterns, even if the field name is not explicitly listed in `mask_fields`. This catches PII in unexpected locations like "notes" or "description" fields.
