# RBAC (Role-Based Access Control)

FHAMESH enforces field-level access control through the `RBACEnforcer`. Roles, permissions, and rate limits are defined in `config/policies.yaml`.

## Permission Model

Each permission grants a role access to specific fields on a specific resource for a specific action:

```python
Permission(
    resource="employees",   # table or resource name
    action="read",          # allowed action
    fields=("name", "department", "salary"),  # allowed fields
)
```

A role is a named collection of permissions:

```python
Role(
    name="analyst",
    permissions=(
        Permission(resource="employees", action="read",
                   fields=("name", "department", "salary")),
        Permission(resource="products", action="read",
                   fields=("name", "price", "category")),
    ),
)
```

## Deny by Default

If a role does not have an explicit permission for a resource/action/field combination, access is denied. There is no "allow unless denied" logic.

```python
rbac.check("viewer", "employees", "read", ["salary"])
# False -- viewer has no permission for the salary field

rbac.check("analyst", "employees", "write", ["name"])
# False -- analyst has no write permission
```

## Wildcard Access

The admin role uses wildcards (`*`) for both resource and action, granting unrestricted access:

```python
Role(
    name="admin",
    permissions=(
        Permission(resource="*", action="*", fields=()),
    ),
)
```

When `resource="*"` and `action="*"`, the RBAC enforcer allows access to any resource, action, and field combination. The empty `fields` tuple is ignored for wildcard permissions.

## Built-in Roles

Three roles are defined in `config/policies.yaml`:

### admin

Full access to everything. No field restrictions. Max query depth of 10. Rate limit of 1000 requests per minute.

```yaml
admin:
  permissions:
    - resource: "*"
      action: "*"
  max_query_depth: 10
  rate_limit_per_minute: 1000
```

### analyst

Read access to employee and order data with specific fields. Max query depth of 3. Rate limit of 60 requests per minute.

```yaml
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
```

### viewer

Read access to product data and limited employee data (no salary). Max query depth of 1. Rate limit of 30 requests per minute.

```yaml
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

!!! note "Field-level granularity"
    Notice that the `analyst` role can read `salary` from the `employees` table, but the `viewer` role cannot. This is field-level access control -- two roles can have read access to the same table but see different columns.

## Rate Limits

Rate limits are enforced at two levels:

### Global Rate Limits

Applied across all users:

```yaml
rate_limits:
  global:
    requests_per_minute: 100
    burst: 20
```

### Per-User Rate Limits

Applied per authenticated user:

```yaml
rate_limits:
  per_user:
    requests_per_minute: 30
    burst: 10
```

### Per-Role Rate Limits

Each role also has its own `rate_limit_per_minute` defined alongside its permissions.

When any rate limit is exceeded, the `PolicyEngine` returns a `DENY` verdict and the request is rejected.

## How RBAC Fits in the Pipeline

The `RBACEnforcer` is called by the `PolicyEngine` in the orchestrator layer, after credential verification and uncertainty estimation:

```
CredentialVerifier (token valid?)
        |
UncertaintyEstimator (adversarial?)
        |
PolicyEngine
   +-- RBACEnforcer (field-level access?)
   +-- Rate Limiter (within limits?)
        |
   PolicyAttestation signed and attached
```

Only after all checks pass does the query proceed to the data core layer.
