# API Reference: Core

The `fhamesh.core` package contains the foundational classes used across all layers of the mesh.

## BaseAgent

The abstract base class for all agents in the mesh.

::: fhamesh.core.agent.BaseAgent

## MessageEnvelope

Immutable message container used for all inter-agent communication. Implemented as a frozen dataclass.

::: fhamesh.core.message.MessageEnvelope

## IntentDescriptor

Structured representation of a classified user intent.

::: fhamesh.core.message.IntentDescriptor

## QueryResult

Structured representation of a query result returned from the data core.

::: fhamesh.core.message.QueryResult

## AgentRegistry

Registry for discovering and looking up agents by ID.

::: fhamesh.core.registry.AgentRegistry

## Enums

The following enums are defined in `fhamesh.core.types`:

### AgentLayer

Identifies which layer an agent belongs to: `LEAF`, `ORCHESTRATOR`, or `DATACORE`.

::: fhamesh.core.types.AgentLayer

### IntentCategory

Categorizes user intents: `QUERY`, `COMMAND`, `NAVIGATION`.

::: fhamesh.core.types.IntentCategory

### MessageType

Types of messages in the mesh: `INTENT`, `RESPONSE`, `ERROR`, `HEARTBEAT`.

::: fhamesh.core.types.MessageType

### PolicyVerdict

Result of a policy evaluation: `ALLOW` or `DENY`.

::: fhamesh.core.types.PolicyVerdict

## Errors

Custom exception classes are defined in `fhamesh.core.errors`:

::: fhamesh.core.errors
