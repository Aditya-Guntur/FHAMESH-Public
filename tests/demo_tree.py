#!/usr/bin/env python
"""Demo: Show global audit log tree with query tree manager.

This demo simulates query flow and shows the tree visualization.
No real Redis required.
"""

from __future__ import annotations

import asyncio
import json

from fhamesh.security.audit import AuditLogger
from fhamesh.security.query_tree_manager import QueryTreeManager


async def main():
    print("\n" + "=" * 60)
    print("  FHAMESH Query Tree Demo")
    print("=" * 60)

    audit = AuditLogger(":memory:")
    await audit.initialize()

    tree_manager = QueryTreeManager(audit)

    print("\n[1] Simulating query flow through the mesh...")

    import uuid
    from fhamesh.core.message import MessageEnvelope

    correlation_id = uuid.uuid4().hex[:12]

    env1 = MessageEnvelope(
        correlation_id=correlation_id,
        message_type="intent_request",
        source_agent_id="runner:client",
        target_agent_id="leaf:router",
        payload={"user_input": "Show me salaries"},
    )
    await audit.log_event("send", "runner:client", env1)
    await audit.log_event("recv", "leaf:router", env1)

    env2 = MessageEnvelope(
        correlation_id=correlation_id,
        message_type="data_query",
        source_agent_id="leaf:router",
        target_agent_id="orchestrator:controller",
        payload={"intent": "salary_query"},
        subtree_id="subtree:orch:1",
        parent_message_id=env1.message_id,
    )
    await audit.log_event("send", "leaf:router", env2)
    await audit.log_event("recv", "orchestrator:controller", env2)

    env3 = MessageEnvelope(
        correlation_id=correlation_id,
        message_type="data_query",
        source_agent_id="orchestrator:controller",
        target_agent_id="datacore:node",
        payload={"sql": "SELECT * FROM salaries"},
        subtree_id="subtree:orch:1",
        parent_message_id=env2.message_id,
    )
    await audit.log_event("send", "orchestrator:controller", env3)

    env4 = MessageEnvelope(
        correlation_id=correlation_id,
        message_type="data_response",
        source_agent_id="datacore:node",
        target_agent_id="orchestrator:controller",
        payload={"rows": [{"salary": 50000}, {"salary": 60000}]},
        subtree_id="subtree:orch:1",
        parent_message_id=env3.message_id,
    )
    await audit.log_event("send", "datacore:node", env4)
    await audit.log_event("recv", "orchestrator:controller", env4)

    env5 = MessageEnvelope(
        correlation_id=correlation_id,
        message_type="data_response",
        source_agent_id="orchestrator:controller",
        target_agent_id="leaf:router",
        payload={"data": [{"salary": 50000}, {"salary": 60000}]},
        parent_message_id=env2.message_id,
    )
    await audit.log_event("send", "orchestrator:controller", env5)
    await audit.log_event("recv", "leaf:router", env5)
    await audit.log_event("send", "leaf:router", env5)
    await audit.log_event("recv", "runner:client", env5)

    print("\n[2] Query tree for correlation", correlation_id)
    print("-" * 40)
    tree = await tree_manager.show_tree_ascii(correlation_id)
    print(tree or "(empty)")

    print("\n[3] Branch analysis (detects cutoffs)")
    print("-" * 40)
    analysis = await tree_manager.analyze_correlation(correlation_id)
    print(json.dumps(analysis, indent=2))

    print("\n[4] All recent correlations")
    print("-" * 40)
    corr_ids = await tree_manager.get_all_correlation_ids()
    for cid in corr_ids:
        print(f"  {cid}")

    print("\n" + "=" * 60)
    print("  Demo complete!")
    print("=" * 60 + "\n")

    await audit.close()


if __name__ == "__main__":
    asyncio.run(main())
