"""Base agent class — the foundation of every agent in the mesh.

All agents (Leaf, Orchestrator, DataCore) inherit from BaseAgent.
It provides the lifecycle (start/stop), message loop, authentication
injection/verification, and audit logging.
"""

from __future__ import annotations

import abc
import asyncio
import logging
import uuid
from typing import Any

from .errors import FHAMeshError, HopLimitExceeded
from .message import MessageEnvelope
from .registry import AgentRegistry
from .types import AgentLayer, MessageType
from ..bus.channels import ChannelRouter
from ..bus.middleware import MessageMiddleware
from ..bus.transport import RedisTransport
from ..security.audit import AuditLogger
from ..security.credentials import ScopedToken, TokenMinter
from ..security.verifier import CredentialVerifier


class BaseAgent(abc.ABC):
    """Abstract base for all agents in the mesh.

    Subclass this to create Leaf, Orchestrator, or DataCore agents.
    Provides lifecycle management, authenticated message handling,
    and audit logging out of the box.
    """

    def __init__(
        self,
        agent_id: str | None = None,
        layer: AgentLayer = AgentLayer.LEAF,
        domain: str = "general",
        config: dict[str, Any] | None = None,
    ):
        self.agent_id = agent_id or f"{layer.value}:{domain}:{uuid.uuid4().hex[:8]}"
        self.layer = layer
        self.domain = domain
        self.config = config or {}
        self.logger = logging.getLogger(f"fhamesh.{self.agent_id}")
        self._running = False
        self._transport: RedisTransport | None = None
        self._registry: AgentRegistry | None = None
        self._middleware: MessageMiddleware | None = None
        self._token_minter: TokenMinter | None = None
        self._audit: AuditLogger | None = None
        self._heartbeat_task: asyncio.Task[None] | None = None

    # --- Lifecycle ---

    async def start(
        self,
        transport: RedisTransport,
        registry: AgentRegistry | None = None,
        middleware: MessageMiddleware | None = None,
        token_minter: TokenMinter | None = None,
        audit: AuditLogger | None = None,
    ) -> None:
        """Connect to the mesh, register, and prepare for message processing."""
        self._transport = transport
        self._registry = registry
        self._middleware = middleware
        self._token_minter = token_minter
        self._audit = audit
        self._running = True

        # Register in the mesh
        channels = ChannelRouter.agent_channels(self.agent_id, self.layer, self.domain)
        if self._registry:
            await self._registry.register(
                self.agent_id, self.layer.value, self.domain, channels,
            )

        # Subscribe to channels
        await self._transport.subscribe(*channels)

        # Start heartbeat
        self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())

        self.logger.info("Agent started: %s", self.agent_id)

    async def run(self) -> None:
        """Main message processing loop. Call after start()."""
        if self._transport is None:
            raise RuntimeError("Agent not started. Call start() first.")
        try:
            async for raw in self._transport.listen():
                if not self._running:
                    break
                await self._process_raw_message(raw)
        except asyncio.CancelledError:
            pass
        except Exception:
            self.logger.exception("Fatal error in message loop")
        finally:
            await self.stop()

    async def stop(self) -> None:
        """Deregister and shut down."""
        self._running = False
        if self._heartbeat_task:
            self._heartbeat_task.cancel()
            try:
                await self._heartbeat_task
            except asyncio.CancelledError:
                pass
        if self._registry:
            await self._registry.deregister(self.agent_id)
        self.logger.info("Agent stopped: %s", self.agent_id)

    # --- Abstract methods (each layer implements) ---

    @abc.abstractmethod
    async def handle_message(self, envelope: MessageEnvelope) -> MessageEnvelope | None:
        """Process an incoming message. Return a response envelope or None."""
        ...

    @abc.abstractmethod
    async def health_check(self) -> dict[str, Any]:
        """Return health/status information."""
        ...

    # --- Message handling ---

    async def _process_raw_message(self, raw: bytes) -> None:
        """Deserialize, validate, and dispatch a raw message."""
        try:
            envelope = MessageEnvelope.from_bytes(raw)
        except Exception:
            self.logger.warning("Failed to deserialize message")
            return

        # Skip messages from self
        if envelope.source_agent_id == self.agent_id:
            return

        # Middleware validation (auth, TTL, hops)
        if self._middleware:
            allowed, reason = await self._middleware.process_inbound(
                envelope,
                expected_action=envelope.message_type,
                expected_target=self.agent_id,
            )
            if not allowed:
                self.logger.warning(
                    "Message rejected: %s (from %s)", reason, envelope.source_agent_id,
                )
                return

        # Audit log inbound
        if self._audit:
            await self._audit.log_event("recv", self.agent_id, envelope)

        # Handle health pings automatically
        if envelope.message_type == MessageType.HEALTH_PING.value:
            await self._handle_health_ping(envelope)
            return

        # Dispatch to subclass handler
        try:
            response = await self.handle_message(envelope)
            if response:
                # Propagate _reply_channel from inbound message so the
                # response routes back to the waiting transport.request() caller.
                reply_ch = envelope.payload.get("_reply_channel", "")
                if reply_ch:
                    d = response.to_dict()
                    d["payload"]["_reply_channel"] = reply_ch
                    response = MessageEnvelope.from_dict(d)
                await self.send(response)
        except FHAMeshError as exc:
            self.logger.error("Mesh error handling %s: %s", envelope.message_id, exc)
            await self._send_error(envelope, str(exc))
        except Exception as exc:
            self.logger.exception("Unexpected error handling %s", envelope.message_id)
            await self._send_error(envelope, f"Internal error: {type(exc).__name__}")

    async def send(self, envelope: MessageEnvelope) -> None:
        """Send a message with auth token injection and audit logging."""
        if self._transport is None:
            raise RuntimeError("Agent not started")
        if envelope.hop_count >= envelope.max_hops:
            raise HopLimitExceeded(f"Hop limit {envelope.max_hops} reached")

        stamped = self._stamp_auth(envelope)

        if self._audit:
            await self._audit.log_event("send", self.agent_id, stamped)

        # If the payload carries a _reply_channel, publish there directly
        # so the waiting transport.request() caller receives the response.
        reply_ch = envelope.payload.get("_reply_channel", "")
        if reply_ch:
            self.logger.debug("Sending response on reply channel: %s", reply_ch)
            await self._transport.publish_to_channel(reply_ch, stamped)
        else:
            await self._transport.publish(stamped)

    def _stamp_auth(self, envelope: MessageEnvelope) -> MessageEnvelope:
        """Attach a freshly minted auth token to an outbound message."""
        if self._token_minter is None:
            return envelope

        token = self._token_minter.mint(
            issuer_agent_id=self.agent_id,
            subject_agent_id=envelope.target_agent_id,
            layer=self.layer.value,
            domain=self.domain,
            allowed_actions=[envelope.message_type],
            ttl_seconds=self.config.get("token_ttl_seconds", 30),
        )

        d = envelope.to_dict()
        d["auth_token"] = token.to_json()
        d["source_agent_id"] = self.agent_id
        return MessageEnvelope.from_dict(d)

    def mint_token(
        self,
        target_agent_id: str,
        allowed_actions: list[str],
        role: str = "",
        user_id: str = "",
        scoped_fields: list[str] | None = None,
        ttl_seconds: int = 30,
    ) -> ScopedToken | None:
        """Mint a new scoped token (convenience wrapper)."""
        if self._token_minter is None:
            return None
        return self._token_minter.mint(
            issuer_agent_id=self.agent_id,
            subject_agent_id=target_agent_id,
            layer=self.layer.value,
            domain=self.domain,
            allowed_actions=allowed_actions,
            ttl_seconds=ttl_seconds,
            scoped_fields=scoped_fields,
            role=role,
            user_id=user_id,
        )

    # --- Internal helpers ---

    async def _handle_health_ping(self, envelope: MessageEnvelope) -> None:
        """Respond to a health ping."""
        health = await self.health_check()
        response = envelope.reply(
            message_type=MessageType.HEALTH_PONG.value,
            payload=health,
            source_agent_id=self.agent_id,
        )
        await self.send(response)

    async def _send_error(self, original: MessageEnvelope, error_message: str) -> None:
        """Send an error response back to the sender."""
        response = original.reply(
            message_type=MessageType.ERROR.value,
            payload={"error": error_message},
            source_agent_id=self.agent_id,
        )
        try:
            await self.send(response)
        except Exception:
            self.logger.exception("Failed to send error response")

    async def _heartbeat_loop(self) -> None:
        """Periodically refresh registration TTL."""
        interval = max(10, (self._registry._ttl // 3) if self._registry else 20)
        while self._running:
            try:
                await asyncio.sleep(interval)
                if self._registry and self._running:
                    await self._registry.heartbeat(self.agent_id)
            except asyncio.CancelledError:
                break
            except Exception:
                self.logger.exception("Heartbeat error")
