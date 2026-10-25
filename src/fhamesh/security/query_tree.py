"""Query tree visualization from global audit log.

Builds and visualizes the execution tree from audit log entries,
showing message flow, branch states, and cutoff detection.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from .audit import AuditLogger


@dataclass
class QueryTreeNode:
    """A node in the query execution tree."""

    agent_id: str
    message_id: str
    direction: str
    timestamp: float
    subtree_id: str = ""
    parent_message_id: str = ""
    content_hash: str = ""
    children: list["QueryTreeNode"] = field(default_factory=list)
    state: str = "pending"
    error: str = ""


class QueryTreeVisualizer:
    """Builds and visualizes query execution trees from audit logs."""

    def __init__(self, audit_logger: AuditLogger):
        self._audit = audit_logger

    async def build_tree(self, correlation_id: str) -> QueryTreeNode | None:
        """Reconstruct the full query execution tree for a correlation ID."""
        events = await self._audit.query_by_correlation(correlation_id)
        if not events:
            return None

        nodes_by_msg_id: dict[str, QueryTreeNode] = {}
        root = None

        for evt in events:
            node = QueryTreeNode(
                agent_id=evt["agent_id"],
                message_id=evt["message_id"],
                direction=evt["direction"],
                timestamp=evt["timestamp"],
                subtree_id=evt.get("subtree_id", ""),
                parent_message_id=evt.get("parent_message_id", ""),
                content_hash=evt.get("content_hash", ""),
            )
            nodes_by_msg_id[node.message_id] = node

            if not root:
                root = node

        for msg_id, node in nodes_by_msg_id.items():
            if node.parent_message_id and node.parent_message_id in nodes_by_msg_id:
                parent = nodes_by_msg_id[node.parent_message_id]
                parent.children.append(node)

        return root

    def visualize(self, node: QueryTreeNode, indent: int = 0, is_last: bool = True) -> str:
        """Return ASCII tree visualization of the query tree."""
        ts = datetime.fromtimestamp(node.timestamp).strftime("%H:%M:%S.%f")[:-3]

        branch = "└─ " if is_last else "├─ "
        connector = "    " if is_last else "│   "

        icon = "→" if node.direction == "send" else "←"
        subtree_info = f" [{node.subtree_id}]" if node.subtree_id else ""

        short_id = node.agent_id.split(":")[-1][:8] if node.agent_id else "unknown"

        lines = [f"{branch}{ts} {icon} {short_id}{subtree_info}"]

        for i, child in enumerate(node.children):
            is_child_last = i == len(node.children) - 1
            child_lines = self.visualize(child, indent + 1, is_child_last)
            for line in child_lines.split("\n"):
                lines.append(connector + line)

        return "\n".join(lines)

    def to_dict(self, node: QueryTreeNode) -> dict[str, Any]:
        """Convert tree to dictionary for JSON serialization."""
        return {
            "agent_id": node.agent_id,
            "message_id": node.message_id,
            "direction": node.direction,
            "timestamp": node.timestamp,
            "subtree_id": node.subtree_id,
            "state": node.state,
            "error": node.error,
            "children": [self.to_dict(c) for c in node.children],
        }
