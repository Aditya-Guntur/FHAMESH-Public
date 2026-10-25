"""Leaf Interaction Node — the edge layer agent.

Sits at the user boundary. Sanitizes input, classifies intent,
routes to domain, checks eligibility, and forwards a structured
IntentDescriptor to the appropriate orchestrator.

Has NO access to backend data. Never sees query results.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from ..core.agent import BaseAgent
from ..core.message import IntentDescriptor, MessageEnvelope
from ..core.types import AgentLayer, MessageType
from ..security.credentials import ScopedToken
from .classifier import IntentClassifier
from .gate import EligibilityGate
from .router import DomainRouter
from .sanitizer import InputSanitizer

logger = logging.getLogger(__name__)


class LeafNode(BaseAgent):
    """Edge-layer agent deployed at the user interface boundary.

    Responsibilities:
    - Sanitize input (assume all input is adversarial)
    - Classify intent (keyword-based, pluggable for ML)
    - Route to correct domain
    - Check eligibility
    - Produce IntentDescriptor and forward to orchestrator

    Constraints:
    - No access to backend systems or sensitive data
    - No deep reasoning or response synthesis
    - No visibility into historical state beyond the current turn
    """

    def __init__(
        self,
        domain: str = "general",
        config: dict[str, Any] | None = None,
    ):
        super().__init__(layer=AgentLayer.LEAF, domain=domain, config=config or {})
        cfg = self.config
        self._sanitizer = InputSanitizer(cfg.get("sanitizer"))
        self._classifier = IntentClassifier(cfg.get("classifier"))
        self._router = DomainRouter(cfg.get("domains"))
        self._gate = EligibilityGate(cfg.get("eligibility"))

    async def handle_message(self, envelope: MessageEnvelope) -> MessageEnvelope | None:
        """Process an incoming user request.

        Flow: sanitize -> classify -> route -> gate -> forward
        """
        # Only handle intent requests
        if envelope.message_type not in (
            MessageType.INTENT_REQUEST.value, ""
        ):
            self.logger.debug("Ignoring message type: %s", envelope.message_type)
            return None

        raw_input = envelope.payload.get("user_input", "")
        user_id = envelope.payload.get("user_id", "")
        role = envelope.payload.get("role", "viewer")

        # Step 1: Sanitize
        sanitized, is_safe = self._sanitizer.sanitize(raw_input)
        if not is_safe:
            self.logger.warning("Input failed sanitization from %s", envelope.source_agent_id)
            return self._build_rejection(envelope, "Input failed safety checks")

        # Step 2: Classify intent
        intent = self._classifier.classify(sanitized)
        intent.sanitized = True
        intent.raw_input_hash = self._sanitizer.compute_hash(raw_input)

        # Step 3: Route to domain
        target_domain = self._router.resolve(intent)
        intent.domain = target_domain

        # Step 4: Eligibility gate
        # Parse token from envelope if present
        token = None
        if envelope.auth_token:
            try:
                token = ScopedToken.from_json(envelope.auth_token)
            except (ValueError, KeyError):
                pass

        # If no token, mint one for the user (leaf is the entry point)
        if token is None and self._token_minter:
            token = self._token_minter.mint(
                issuer_agent_id=self.agent_id,
                subject_agent_id="",
                layer=self.layer.value,
                domain=target_domain,
                allowed_actions=[MessageType.INTENT_REQUEST.value, MessageType.DATA_QUERY.value],
                role=role,
                user_id=user_id,
                ttl_seconds=self.config.get("token_ttl_seconds", 30),
            )

        eligible, reason = await self._gate.check(intent, token)
        if not eligible:
            self.logger.warning("Eligibility denied: %s", reason)
            return self._build_rejection(envelope, f"Eligibility denied: {reason}")

        intent.eligibility_passed = True

        # Step 5: Forward to orchestrator and wait for response
        forward_envelope = await self._build_forward(
            envelope, target_domain, intent, token, user_id, role,
        )

        # Use request/reply to synchronously wait for the orchestrator's response
        if self._transport:
            response = await self._transport.request(forward_envelope, timeout=15.0)
            if response:
                # Relay the orchestrator's response back to the original caller
                return MessageEnvelope(
                    correlation_id=envelope.correlation_id or envelope.message_id,
                    message_type=response.message_type,
                    source_agent_id=self.agent_id,
                    target_agent_id=envelope.source_agent_id,
                    payload=response.payload,
                    parent_message_id=envelope.message_id,
                    hop_count=response.hop_count + 1,
                    max_hops=envelope.max_hops,
                )
            else:
                return self._build_rejection(envelope, "Orchestrator timeout")
        return self._build_rejection(envelope, "No transport available")

    async def _build_forward(
        self,
        original: MessageEnvelope,
        target_domain: str,
        intent: IntentDescriptor,
        token: ScopedToken | None,
        user_id: str,
        role: str,
    ) -> MessageEnvelope:
        """Build a forwarding envelope to the target orchestrator."""
        # Look up the orchestrator in the registry
        target_id = ""
        if self._registry:
            target_id = await self._registry.find_one(
                target_domain, AgentLayer.ORCHESTRATOR,
            ) or ""

        # If no specific orchestrator found, try general
        if not target_id and self._registry:
            target_id = await self._registry.find_one(
                "general", AgentLayer.ORCHESTRATOR,
            ) or ""

        payload = {
            "intent": intent.to_dict(),
            "user_id": user_id,
            "role": role,
        }

        # Mint a fresh token for the orchestrator
        auth_token = ""
        if self._token_minter and token:
            orch_token = self._token_minter.mint(
                issuer_agent_id=self.agent_id,
                subject_agent_id=target_id,
                layer=self.layer.value,
                domain=target_domain,
                allowed_actions=[
                    MessageType.INTENT_REQUEST.value,
                    MessageType.DATA_QUERY.value,
                ],
                role=role,
                user_id=user_id,
                scoped_fields=list(token.scoped_fields) if token.scoped_fields else None,
                ttl_seconds=self.config.get("token_ttl_seconds", 30),
            )
            auth_token = orch_token.to_json()

        return MessageEnvelope(
            correlation_id=original.correlation_id or original.message_id,
            message_type=MessageType.INTENT_REQUEST.value,
            source_agent_id=self.agent_id,
            target_agent_id=target_id,
            payload=payload,
            auth_token=auth_token,
            parent_message_id=original.message_id,
            hop_count=original.hop_count + 1,
            max_hops=original.max_hops,
        )

    def _build_rejection(
        self,
        original: MessageEnvelope,
        reason: str,
    ) -> MessageEnvelope:
        """Build a rejection response envelope."""
        return original.reply(
            message_type=MessageType.ERROR.value,
            payload={"error": reason, "rejected_at": "leaf"},
            source_agent_id=self.agent_id,
        )

    async def health_check(self) -> dict[str, Any]:
        return {
            "agent_id": self.agent_id,
            "layer": "leaf",
            "domain": self.domain,
            "status": "ok",
        }
