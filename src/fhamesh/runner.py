"""FHAMESH runner — process launcher and CLI entry point.

Starts all agents (Leaf, Orchestrator, DataCore) as concurrent async tasks,
wires up security infrastructure, and provides a demo query interface.

Usage:
    fhamesh run          # start all agents (requires Redis)
    fhamesh demo         # run a demo scenario (requires Redis)
    fhamesh health       # ping all agents for health status
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import signal
import sys
import uuid
from pathlib import Path
from typing import Any

from .bus.middleware import MessageMiddleware
from .bus.transport import RedisTransport
from .config.loader import ConfigLoader
from .core.message import MessageEnvelope
from .core.registry import AgentRegistry
from .core.types import AgentLayer, MessageType
from .datacore.node import DataCoreNode
from .leaf.node import LeafNode
from .orchestrator.controller import OrchestratorNode
from .security.audit import AuditLogger
from .security.credentials import TokenMinter
from .security.policy import PolicyEngine, RateLimiter
from .security.query_tree_manager import QueryTreeManager
from .security.rbac import RBACEnforcer
from .security.verifier import CredentialVerifier

logger = logging.getLogger("fhamesh.runner")


class MeshRunner:
    """Manages the full lifecycle of a FHAMESH mesh.

    Creates all agents, wires shared services, and runs them as
    concurrent asyncio tasks. Handles graceful shutdown via signals.
    """

    def __init__(self, config_dir: str = "config"):
        self._config_dir = config_dir
        self._config = None
        self._transport: RedisTransport | None = None
        self._audit: AuditLogger | None = None
        self._tree_manager: QueryTreeManager | None = None
        self._registry: AgentRegistry | None = None
        self._agents: list[Any] = []
        self._tasks: list[asyncio.Task] = []
        self._shutdown_event = asyncio.Event()
        self._leaf_minter: TokenMinter | None = None
        self._token_ttl: int = 30

    async def setup(self) -> None:
        """Load config, connect to Redis, initialize all shared services."""
        # Load configuration
        loader = ConfigLoader(self._config_dir)
        self._config = loader.load()

        # Configure logging
        log_level = getattr(logging, self._config.system.log_level.upper(), logging.INFO)
        logging.basicConfig(
            level=log_level,
            format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
            datefmt="%H:%M:%S",
        )

        logger.info("Configuration loaded from %s", self._config_dir)

        # Connect to Redis
        self._transport = RedisTransport(self._config.redis.url)
        await self._transport.connect()
        logger.info("Connected to Redis at %s", self._config.redis.url)

        # Initialize audit logger
        self._audit = AuditLogger(self._config.audit.db_path)
        await self._audit.initialize()

        # Initialize query tree manager
        self._tree_manager = QueryTreeManager(self._audit)

        # Initialize agent registry
        self._registry = AgentRegistry(self._transport.redis)

        # Build security infrastructure
        signing_keys = self._config.security.signing_keys
        leaf_minter = TokenMinter(signing_keys.leaf)
        orch_minter = TokenMinter(signing_keys.orchestrator)
        core_minter = TokenMinter(signing_keys.datacore)
        self._leaf_minter = leaf_minter
        self._token_ttl = self._config.security.token_ttl_seconds

        # All layers share a verifier that knows all keys
        verifier = CredentialVerifier(
            {
                "leaf": signing_keys.leaf,
                "orchestrator": signing_keys.orchestrator,
                "datacore": signing_keys.datacore,
            }
        )

        # Middleware (shared across agents)
        middleware = MessageMiddleware(
            verifier=verifier,
            registry=self._registry,
        )

        # RBAC and policy engine
        policies_dict = self._config.policies.model_dump(by_alias=True)
        rbac = RBACEnforcer.from_config(policies_dict)

        rate_limiter = RateLimiter(
            self._transport.redis,
            requests_per_minute=self._config.policies.rate_limits.global_limit.requests_per_minute,
            burst=self._config.policies.rate_limits.global_limit.burst,
        )

        policy_engine = PolicyEngine(
            rbac=rbac,
            rate_limiter=rate_limiter,
            signing_key=signing_keys.orchestrator,
        )

        # --- Create Agents ---

        # Leaf node
        leaf_config = self._config.leaf.model_dump()
        leaf_config["domains"] = self._config.domains.model_dump()
        leaf_config["agents"] = self._config.agents.model_dump()
        leaf_config["token_ttl_seconds"] = self._config.security.token_ttl_seconds
        leaf = LeafNode(domain="general", config=leaf_config)

        # Orchestrator node
        orch_config = self._config.orchestrator.model_dump()
        orch_config["agents"] = self._config.agents.model_dump()
        orch_config["token_ttl_seconds"] = self._config.security.token_ttl_seconds
        orch = OrchestratorNode(domain="general", config=orch_config)
        orch.set_policy_engine(policy_engine)
        orch.set_rbac(rbac)

        # DataCore node
        dc_config = self._config.datacore.model_dump()
        dc_config["privacy"] = self._config.privacy.differential_privacy.model_dump()
        dc_config["pii"] = self._config.privacy.pii.model_dump()
        dc_config["token_ttl_seconds"] = self._config.security.token_ttl_seconds
        datacore = DataCoreNode(domain="general", config=dc_config)

        self._agents = [leaf, orch, datacore]

        # --- Start agents with their respective transports ---
        # Each agent gets its own transport so pub/sub channels don't collide
        for agent in self._agents:
            transport = RedisTransport(self._config.redis.url)
            await transport.connect()

            # Select the correct minter for the layer
            if agent.layer == AgentLayer.LEAF:
                minter = leaf_minter
            elif agent.layer == AgentLayer.ORCHESTRATOR:
                minter = orch_minter
            else:
                minter = core_minter

            await agent.start(
                transport=transport,
                registry=self._registry,
                middleware=middleware,
                token_minter=minter,
                audit=self._audit,
            )

        logger.info(
            "Agents started: %s",
            [a.agent_id for a in self._agents],
        )

    async def run(self) -> None:
        """Run all agents concurrently. Blocks until shutdown."""
        # Register signal handlers for graceful shutdown
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, self._signal_shutdown)
            except NotImplementedError:
                # Windows doesn't support add_signal_handler
                pass

        # Start agent message loops as tasks
        self._tasks = [asyncio.create_task(agent.run()) for agent in self._agents]

        logger.info("Mesh is running. Press Ctrl+C to stop.")

        # Wait for shutdown signal or task completion
        try:
            await self._shutdown_event.wait()
        except asyncio.CancelledError:
            pass
        finally:
            await self.shutdown()

    async def shutdown(self) -> None:
        """Gracefully stop all agents and close connections."""
        logger.info("Shutting down mesh...")

        for task in self._tasks:
            task.cancel()

        await asyncio.gather(*self._tasks, return_exceptions=True)

        for agent in self._agents:
            try:
                await agent.stop()
            except Exception:
                pass

        if self._audit:
            await self._audit.close()

        if self._transport:
            await self._transport.disconnect()

        logger.info("Mesh stopped.")

    def _signal_shutdown(self) -> None:
        """Handle OS signals for graceful shutdown."""
        self._shutdown_event.set()

    # --- Query interface ---

    async def submit_query(
        self,
        user_input: str,
        user_id: str = "demo_user",
        role: str = "analyst",
    ) -> dict[str, Any] | None:
        """Submit a query through the mesh and wait for a response.

        This creates a message envelope and sends it to the Leaf node,
        then waits for the correlated response.
        """
        if not self._agents:
            raise RuntimeError("Mesh not started. Call setup() first.")

        leaf = self._agents[0]
        correlation_id = uuid.uuid4().hex[:16]

        # Register the runner client in the registry so middleware allows it
        if self._registry:
            await self._registry.register(
                agent_id="runner:client",
                layer="client",
                domain="general",
                channels=[],
            )

        # Mint a zero-trust token for the request
        token = self._leaf_minter.mint(
            issuer_agent_id="runner:client",
            subject_agent_id=leaf.agent_id,
            layer="leaf",
            domain="general",
            allowed_actions=["intent_request", "query"],
            ttl_seconds=self._token_ttl,
            role=role,
            user_id=user_id,
        )

        envelope = MessageEnvelope(
            correlation_id=correlation_id,
            message_type=MessageType.INTENT_REQUEST.value,
            source_agent_id="runner:client",
            target_agent_id=leaf.agent_id,
            auth_token=token.to_json(),
            payload={
                "user_input": user_input,
                "user_id": user_id,
                "role": role,
            },
        )

        # Use the runner's own transport (not the leaf's) for request/reply
        if self._transport is None:
            raise RuntimeError("Runner transport not initialized")

        response = await self._transport.request(envelope, timeout=20.0)

        if response:
            result = dict(response.payload)
            result.pop("_reply_channel", None)
            return result
        return None


async def cmd_run(args: argparse.Namespace) -> None:
    """Run the full mesh."""
    runner = MeshRunner(config_dir=args.config)
    await runner.setup()
    await runner.run()


async def cmd_demo(args: argparse.Namespace) -> None:
    """Run a demo scenario with sample queries."""
    runner = MeshRunner(config_dir=args.config)
    await runner.setup()

    # Start agent loops in background
    tasks = [asyncio.create_task(agent.run()) for agent in runner._agents]

    # Give agents a moment to register
    await asyncio.sleep(0.5)

    demo_queries = [
        ("Show me employee salaries in engineering and departments", "alice", "admin"),
        ("List all products", "bob", "analyst"),
        ("What is the average salary?", "charlie", "viewer"),
        ("Show me all orders above 500", "alice", "analyst"),
    ]

    print("\n" + "=" * 60)
    print("  FHAMESH Demo - Federated Hierarchical Agent Mesh")
    print("=" * 60)

    for query, user_id, role in demo_queries:
        print(f"\n{'-' * 60}")
        print(f"  Query:   {query}")
        print(f"  User:    {user_id} (role: {role})")
        print(f"{'-' * 60}")

        try:
            result = await runner.submit_query(query, user_id=user_id, role=role)
            if result:
                if "result" in result:
                    qr = result["result"]
                    print(f"  Success: {qr.get('success', False)}")
                    if qr.get("data"):
                        data = qr["data"]
                        if isinstance(data, dict) and "rows" in data:
                            rows = data["rows"]
                            print(f"  Rows:    {len(rows)}")
                            for row in rows[:3]:
                                print(f"           {row}")
                            if len(rows) > 3:
                                print(f"           ... and {len(rows) - 3} more")
                        else:
                            print(f"  Data:    {json.dumps(data, indent=2, default=str)[:200]}")
                    if qr.get("privacy_budget_consumed", 0) > 0:
                        print(f"  Privacy: e={qr['privacy_budget_consumed']:.4f} consumed")
                    if qr.get("fields_redacted"):
                        print(f"  Redacted: {qr['fields_redacted']}")
                    if qr.get("noise_applied"):
                        print(f"  Noise:   Applied (differential privacy)")
                    if qr.get("error_message"):
                        print(f"  Error:   {qr['error_message']}")

                    # Show global audit log tree (ASCII art)
                    if runner._tree_manager:
                        corr_ids = await runner._tree_manager.get_all_correlation_ids()
                        if corr_ids:
                            tree = await runner._tree_manager.show_global_tree()
                            for line in tree.split("\n"):
                                print(f"  {line}")
                elif "error" in result:
                    print(f"  Error:   {result['error']}")
                else:
                    print(f"  Result:  {json.dumps(result, default=str)[:200]}")
            else:
                print("  Result:  No response (timeout)")
        except Exception as exc:
            print(f"  Error:   {exc}")

    print(f"\n{'=' * 60}")
    print("  Demo complete.")
    print(f"{'=' * 60}\n")

    # Cleanup
    for task in tasks:
        task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)
    await runner.shutdown()


async def cmd_interactive(args: argparse.Namespace) -> None:
    """Interactive query mode."""
    runner = MeshRunner(config_dir=args.config)
    await runner.setup()

    # Start agent loops in background
    tasks = [asyncio.create_task(agent.run()) for agent in runner._agents]
    await asyncio.sleep(0.5)

    print("\n" + "=" * 60)
    print("  FHAMESH Interactive Mode")
    print("  Type a query and press Enter. Type 'quit' to exit.")
    print("  Format: [user_id:role] query")
    print("  Example: alice:admin Show me employee salaries")
    print("  Default: demo_user:analyst")
    print("=" * 60 + "\n")

    try:
        while True:
            try:
                raw = input("fhamesh> ").strip()
            except EOFError:
                break
            if not raw or raw.lower() in ("quit", "exit", "q"):
                break

            # Parse optional user:role prefix
            user_id, role = "demo_user", "analyst"
            if raw.startswith("[") and "]" in raw:
                prefix, raw = raw.split("]", 1)
                prefix = prefix.lstrip("[").strip()
                raw = raw.strip()
                if ":" in prefix:
                    user_id, role = prefix.split(":", 1)
                else:
                    user_id = prefix

            result = await runner.submit_query(raw, user_id=user_id, role=role)
            if result:
                print(json.dumps(result, indent=2, default=str))
            else:
                print("No response (timeout)")
            print()
    except KeyboardInterrupt:
        print("\nExiting...")

    for task in tasks:
        task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)
    await runner.shutdown()


async def cmd_health(args: argparse.Namespace) -> None:
    """Ping all agents for health status."""
    runner = MeshRunner(config_dir=args.config)
    await runner.setup()

    # Start agent loops briefly for health check
    tasks = [asyncio.create_task(agent.run()) for agent in runner._agents]
    await asyncio.sleep(0.5)

    print("\nAgent Health Status:")
    print("-" * 40)
    for agent in runner._agents:
        try:
            health = await agent.health_check()
            status = health.get("status", "unknown")
            print(f"  {agent.agent_id}: {status}")
        except Exception as exc:
            print(f"  {agent.agent_id}: ERROR ({exc})")
    print("-" * 40)
    print()

    for task in tasks:
        task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)
    await runner.shutdown()


async def cmd_tree(args: argparse.Namespace) -> None:
    """Show the global audit log tree."""
    runner = MeshRunner(config_dir=args.config)
    await runner.setup()

    if runner._tree_manager is None:
        print("Error: Tree manager not initialized")
        await runner.shutdown()
        return

    if args.branch_manager:
        output = await runner._tree_manager.show_branch_manager()
        print(output)
    elif args.watch:
        await runner._tree_manager.stream_live_tree()
    elif args.correlation:
        tree = await runner._tree_manager.show_tree_ascii(args.correlation)
        print(tree)
    else:
        output = await runner._tree_manager.show_global_tree()
        print(output)

    await runner.shutdown()


def build_parser() -> argparse.ArgumentParser:
    """Build the CLI argument parser."""
    parser = argparse.ArgumentParser(
        prog="fhamesh",
        description="Federated Hierarchical Agent Mesh with Zero Trust Orchestration",
    )
    parser.add_argument(
        "--config",
        "-c",
        default="config",
        help="Path to the configuration directory (default: config/)",
    )
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # run
    run_parser = subparsers.add_parser("run", help="Start the mesh (long-running)")
    run_parser.set_defaults(func=cmd_run)

    # demo
    demo_parser = subparsers.add_parser("demo", help="Run a demo scenario")
    demo_parser.set_defaults(func=cmd_demo)

    # interactive
    interactive_parser = subparsers.add_parser(
        "interactive",
        aliases=["i"],
        help="Interactive query mode",
    )
    interactive_parser.set_defaults(func=cmd_interactive)

    # health
    health_parser = subparsers.add_parser("health", help="Check agent health")
    health_parser.set_defaults(func=cmd_health)

    # tree
    tree_parser = subparsers.add_parser("tree", help="Show live audit log tree")
    tree_parser.add_argument("--correlation", "-c", help="Show tree for specific correlation ID")
    tree_parser.add_argument("--watch", "-w", action="store_true", help="Watch mode (live streaming)")
    tree_parser.add_argument("--branch-manager", "-b", action="store_true", help="Show branch manager (cutoffs)")
    tree_parser.set_defaults(func=cmd_tree)

    return parser


def main() -> None:
    """CLI entry point."""
    parser = build_parser()
    args = parser.parse_args()

    if not args.command:
        # Default to demo if no subcommand
        args.command = "demo"
        args.func = cmd_demo

    try:
        asyncio.run(args.func(args))
    except KeyboardInterrupt:
        print("\nInterrupted.")
        sys.exit(0)
    except Exception as exc:
        logger.exception("Fatal error: %s", exc)
        sys.exit(1)


if __name__ == "__main__":
    main()
