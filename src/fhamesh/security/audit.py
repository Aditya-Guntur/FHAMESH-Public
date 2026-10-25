"""Append-only audit log for the agent mesh.

Every message sent/received is logged with content hashes (never raw content),
agent IDs, timestamps, and confidence scores. Stored in SQLite for the prototype.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any

import aiosqlite

from ..core.message import MessageEnvelope

logger = logging.getLogger(__name__)


class AuditLogger:
    """SQLite-backed append-only audit trail.

    Logs message metadata and content hashes for forensic analysis
    and post-incident attribution.
    """

    def __init__(self, db_path: str = "audit.db"):
        self._db_path = db_path
        self._conn: aiosqlite.Connection | None = None

    async def initialize(self) -> None:
        """Create the audit database and table."""
        self._conn = await aiosqlite.connect(self._db_path)
        await self._conn.execute("""
            CREATE TABLE IF NOT EXISTS audit_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp REAL NOT NULL,
                direction TEXT NOT NULL,
                agent_id TEXT NOT NULL,
                message_id TEXT NOT NULL,
                correlation_id TEXT NOT NULL,
                message_type TEXT NOT NULL,
                source_agent_id TEXT NOT NULL,
                target_agent_id TEXT NOT NULL,
                content_hash TEXT NOT NULL,
                hop_count INTEGER NOT NULL,
                subtree_id TEXT DEFAULT '',
                confidence REAL,
                attestation_id TEXT DEFAULT '',
                policy_verdict TEXT DEFAULT ''
            )
        """)
        await self._conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_audit_correlation
            ON audit_log(correlation_id)
        """)
        await self._conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_audit_agent
            ON audit_log(agent_id, timestamp)
        """)
        await self._conn.commit()

    async def log_event(
        self,
        direction: str,
        agent_id: str,
        envelope: MessageEnvelope,
        confidence: float | None = None,
        attestation_id: str = "",
        policy_verdict: str = "",
    ) -> None:
        """Log a message event to the audit trail."""
        if self._conn is None:
            return
        await self._conn.execute(
            """INSERT INTO audit_log (
                timestamp, direction, agent_id, message_id, correlation_id,
                message_type, source_agent_id, target_agent_id, content_hash,
                hop_count, subtree_id, confidence, attestation_id, policy_verdict
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                time.time(),
                direction,
                agent_id,
                envelope.message_id,
                envelope.correlation_id,
                envelope.message_type,
                envelope.source_agent_id,
                envelope.target_agent_id,
                envelope.content_hash(),
                envelope.hop_count,
                envelope.subtree_id,
                confidence,
                attestation_id,
                policy_verdict,
            ),
        )
        await self._conn.commit()

    async def query_by_correlation(self, correlation_id: str) -> list[dict[str, Any]]:
        """Trace a request through the entire mesh by correlation ID."""
        if self._conn is None:
            return []
        cursor = await self._conn.execute(
            "SELECT * FROM audit_log WHERE correlation_id = ? ORDER BY timestamp",
            (correlation_id,),
        )
        rows = await cursor.fetchall()
        columns = [desc[0] for desc in cursor.description]
        return [dict(zip(columns, row)) for row in rows]

    async def query_by_agent(
        self,
        agent_id: str,
        since: float = 0,
    ) -> list[dict[str, Any]]:
        """Query audit events for a specific agent."""
        if self._conn is None:
            return []
        cursor = await self._conn.execute(
            "SELECT * FROM audit_log WHERE agent_id = ? AND timestamp >= ? ORDER BY timestamp",
            (agent_id, since),
        )
        rows = await cursor.fetchall()
        columns = [desc[0] for desc in cursor.description]
        return [dict(zip(columns, row)) for row in rows]

    async def close(self) -> None:
        """Close the audit database connection."""
        if self._conn:
            await self._conn.close()
            self._conn = None
