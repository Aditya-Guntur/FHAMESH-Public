"""Storage backend abstraction and SQLite implementation.

Provides a pluggable storage interface. The SQLiteBackend is the
default implementation; subclass StorageBackend for PostgreSQL, etc.
"""

from __future__ import annotations

import abc
import logging
from typing import Any

import aiosqlite

logger = logging.getLogger(__name__)


class RLSContext:
    """Row-level security context passed to storage queries."""
    def __init__(
        self,
        user_id: str = "",
        role: str = "",
        department: str = "",
        predicates: dict[str, Any] | None = None,
    ):
        self.user_id = user_id
        self.role = role
        self.department = department
        self.predicates = predicates or {}


class StorageBackend(abc.ABC):
    """Abstract storage backend. Subclass for different databases."""

    @abc.abstractmethod
    async def initialize(self) -> None:
        ...

    @abc.abstractmethod
    async def execute(
        self,
        query: dict[str, Any],
        rls_context: RLSContext | None = None,
    ) -> dict[str, Any]:
        ...

    @abc.abstractmethod
    async def close(self) -> None:
        ...


class SQLiteBackend(StorageBackend):
    """Real SQLite backend with parameterized queries and seed data.

    NEVER accepts raw SQL. All queries are built from structured dicts.
    """

    def __init__(self, db_path: str = "data.db"):
        self._db_path = db_path
        self._conn: aiosqlite.Connection | None = None

    async def initialize(self) -> None:
        """Create database, tables, and seed data."""
        self._conn = await aiosqlite.connect(self._db_path)
        await self._conn.execute("PRAGMA journal_mode=WAL")
        await self._create_tables()
        await self._seed_data()

    async def execute(
        self,
        query: dict[str, Any],
        rls_context: RLSContext | None = None,
    ) -> dict[str, Any]:
        """Execute a structured query with RLS predicates."""
        if self._conn is None:
            raise RuntimeError("Storage not initialized")

        table = query.get("table", "")
        fields = query.get("fields", ["*"])
        filters = dict(query.get("filters", {}))
        limit = query.get("limit", 100)
        aggregate = query.get("aggregate")

        # Merge RLS predicates
        if rls_context and rls_context.predicates:
            filters.update(rls_context.predicates)

        # Build field list
        if aggregate and fields and fields != ["*"]:
            numeric_field = fields[0]
            for f in fields:
                if f in ("salary", "amount", "price", "age", "count"):
                    numeric_field = f
                    break
            select_clause = f"{aggregate.upper()}({numeric_field}) as result"
        else:
            select_clause = ", ".join(fields) if fields != ["*"] else "*"

        # Build WHERE clause (parameterized)
        where_parts: list[str] = []
        params: list[Any] = []
        for col, val in filters.items():
            if col == "date_from":
                where_parts.append("date >= ?")
                params.append(val)
            elif col == "date_to":
                where_parts.append("date <= ?")
                params.append(val)
            else:
                where_parts.append(f"{col} = ?")
                params.append(val)

        sql = f"SELECT {select_clause} FROM {table}"
        if where_parts:
            sql += " WHERE " + " AND ".join(where_parts)
        if not aggregate:
            sql += " LIMIT ?"
            params.append(limit)

        logger.debug("SQL: %s | params: %s", sql, params)

        cursor = await self._conn.execute(sql, params)
        rows = await cursor.fetchall()
        columns = [desc[0] for desc in cursor.description]

        if aggregate:
            result_val = rows[0][0] if rows else 0
            return {
                "aggregate": aggregate,
                "value": result_val,
                "table": table,
                "filters_applied": list(filters.keys()),
                "row_count": 1,
            }

        results = [dict(zip(columns, row)) for row in rows]
        return {
            "rows": results,
            "row_count": len(results),
            "table": table,
            "fields": columns,
            "filters_applied": list(filters.keys()),
        }

    async def close(self) -> None:
        if self._conn:
            await self._conn.close()
            self._conn = None

    async def _create_tables(self) -> None:
        if self._conn is None:
            return
        await self._conn.execute("""
            CREATE TABLE IF NOT EXISTS employees (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL, email TEXT, phone TEXT, ssn TEXT,
                department TEXT NOT NULL, title TEXT NOT NULL,
                salary REAL NOT NULL, manager TEXT, hire_date TEXT
            )
        """)
        await self._conn.execute("""
            CREATE TABLE IF NOT EXISTS orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                order_id TEXT NOT NULL, customer_name TEXT NOT NULL,
                customer_email TEXT, amount REAL NOT NULL,
                date TEXT NOT NULL, status TEXT DEFAULT 'completed',
                product_id INTEGER
            )
        """)
        await self._conn.execute("""
            CREATE TABLE IF NOT EXISTS products (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                product_id TEXT NOT NULL, name TEXT NOT NULL,
                category TEXT NOT NULL, price REAL NOT NULL,
                stock INTEGER DEFAULT 0, description TEXT
            )
        """)
        await self._conn.commit()

    async def _seed_data(self) -> None:
        if self._conn is None:
            return
        cursor = await self._conn.execute("SELECT COUNT(*) FROM employees")
        count = (await cursor.fetchone())[0]
        if count > 0:
            return

        employees = [
            ("Alice Johnson", "alice.johnson@company.com", "555-0101", "123-45-6789", "engineering", "Senior Engineer", 125000, "Bob Smith", "2021-03-15"),
            ("Bob Smith", "bob.smith@company.com", "555-0102", "234-56-7890", "engineering", "Engineering Manager", 155000, "Carol Davis", "2019-06-01"),
            ("Carol Davis", "carol.davis@company.com", "555-0103", "345-67-8901", "engineering", "VP Engineering", 195000, None, "2018-01-10"),
            ("Diana Lee", "diana.lee@company.com", "555-0104", "456-78-9012", "engineering", "Software Engineer", 105000, "Bob Smith", "2022-09-20"),
            ("Ethan Brown", "ethan.brown@company.com", "555-0105", "567-89-0123", "hr", "HR Director", 140000, None, "2020-02-14"),
            ("Fiona Garcia", "fiona.garcia@company.com", "555-0106", "678-90-1234", "hr", "Recruiter", 85000, "Ethan Brown", "2021-07-01"),
            ("George Wilson", "george.wilson@company.com", "555-0107", "789-01-2345", "finance", "CFO", 210000, None, "2017-11-30"),
            ("Hannah Martinez", "hannah.martinez@company.com", "555-0108", "890-12-3456", "finance", "Financial Analyst", 95000, "George Wilson", "2022-01-15"),
            ("Ivan Chen", "ivan.chen@company.com", "555-0109", "901-23-4567", "engineering", "DevOps Engineer", 115000, "Bob Smith", "2021-11-01"),
            ("Julia Kim", "julia.kim@company.com", "555-0110", "012-34-5678", "product", "Product Manager", 130000, "Carol Davis", "2020-08-20"),
            ("Kevin Patel", "kevin.patel@company.com", "555-0111", "111-22-3333", "engineering", "Junior Engineer", 85000, "Bob Smith", "2023-06-01"),
            ("Laura Thompson", "laura.thompson@company.com", "555-0112", "222-33-4444", "hr", "HR Coordinator", 72000, "Ethan Brown", "2023-01-10"),
            ("Michael Wang", "michael.wang@company.com", "555-0113", "333-44-5555", "finance", "Accountant", 88000, "George Wilson", "2022-04-15"),
            ("Nina Anderson", "nina.anderson@company.com", "555-0114", "444-55-6666", "engineering", "QA Engineer", 95000, "Bob Smith", "2021-05-20"),
            ("Oscar Rodriguez", "oscar.rodriguez@company.com", "555-0115", "555-66-7777", "product", "UX Designer", 110000, "Julia Kim", "2022-07-01"),
        ]
        await self._conn.executemany(
            "INSERT INTO employees (name,email,phone,ssn,department,title,salary,manager,hire_date) VALUES (?,?,?,?,?,?,?,?,?)",
            employees,
        )

        orders = [
            ("ORD-001","Alice Johnson","alice@example.com",1250.00,"2024-01-15","completed",1),
            ("ORD-002","Bob Smith","bob@example.com",890.50,"2024-01-20","completed",2),
            ("ORD-003","Charlie Brown","charlie@example.com",2100.00,"2024-02-01","completed",3),
            ("ORD-004","Diana Prince","diana@example.com",450.75,"2024-02-10","completed",1),
            ("ORD-005","Eve Wilson","eve@example.com",3200.00,"2024-02-15","pending",4),
            ("ORD-006","Frank Castle","frank@example.com",780.25,"2024-03-01","completed",2),
            ("ORD-007","Grace Hopper","grace@example.com",1650.00,"2024-03-10","completed",5),
            ("ORD-008","Hank Pym","hank@example.com",920.00,"2024-03-15","shipped",3),
            ("ORD-009","Ivy Chen","ivy@example.com",4500.00,"2024-04-01","completed",6),
            ("ORD-010","Jack Ryan","jack@example.com",550.00,"2024-04-10","completed",1),
        ]
        await self._conn.executemany(
            "INSERT INTO orders (order_id,customer_name,customer_email,amount,date,status,product_id) VALUES (?,?,?,?,?,?,?)",
            orders,
        )

        products = [
            ("PROD-001","Enterprise Server","hardware",12500.00,45,"High-performance rack server"),
            ("PROD-002","Cloud License","software",890.00,999,"Annual cloud platform license"),
            ("PROD-003","Security Suite","software",2100.00,500,"Enterprise security package"),
            ("PROD-004","Wireless Router","hardware",450.00,200,"Enterprise-grade wireless router"),
            ("PROD-005","Database License","software",3200.00,150,"Database management system license"),
            ("PROD-006","Analytics Platform","software",4500.00,75,"Big data analytics suite"),
            ("PROD-007","Backup System","hardware",1650.00,100,"Automated backup appliance"),
            ("PROD-008","Network Switch","hardware",920.00,300,"48-port managed switch"),
        ]
        await self._conn.executemany(
            "INSERT INTO products (product_id,name,category,price,stock,description) VALUES (?,?,?,?,?,?)",
            products,
        )

        await self._conn.commit()
        logger.info("Seeded database with sample data")
