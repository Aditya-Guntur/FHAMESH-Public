"""Orchestrator Node — the subtree logic controller.

The primary architectural addition in the mesh. Orchestrators do not
answer user queries directly; they validate and control the execution
path, enforce policy, spawn subtrees, and aggregate results.
"""

from __future__ import annotations

import logging
from typing import Any

from ..core.agent import BaseAgent
from ..core.message import IntentDescriptor, MessageEnvelope, QueryResult
from ..core.types import AgentLayer, MessageType, PolicyVerdict
from ..security.credentials import ScopedToken
from ..security.policy import PolicyAttestation, PolicyEngine, RateLimiter
from ..security.rbac import RBACEnforcer
from .aggregator import ResultAggregator
from .decomposer import QueryDecomposer
from .mesh import PeerMesh
from .subtree import SubtreeManager
from .uncertainty import UncertaintyEstimator
from .validator import ExecutionPathValidator

logger = logging.getLogger(__name__)


class OrchestratorNode(BaseAgent):
    """Core orchestration layer agent.

    Receives IntentDescriptors from Leaf nodes, validates them,
    decomposes complex queries, spawns subtrees, queries DataCore,
    and aggregates results. Supports lateral peer communication.

    For custom orchestration logic, subclass and override _handle_intent().
    """

    def __init__(
        self,
        domain: str = "general",
        config: dict[str, Any] | None = None,
    ):
        super().__init__(layer=AgentLayer.ORCHESTRATOR, domain=domain, config=config or {})
        cfg = self.config
        self._validator = ExecutionPathValidator(cfg.get("validation"))
        self._uncertainty = UncertaintyEstimator(cfg.get("uncertainty"))
        self._decomposer = QueryDecomposer(cfg.get("decomposition"))
        self._subtree_mgr = SubtreeManager(self)
        self._aggregator = ResultAggregator()
        self._peer_mesh = PeerMesh(self)
        self._policy_engine: PolicyEngine | None = None
        self._rbac: RBACEnforcer | None = None

    def set_policy_engine(self, engine: PolicyEngine) -> None:
        """Inject policy engine after construction."""
        self._policy_engine = engine

    def set_rbac(self, rbac: RBACEnforcer) -> None:
        """Inject RBAC enforcer after construction."""
        self._rbac = rbac

    async def handle_message(self, envelope: MessageEnvelope) -> MessageEnvelope | None:
        """Route messages to the appropriate handler."""
        match envelope.message_type:
            case MessageType.INTENT_REQUEST.value:
                return await self._handle_intent(envelope)
            case MessageType.DATA_RESPONSE.value:
                return await self._handle_data_response(envelope)
            case MessageType.SUBTREE_RESULT.value:
                return await self._handle_subtree_result(envelope)
            case MessageType.PEER_REQUEST.value:
                return await self._handle_peer_request(envelope)
            case _:
                self.logger.debug("Unhandled message type: %s", envelope.message_type)
                return None

    async def _handle_intent(self, envelope: MessageEnvelope) -> MessageEnvelope | None:
        """Main orchestration pipeline.

        1. Parse and validate intent
        2. Estimate uncertainty / detect adversarial input
        3. Enforce policy (RBAC, rate limiting)
        4. Decompose into sub-queries
        5. Execute (direct DataCore query or spawn subtrees)
        6. Return result
        """
        intent_data = envelope.payload.get("intent", {})
        intent = IntentDescriptor.from_dict(intent_data)
        user_id = envelope.payload.get("user_id", "")
        role = envelope.payload.get("role", "viewer")

        # Step 1: Validate execution path
        valid, reason = self._validator.validate(intent, envelope)
        if not valid:
            self.logger.warning("Validation failed: %s", reason)
            return self._build_error(envelope, f"Validation failed: {reason}")

        # Step 2: Uncertainty estimation
        uncertainty = self._uncertainty.estimate(intent)
        if uncertainty.is_adversarial:
            self.logger.warning("Adversarial input detected: %s", uncertainty.reasoning)
            return self._build_error(envelope, "Adversarial input detected")
        if uncertainty.confidence < self._uncertainty.rejection_threshold:
            self.logger.warning("Low confidence: %s", uncertainty.reasoning)
            return self._build_error(
                envelope,
                f"Confidence too low ({uncertainty.confidence:.3f})",
            )

        # Step 3: Policy enforcement
        token = None
        if envelope.auth_token:
            try:
                token = ScopedToken.from_json(envelope.auth_token)
            except (ValueError, KeyError):
                return self._build_error(envelope, "Invalid auth token")

        attestation: PolicyAttestation | None = None
        if self._policy_engine and token:
            resource = self._decomposer._resolve_table(intent)
            fields = self._decomposer._resolve_fields(intent)

            verdict, attestation = await self._policy_engine.evaluate(
                envelope=envelope,
                token=token,
                resource=resource,
                action="read",
                fields=fields,
                agent_id=self.agent_id,
            )
            if verdict != PolicyVerdict.ALLOW:
                self.logger.warning("Policy denied: %s", verdict.name)
                return self._build_error(envelope, f"Policy denied: {verdict.name}")

        # Step 4: Decompose
        sub_queries = self._decomposer.decompose(intent)

        for sq in sub_queries:
            sq["user_id"] = user_id
            sq["role"] = role
            if attestation:
                sq["attestation"] = attestation.to_json()

        # Step 5: Execute
        if len(sub_queries) == 1:
            result = await self._query_datacore(
                sub_queries[0], envelope, attestation, user_id, role,
            )
            if result is not None:
                return self._build_response(envelope, result)
            return None
        else:
            timeout = self.config.get("subtree", {}).get("timeout_seconds", 30.0)
            subtree_id = await self._subtree_mgr.spawn(
                parent_envelope=envelope,
                sub_queries=sub_queries,
                timeout_seconds=timeout,
            )
            self.logger.info("Spawned subtree %s for decomposed query", subtree_id)
            return None

    async def _query_datacore(
        self,
        query: dict[str, Any],
        envelope: MessageEnvelope,
        attestation: PolicyAttestation | None,
        user_id: str,
        role: str,
    ) -> QueryResult | None:
        """Send a validated query to a DataCore node."""
        target_id = ""
        domain = query.get("domain", self.domain)
        if self._registry:
            target_id = await self._registry.find_one(
                domain, AgentLayer.DATACORE,
            ) or ""
            if not target_id:
                target_id = await self._registry.find_one(
                    "general", AgentLayer.DATACORE,
                ) or ""

        payload: dict[str, Any] = {
            "sub_query": query,
            "sub_query_index": 0,
            "user_id": user_id,
            "role": role,
        }

        auth_token = ""
        if self._token_minter:
            dc_token = self._token_minter.mint(
                issuer_agent_id=self.agent_id,
                subject_agent_id=target_id,
                layer=self.layer.value,
                domain=domain,
                allowed_actions=[MessageType.DATA_QUERY.value],
                role=role,
                user_id=user_id,
                scoped_fields=query.get("fields", []),
            )
            auth_token = dc_token.to_json()

        query_envelope = MessageEnvelope(
            correlation_id=envelope.correlation_id,
            message_type=MessageType.DATA_QUERY.value,
            source_agent_id=self.agent_id,
            target_agent_id=target_id,
            payload=payload,
            auth_token=auth_token,
            policy_attestation=attestation.to_json() if attestation else "",
            parent_message_id=envelope.message_id,
            hop_count=envelope.hop_count + 1,
            max_hops=envelope.max_hops,
        )

        if self._transport and target_id:
            response = await self._transport.request(
                query_envelope, timeout=15.0,
            )
            if response and response.payload.get("result"):
                return QueryResult.from_dict(response.payload["result"])
            elif response and response.message_type == MessageType.ERROR.value:
                return QueryResult(
                    success=False,
                    error_message=response.payload.get("error", "DataCore error"),
                )

        await self.send(query_envelope)
        return None

    async def _handle_data_response(self, envelope: MessageEnvelope) -> MessageEnvelope | None:
        """Handle a response from a DataCore node."""
        subtree_id = envelope.payload.get("subtree_id", envelope.subtree_id)
        idx = envelope.payload.get("sub_query_index", 0)
        result_data = envelope.payload.get("result", {})
        result = QueryResult.from_dict(result_data)

        if subtree_id and subtree_id in self._subtree_mgr._active:
            self._subtree_mgr.record_result(subtree_id, idx, result)
            if self._subtree_mgr.is_complete(subtree_id):
                return await self._finalize_subtree(subtree_id)
        else:
            return envelope.reply(
                message_type=MessageType.INTENT_RESPONSE.value,
                payload={"result": result.to_dict()},
                source_agent_id=self.agent_id,
            )

        return None

    async def _handle_subtree_result(self, envelope: MessageEnvelope) -> MessageEnvelope | None:
        """Handle a result from a child subtree."""
        subtree_id = envelope.subtree_id or envelope.payload.get("subtree_id", "")
        idx = envelope.payload.get("sub_query_index", 0)
        result_data = envelope.payload.get("result", {})
        result = QueryResult.from_dict(result_data)

        self._subtree_mgr.record_result(subtree_id, idx, result)

        if self._subtree_mgr.is_complete(subtree_id):
            return await self._finalize_subtree(subtree_id)

        return None

    async def _finalize_subtree(self, subtree_id: str) -> MessageEnvelope | None:
        """Aggregate subtree results and respond to the original caller."""
        results = self._subtree_mgr.collect_results(subtree_id)
        aggregated = self._aggregator.aggregate(results)
        parent_envelope = self._subtree_mgr.get_parent_envelope(subtree_id)

        await self._subtree_mgr.gc(subtree_id)

        if parent_envelope:
            return self._build_response(parent_envelope, aggregated)
        return None

    async def _handle_peer_request(self, envelope: MessageEnvelope) -> MessageEnvelope | None:
        """Handle a request from a peer orchestrator."""
        self.logger.info(
            "Peer request from %s", envelope.source_agent_id,
        )
        return envelope.reply(
            message_type=MessageType.PEER_RESPONSE.value,
            payload={"status": "acknowledged", "domain": self.domain},
            source_agent_id=self.agent_id,
        )

    def _build_error(self, original: MessageEnvelope, reason: str) -> MessageEnvelope:
        """Build an error response."""
        return original.reply(
            message_type=MessageType.ERROR.value,
            payload={"error": reason, "rejected_at": "orchestrator"},
            source_agent_id=self.agent_id,
        )

    def _build_response(
        self,
        original: MessageEnvelope,
        result: QueryResult,
    ) -> MessageEnvelope:
        """Build a success response with query results."""
        return original.reply(
            message_type=MessageType.INTENT_RESPONSE.value,
            payload={"result": result.to_dict()},
            source_agent_id=self.agent_id,
        )

    async def health_check(self) -> dict[str, Any]:
        return {
            "agent_id": self.agent_id,
            "layer": "orchestrator",
            "domain": self.domain,
            "active_subtrees": self._subtree_mgr.active_count(),
            "status": "ok",
        }
