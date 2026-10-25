# Tutorial: RBAC Access Control

The `RBACEnforcer` checks field-level permissions for every query. Roles are defined with explicit resource/action/field tuples. Access is denied by default -- if a permission is not explicitly granted, the request is refused.

## Code Example

```python
from fhamesh.security.rbac import RBACEnforcer, Role, Permission

# Define roles with field-level permissions
rbac = RBACEnforcer(roles={
    "admin": Role(
        name="admin",
        permissions=(Permission(resource="*", action="*", fields=()),),
    ),
    "analyst": Role(
        name="analyst",
        permissions=(
            Permission(resource="employees", action="read",
                       fields=("name", "department", "salary")),
            Permission(resource="products", action="read",
                       fields=("name", "price", "category")),
        ),
    ),
    "viewer": Role(
        name="viewer",
        permissions=(
            Permission(resource="employees", action="read",
                       fields=("name", "department")),
        ),
    ),
})

# Admin: full access (wildcard)
print(rbac.check("admin", "employees", "read", ["name", "salary", "ssn"]))
# True — admin has wildcard permissions

# Analyst: can read name, department, salary
print(rbac.check("analyst", "employees", "read", ["name", "salary"]))
# True — fields are within allowed set

# Viewer: can only read name and department
print(rbac.check("viewer", "employees", "read", ["salary"]))
# False — viewer cannot access salary

# Analyst: cannot write
print(rbac.check("analyst", "employees", "write", ["name"]))
# False — no write permission
```

## Expected Output

```
True      <- admin: wildcard access to everything
True      <- analyst: salary is in their allowed fields
False     <- viewer: salary is NOT in their allowed fields
False     <- analyst: no write permission defined
```

## Explanation

**Admin (wildcard)**: The admin role uses `resource="*"` and `action="*"`, which grants unrestricted access to any resource, any action, and any field. The empty `fields=()` tuple is ignored for wildcard permissions.

**Analyst (field-level read)**: The analyst role has read access to `employees` with fields `(name, department, salary)`. Requesting `["name", "salary"]` is a subset of the allowed fields, so access is granted.

**Viewer (restricted fields)**: The viewer role has read access to `employees` but only for `(name, department)`. Requesting `["salary"]` is not in the allowed set, so access is denied.

**Analyst (no write)**: The analyst role only has `action="read"` permissions. There is no `action="write"` permission defined, so write access is denied regardless of the fields requested.

!!! note "Deny by default"
    If a role is not defined, or does not have a matching permission for the requested resource/action/field combination, the `check()` method returns `False`. There is no fallback to "allow" behavior.
