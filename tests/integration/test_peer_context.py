"""Tests for OrchestratorNode's describe_context peer-request handler.

This is the server side of cross-domain coordination: another
orchestrator asks "what do you have for this intent", and this
orchestrator answers from its own DynamicSchemaRegistry — never from
row data. No transport/Redis needed since _handle_peer_request doesn't
touch either directly.
"""

from fhamesh.core.message import IntentDescriptor, MessageEnvelope
from fhamesh.core.types import MessageType
from fhamesh.orchestrator.controller import OrchestratorNode


class TestDescribeContext:
    async def test_describe_context_returns_schema_for_own_domain(self):
        orch = OrchestratorNode(domain="hr")
        intent = IntentDescriptor(category="query", domain="hr", action="lookup_salary", confidence=0.9)

        request = MessageEnvelope(
            message_type=MessageType.PEER_REQUEST.value,
            source_agent_id="orchestrator:finance:abc",
            target_agent_id=orch.agent_id,
            payload={"action": "describe_context", "intent": intent.to_dict()},
        )

        response = await orch._handle_peer_request(request)

        assert response is not None
        assert response.payload["domain"] == "hr"
        assert response.payload["table"] == "employees"
        assert "salary" in response.payload["known_fields"]

    async def test_unrecognized_action_falls_back_to_acknowledgement(self):
        orch = OrchestratorNode(domain="hr")
        request = MessageEnvelope(
            message_type=MessageType.PEER_REQUEST.value,
            source_agent_id="orchestrator:finance:abc",
            target_agent_id=orch.agent_id,
            payload={"action": "something_else"},
        )

        response = await orch._handle_peer_request(request)

        assert response is not None
        assert response.payload["status"] == "acknowledged"

    async def test_no_action_falls_back_to_acknowledgement(self):
        orch = OrchestratorNode(domain="hr")
        request = MessageEnvelope(
            message_type=MessageType.PEER_REQUEST.value,
            source_agent_id="orchestrator:finance:abc",
            target_agent_id=orch.agent_id,
            payload={},
        )

        response = await orch._handle_peer_request(request)

        assert response is not None
        assert response.payload["domain"] == "hr"
        assert response.payload["status"] == "acknowledged"
