# FHAMESH

**Federated Hierarchical Agent Mesh with Zero Trust Orchestration**

A pluggable Python framework for building secure, distributed agent systems. Agents communicate over Redis pub/sub with HMAC-signed tokens on every message, differential privacy on every query result, and PII redaction on every response.

## Architecture

```
┌──────────────────────────────────────────────────────────────────┐
│                        User / External                           │
└──────────────────┬──────────────────────────────────────────────-┘
                   │ raw input
┌──────────────────▼──────────────────────────────────────────────-┐
│  LEAF LAYER         Sanitize → Classify → Route → Gate → Forward │
│  (edge agents)      No data access. No reasoning. Just routing.  │
└──────────────────┬──────────────────────────────────────────────-┘
                   │ IntentDescriptor + ScopedToken
┌──────────────────▼──────────────────────────────────────────────-┐
│  ORCHESTRATOR LAYER   Validate → Uncertainty → Policy → Decompose│
│  (logic controllers)  Spawn subtrees, peer mesh, aggregate       │
└──────────────────┬──────────────────────────────────────────────-┘
                   │ Structured query + PolicyAttestation
┌──────────────────▼──────────────────────────────────────────────-┐
│  DATA CORE LAYER      Validate → RLS → Execute → Privacy → PII  │
│  (high-assurance)     Row-level security, Laplace noise, redact  │
└─────────────────────────────────────────────────────────────────-┘
```

## Key Features

- **Zero Trust**: Every message carries an HMAC-SHA256 signed `ScopedToken`. Trust is never inherited — re-established at every boundary.
- **Pluggable Agents**: Implement `BaseAgent` to create any agent type. Swap in LLM-powered, rule-based, or custom ML agents.
- **Differential Privacy**: Real Laplace mechanism with per-user epsilon budget tracking in Redis.
- **PII Detection**: Regex-based detection with configurable masking (full redaction, last-4, email domain).
- **Row-Level Security**: Role-based query filtering injected as WHERE predicates.
- **Input Sanitization**: 16+ compiled regex patterns for SQL injection, XSS, prompt injection, path traversal, command injection.
- **Recursive Subtrees**: Orchestrators decompose complex queries and spawn isolated subtrees.
- **Peer Mesh**: Lateral communication between orchestrators for consensus and load distribution.
- **Audit Trail**: SQLite append-only log with content hashes (never raw content).
- **RBAC**: Field-level permissions with wildcard support.

## Quick Start

### Prerequisites

- Python 3.12+
- Redis server running on localhost:6379

### Install

```bash
git clone https://github.com/Aditya-Guntur/Federated.git
cd Federated
pip install -e ".[dev]"
```

### Run

```bash
# Start the mesh with a demo scenario
fhamesh demo

# Interactive query mode
fhamesh interactive

# Long-running mesh (agents listen for messages)
fhamesh run

# Health check
fhamesh health
```

### Run Tests (no Redis needed)

```bash
pytest
```

Tests use `fakeredis` — no real Redis server required. 116 tests covering security, privacy, sanitization, storage, classification, and the full pipeline.

## Project Structure

```
src/fhamesh/
  core/          BaseAgent, MessageEnvelope, types, errors, registry
  security/      ScopedToken, TokenMinter, CredentialVerifier, RBAC, PolicyEngine
  bus/           RedisTransport, ChannelRouter, MessageMiddleware
  leaf/          LeafNode, IntentClassifier, DomainRouter, EligibilityGate
  orchestrator/  OrchestratorNode, SubtreeManager, PeerMesh, UncertaintyEstimator
  datacore/      DataCoreNode, DifferentialPrivacyEngine, PIISanitizer, SQLiteBackend
  config/        ConfigLoader, Pydantic schemas
  runner.py      CLI entry point

config/          YAML configuration files
tests/           unit/, integration/, e2e/
```

## Configuration

All config lives in YAML files under `config/`:

| File | Purpose |
|------|---------|
| `default.yaml` | Redis URL, security keys, agent settings |
| `policies.yaml` | RBAC roles, field-level permissions, rate limits |
| `privacy.yaml` | Differential privacy epsilon, budget, field sensitivity |
| `domains.yaml` | Domain routing, intent patterns |

## Extending

### Custom Agent

```python
from fhamesh.core.agent import BaseAgent
from fhamesh.core.message import MessageEnvelope
from fhamesh.core.types import AgentLayer

class MyAgent(BaseAgent):
    def __init__(self):
        super().__init__(layer=AgentLayer.ORCHESTRATOR, domain="custom")

    async def handle_message(self, envelope: MessageEnvelope) -> MessageEnvelope | None:
        # Your logic here
        return envelope.reply(
            message_type="response",
            payload={"result": "done"},
            source_agent_id=self.agent_id,
        )

    async def health_check(self) -> dict:
        return {"status": "ok"}
```

### Custom Classifier

```python
from fhamesh.leaf.classifier import BaseClassifier
from fhamesh.core.message import IntentDescriptor

class MLClassifier(BaseClassifier):
    def classify(self, text: str) -> IntentDescriptor:
        # Your ML model here
        ...
```

### Custom Storage Backend

```python
from fhamesh.datacore.storage import StorageBackend, RLSContext

class PostgresBackend(StorageBackend):
    async def initialize(self): ...
    async def execute(self, query, rls_context): ...
    async def close(self): ...
```

## Security Model

1. **ScopedToken**: Short-lived HMAC-SHA256 signed credential on every message
2. **CredentialVerifier**: 5-step verification chain (layer, signature, expiry, action, target)
3. **PolicyEngine**: RBAC + rate limiting with signed attestations
4. **InputSanitizer**: Blocks SQL injection, XSS, prompt injection at the edge
5. **UncertaintyEstimator**: Detects adversarial inputs via consistency checking
6. **DifferentialPrivacy**: Laplace noise with per-user budget enforcement
7. **PIISanitizer**: Regex-based PII detection and masking
8. **AuditLogger**: Content hashes only — never stores raw user data

## Dependencies

All free, open source, pip-installable:

- `redis` — async pub/sub transport
- `pyyaml` — configuration loading
- `pydantic` — config validation
- `pycryptodome` — HMAC-SHA256
- `aiosqlite` — async SQLite
- `numpy` — Laplace noise generation

## License

MIT
