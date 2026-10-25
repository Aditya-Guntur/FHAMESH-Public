# Tutorial: Row-Level Security

`RowLevelSecurity` builds an `RLSContext` that gets injected into every database query as WHERE predicates. Different roles see different rows from the same table.

## Code Example

```python
from fhamesh.datacore.rls import RowLevelSecurity

rls = RowLevelSecurity()

for role in ["admin", "viewer", "engineering_lead"]:
    ctx = rls.build_context_for_table(
        table="employees",
        auth_token_raw="",
        user_id=f"{role}_user",
        role=role,
    )
    print(f"Role: {role:20s} Predicates: {ctx.predicates}")
```

## Expected Output

```
Role: admin                Predicates: {}
Role: viewer               Predicates: {}
Role: engineering_lead     Predicates: {'department': 'engineering'}
```

## Explanation

**Admin**: No predicates are applied. The admin role sees all rows in the table.

**Viewer**: No row-level predicates are applied. The viewer role is restricted at the field level by RBAC (it cannot see the `salary` column), but it has no row-level restrictions.

**Engineering lead**: A `department = 'engineering'` predicate is injected. This role only sees rows where the department is "engineering". All other rows are invisible.

These predicates are merged into the SQL WHERE clause automatically by the `SQLiteBackend`. For example, an engineering lead querying the employees table would get:

```sql
SELECT name, department, salary
FROM employees
WHERE department = 'engineering'
```

!!! tip "RLS + RBAC work together"
    Row-level security controls *which rows* a role can see. RBAC controls *which fields* a role can see. Together, they provide fine-grained access control at both the row and column level.
