"""DataCore Node — the high-assurance backend agent.

Operates under the strictest constraints. Every query must be validated,
privacy-budgeted, row-filtered, and sanitized before results are returned.
"""

from __future__ import annotations

import logging
from typing import Any

from ..core.agent import BaseAgent
from ..core.message import MessageEnvelope, QueryResult
from ..core.types import AgentLayer, MessageType
from ..security.credentials import ScopedToken
from .privacy import DifferentialPrivacyEngine
from .pii import PIISanitizer
from .query_validator import QueryValidator
from .rls import RowLevelSecurity
from .storage import SQLiteBackend, StorageBackend

logger = logging.getLogger(__name__)


class DataCoreNode(BaseAgent):
    """High-assurance backend agent.

    Responsibilities:
    - Validate queries (field-level justification)
    - Apply row-level security
    - Apply differential privacy noise
    - Detect and redact PII
    - Return structured, privacy-protected results

    The DataCore never receives raw user prompts. All requests are
    structured, validated query objects from the Orchestrator.
    """

    def __init__(
        self,
        domain: str = "general",
        config: dict[str, Any] | None = None,
    ):
        super().__init__(layer=AgentLayer.DATACORE, domain=domain, config=config or {})
        cfg = self.config
        self._query_validator = QueryValidator(cfg.get("query_validation"))
        self._privacy_engine = DifferentialPrivacyEngine(cfg.get("privacy"))
        self._rls = RowLevelSecurity(cfg.get("rls"))
        self._pii_sanitizer = PIISanitizer(cfg.get("pii"))
        self._storage: StorageBackend | None = None

    async def start(self, transport, **kwargs) -> None:
        """Initialize storage and start the agent."""
        db_path = self.config.get("db_path", ":memory:")
        self._storage = SQLiteBackend(db_path)
        await self._storage.initialize()

        # Inject Redis into privacy engine if transport has it
        if hasattr(transport, 'redis'):
            self._privacy_engine.set_redis(transport.redis)

        await super().start(transport, **kwargs)

    async def stop(self) -> None:
        """Clean up storage on shutdown."""
        if self._storage:
            await self._storage.close()
        await super().stop()

    async def handle_message(self, envelope: MessageEnvelope) -> MessageEnvelope | None:
        """Process a data query."""
        if envelope.message_type != MessageType.DATA_QUERY.value:
            self.logger.debug("Ignoring message type: %s", envelope.message_type)
            return None

        query = envelope.payload.get("sub_query", envelope.payload)
        user_id = envelope.payload.get("user_id", "")
        role = envelope.payload.get("role", "viewer")
        sub_query_index = envelope.payload.get("sub_query_index", 0)
        subtree_id = envelope.payload.get("subtree_id", envelope.subtree_id)

        # Step 1: Validate query
        valid, reason = self._query_validator.validate(
            query,
            auth_token_raw=envelope.auth_token,
            policy_attestation=envelope.policy_attestation,
        )
        if not valid:
            self.logger.warning("Query validation failed: %s", reason)
            return self._build_response(
                envelope,
                QueryResult(success=False, error_message=f"Query validation failed: {reason}"),
                sub_query_index,
                subtree_id,
            )

        # Step 2: Check privacy budget
        if user_id:
            budget_ok = await self._privacy_engine.check_budget(user_id)
            if not budget_ok:
                return self._build_response(
                    envelope,
                    QueryResult(success=False, error_message="Privacy budget exhausted"),
                    sub_query_index,
                    subtree_id,
                )

        # Step 3: Build RLS context and execute query
        table = query.get("table", "")
        rls_context = self._rls.build_context_for_table(
            table=table,
            auth_token_raw=envelope.auth_token,
            user_id=user_id,
            role=role,
        )

        try:
            raw_results = await self._storage.execute(query, rls_context)
        except Exception as exc:
            self.logger.exception("Storage execution error")
            return self._build_response(
                envelope,
                QueryResult(success=False, error_message=f"Storage error: {exc}"),
                sub_query_index,
                subtree_id,
            )

        # Step 4: Apply differential privacy
        noisy_results, epsilon_consumed = self._privacy_engine.apply(raw_results, query)

        # Deduct budget
        if user_id and epsilon_consumed > 0:
            await self._privacy_engine.deduct_budget(user_id, epsilon_consumed)

        # Step 5: Sanitize PII
        sanitized, redacted_fields = self._pii_sanitizer.sanitize(noisy_results)

        result = QueryResult(
            success=True,
            data=sanitized,
            privacy_budget_consumed=epsilon_consumed,
            fields_redacted=redacted_fields,
            noise_applied=noisy_results.get("noise_applied", False),
        )

        return self._build_response(envelope, result, sub_query_index, subtree_id)

    def _build_response(
        self,
        original: MessageEnvelope,
        result: QueryResult,
        sub_query_index: int = 0,
        subtree_id: str = "",
    ) -> MessageEnvelope:
        """Build a data response envelope."""
        # Respond on the reply channel if present
        reply_channel = original.payload.get("_reply_channel", "")

        response = original.reply(
            message_type=MessageType.DATA_RESPONSE.value,
            payload={
                "result": result.to_dict(),
                "sub_query_index": sub_query_index,
                "subtree_id": subtree_id,
            },
            source_agent_id=self.agent_id,
        )

        return response

    async def health_check(self) -> dict[str, Any]:
        return {
            "agent_id": self.agent_id,
            "layer": "datacore",
            "domain": self.domain,
            "storage_initialized": self._storage is not None,
            "status": "ok",
        }
