"""Query tree manager with branch cutoff detection."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any

from .audit import AuditLogger
from .query_tree import QueryTreeNode, QueryTreeVisualizer


class BranchState(Enum):
    ACTIVE = "active"
    COMPLETED = "completed"
    TIMEOUT = "timeout"
    FAILED = "failed"
    CUTOFF = "cutoff"


@dataclass
class BranchInfo:
    subtree_id: str
    correlation_id: str
    parent_message_id: str
    state: BranchState = BranchState.ACTIVE
    error: str = ""
    completed_at: float | None = None
    expected_results: int = 0
    received_results: int = 0


class QueryTreeManager:
    """Manages query trees and detects branch cutoffs."""

    def __init__(self, audit_logger: AuditLogger):
        self._audit = audit_logger
        self._visualizer = QueryTreeVisualizer(audit_logger)
        self._branches: dict[str, BranchInfo] = {}
        self._last_timestamps: dict[str, float] = {}

    async def analyze_correlation(self, correlation_id: str) -> dict[str, Any]:
        events = await self._audit.query_by_correlation(correlation_id)
        if not events:
            return {"correlation_id": correlation_id, "branches": [], "cutoffs": []}

        subtrees = {}
        root = None

        for evt in events:
            sid = evt.get("subtree_id", "")
            if not sid:
                if evt.get("direction") == "send" and not root:
                    root = evt.get("message_id", "")
                continue

            if sid not in subtrees:
                subtrees[sid] = {"subtree_id": sid, "messages": [], "timeout": False, "failed": False}
            subtrees[sid]["messages"].append(evt)

        cutoffs = []
        for sid, data in subtrees.items():
            msgs = data["messages"]
            sends = [m for m in msgs if m.get("direction") == "send"]
            recvs = [m for m in msgs if m.get("direction") == "recv"]

            if len(sends) > len(recvs):
                if any(m.get("policy_verdict") == "TIMEOUT" for m in msgs):
                    state = BranchState.TIMEOUT
                    error = "Branch timed out"
                elif any(m.get("policy_verdict") in ("DENY", "DROP") for m in msgs):
                    state = BranchState.FAILED
                    error = "Branch denied/dropped"
                else:
                    state = BranchState.CUTOFF
                    error = f"Expected {len(sends)} results, got {len(recvs)}"
                cutoffs.append(
                    {
                        "subtree_id": sid,
                        "state": state.value,
                        "error": error,
                        "expected": len(sends),
                        "received": len(recvs),
                    }
                )

        return {
            "correlation_id": correlation_id,
            "root_message_id": root,
            "branches": [{"subtree_id": sid, "message_count": len(data["messages"])} for sid, data in subtrees.items()],
            "cutoffs": cutoffs,
        }

    async def get_branch_tree(self, correlation_id: str, subtree_id: str | None = None) -> QueryTreeNode | None:
        return await self._visualizer.build_tree(correlation_id)

    async def visualize_branch(self, correlation_id: str, subtree_id: str | None = None) -> str:
        tree = await self._visualizer.build_tree(correlation_id)
        if not tree:
            return "No tree found"
        return self._visualizer.visualize(tree)

    def list_cutoffs(self) -> list[BranchInfo]:
        return [
            b
            for b in self._branches.values()
            if b.state in (BranchState.TIMEOUT, BranchState.FAILED, BranchState.CUTOFF)
        ]

    async def get_all_correlation_ids(self) -> list[str]:
        cursor = await self._audit._conn.execute(
            "SELECT DISTINCT correlation_id FROM audit_log ORDER BY timestamp DESC LIMIT 50"
        )
        rows = await cursor.fetchall()
        return [r[0] for r in rows]

    async def stream_live_tree(self, interval: float = 1.0, max_corr_ids: int = 5) -> None:
        print("")
        print("=" * 60)
        print("  LIVE GLOBAL AUDIT LOG TREE")
        print("  Press Ctrl+C to exit")
        print("=" * 60)
        print("")

        try:
            while True:
                corr_ids = await self.get_all_correlation_ids()
                if not corr_ids:
                    print("[waiting for queries...]")
                    await asyncio.sleep(interval)
                    continue

                for corr_id in corr_ids[:max_corr_ids]:
                    tree = await self.show_tree_ascii(corr_id)
                    print(tree)
                    print("")

                await asyncio.sleep(interval)
        except KeyboardInterrupt:
            print("\n[stopped]")

    async def show_tree_ascii(self, correlation_id: str) -> str:
        """Show git-style tree for one query."""
        events = await self._audit.query_by_correlation(correlation_id)
        if not events:
            return f"Query {correlation_id}: no events"

        lines = []
        short_corr = correlation_id[:8]
        subtrees = set()

        for evt in events:
            subtree = evt.get("subtree_id", "")
            if subtree:
                subtrees.add(subtree.split(":")[-1][:8])

        branch_info = f" branches: {', '.join(subtrees)}" if subtrees else ""

        lines.append(f"* Query: {short_corr}{branch_info}")

        for i, evt in enumerate(events):
            direction = evt["direction"]
            agent = evt["agent_id"]
            msg_type = evt.get("message_type", "?")[:12]
            subtree = evt.get("subtree_id", "")

            layer = agent.split(":")[0] if ":" in agent else "?"
            short = agent.split(":")[-1][:8]
            arrow = ">>" if direction == "send" else "<<"
            branch = f" [{subtree.split(':')[-1][:6]}]" if subtree else ""

            if i < len(events) - 1:
                lines.append(f"|   +-- {short}({layer}) {arrow} {msg_type:12}{branch}")
                lines.append("|   |")
            else:
                lines.append(f"|   `-- {short}({layer}) {arrow} {msg_type:12}{branch}")
                lines.append("|   `-- DONE")

        return "\n".join(lines)

    async def show_global_tree(self) -> str:
        """Show GLOBAL tree with ALL queries."""
        corr_ids = await self.get_all_correlation_ids()
        if not corr_ids:
            return "No active queries"

        lines = [
            "",
            "=" * 50,
            "GLOBAL QUERY TREE (all queries)",
            "=" * 50,
            "",
        ]

        for corr_id in corr_ids[:10]:
            tree = await self.show_tree_ascii(corr_id)
            lines.append(tree)
            lines.append("")

        return "\n".join(lines)

    async def show_branch_manager(self) -> str:
        """Show BRANCH MANAGER - all branches and cutoffs."""
        corr_ids = await self.get_all_correlation_ids()

        lines = [
            "",
            "=" * 50,
            "BRANCH MANAGER",
            "=" * 50,
            "Tracks: timeouts, failures, incomplete branches",
            "=" * 50,
            "",
        ]

        all_branches = []
        all_cutoffs = []

        for corr_id in corr_ids:
            analysis = await self.analyze_correlation(corr_id)
            branches = analysis.get("branches", [])
            cutoffs = analysis.get("cutoffs", [])

            for b in branches:
                all_branches.append({"corr_id": corr_id, "subtree_id": b["subtree_id"], "msgs": b["message_count"]})

            for c in cutoffs:
                all_cutoffs.append(
                    {"corr_id": corr_id, "subtree_id": c["subtree_id"], "state": c["state"], "error": c["error"]}
                )

        total_branches = len(all_branches)
        total_cutoffs = len(all_cutoffs)

        lines.append(f"Total queries: {len(corr_ids)}")
        lines.append(f"Total branches: {total_branches}")
        lines.append(f"Cutoffs: {total_cutoffs}")
        lines.append("")

        if all_cutoffs:
            lines.append("⚠ CUTOFF BRANCHES:")
            for c in all_cutoffs:
                lines.append(f"  ! {c['subtree_id']}")
                lines.append(f"    Query: {c['corr_id'][:8]}")
                lines.append(f"    State: {c['state']}")
                lines.append(f"    Error: {c['error']}")
                lines.append("")
        else:
            lines.append("✓ No cutoffs detected")

        if all_branches:
            lines.append("-" * 40)
            lines.append("Active branches:")
            for b in all_branches[:10]:
                lines.append(f"  + {b['subtree_id']} ({b['msgs']} msgs)")

        return "\n".join(lines)
