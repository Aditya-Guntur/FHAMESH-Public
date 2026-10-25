# Tutorial: Storage & Queries

The `SQLiteBackend` is the default storage backend. It ships with seed data (15 employees, 8 products, 10 orders) and supports row queries, aggregate queries, and RLS predicate injection.

## Code Example

```python
import asyncio
from fhamesh.datacore.storage import SQLiteBackend, RLSContext

async def main():
    backend = SQLiteBackend(":memory:")
    await backend.initialize()

    # Admin sees all 15 employees
    result = await backend.execute(
        {"table": "employees", "fields": ["name", "department", "salary"],
         "filters": {}},
        RLSContext(user_id="admin", role="admin"),
    )
    print(f"Admin sees {len(result['rows'])} employees:")
    for row in result["rows"]:
        print(f"  {row['name']:20s} {row['department']:15s} "
              f"${row['salary']:>10,.2f}")

    # Engineering lead — RLS filters to engineering only
    print()
    result = await backend.execute(
        {"table": "employees", "fields": ["name", "department", "salary"],
         "filters": {}},
        RLSContext(user_id="eng", role="engineering_lead",
                   department="engineering",
                   predicates={"department": "engineering"}),
    )
    print(f"Engineering lead sees {len(result['rows'])} employees:")
    for row in result["rows"]:
        print(f"  {row['name']:20s} {row['department']:15s} "
              f"${row['salary']:>10,.2f}")

    # Aggregate: average salary
    print()
    result = await backend.execute(
        {"table": "employees", "fields": ["salary"], "filters": {},
         "aggregate": "AVG"},
        RLSContext(user_id="analyst", role="analyst"),
    )
    print(f"Average salary: ${result['value']:,.2f}")

    await backend.close()

asyncio.run(main())
```

## Expected Output

```
Admin sees 15 employees:
  Alice Johnson        engineering     $125,000.00
  Bob Smith            engineering     $155,000.00
  Carol Davis          engineering     $195,000.00
  Diana Lee            engineering     $105,000.00
  Ethan Brown          hr              $140,000.00
  Fiona Garcia         hr              $ 85,000.00
  George Wilson        finance         $210,000.00
  Hannah Martinez      finance         $ 95,000.00
  Ivan Chen            engineering     $115,000.00
  Julia Kim            product         $130,000.00
  Kevin Patel          engineering     $ 85,000.00
  Laura Thompson       hr              $ 72,000.00
  Michael Wang         finance         $ 88,000.00
  Nina Anderson        engineering     $ 95,000.00
  Oscar Rodriguez      product         $110,000.00

Engineering lead sees 7 employees:
  Alice Johnson        engineering     $125,000.00
  Bob Smith            engineering     $155,000.00
  Carol Davis          engineering     $195,000.00
  Diana Lee            engineering     $105,000.00
  Ivan Chen            engineering     $115,000.00
  Kevin Patel          engineering     $ 85,000.00
  Nina Anderson        engineering     $ 95,000.00

Average salary: $120,333.33
```

## Explanation

**Admin query**: The admin role has no RLS predicates, so all 15 employees are returned. The query selects `name`, `department`, and `salary` fields.

**Engineering lead query**: The `RLSContext` includes `predicates={"department": "engineering"}`, which is injected as a WHERE clause. Only the 7 employees in the engineering department are returned.

**Aggregate query**: The `"aggregate": "AVG"` parameter tells the backend to compute the average of the `salary` field. The result is returned as `result["value"]` instead of `result["rows"]`. The aggregate runs across all rows visible to the analyst role (which has no row predicates, so it sees all 15).

!!! note "In-memory database"
    Using `":memory:"` creates a temporary SQLite database with seed data. This is the same approach the test suite uses. For production, configure `datacore.db_path` in `config/default.yaml`.
