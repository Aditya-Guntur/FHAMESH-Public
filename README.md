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
- **LangGraph Reasoning Agents**: Intent classification, query planning, and result synthesis are real LangGraph agents backed by a local Ollama model — not pattern matching dressed up as "AI". Each one falls back to its deterministic counterpart per-call if the model is unreachable, so the mesh degrades gracefully instead of breaking. See [Reasoning Agents](#reasoning-agents) below.
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
- (Optional) [Ollama](https://ollama.com) running locally, for the LangGraph reasoning agents — without it, the mesh automatically uses the deterministic regex/rule-based backends instead

### Install

```bash
git clone https://github.com/Aditya-Guntur/Federated.git
cd Federated
pip install -e ".[dev]"

# Optional: LangGraph reasoning agents (classification, query planning, synthesis)
pip install -e ".[agents]"
ollama pull llama3.2
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

Tests use `fakeredis` — no real Redis server required, and the LangGraph agent tests mock the LLM boundary — no Ollama server required either. 204 tests covering security, privacy, sanitization, storage, classification, query planning, result synthesis, cross-domain coordination, session memory, streaming, and the full pipeline.

## Project Structure

```
src/fhamesh/
  core/          BaseAgent, MessageEnvelope, types, errors, registry
  security/      ScopedToken, TokenMinter, CredentialVerifier, RBAC, PolicyEngine
  bus/           RedisTransport, ChannelRouter, MessageMiddleware
  leaf/          LeafNode, IntentClassifier (regex), DomainRouter, EligibilityGate,
                 SessionMemory
  orchestrator/  OrchestratorNode, QueryDecomposer (rules), ResultAggregator (merge),
                 DomainSchema, DynamicSchemaRegistry, SubtreeManager, PeerMesh,
                 UncertaintyEstimator
  agents/        LangGraph reasoning agents — classification, query planning,
                 result synthesis, cross-domain coordination — plus their tools
                 and the backend factory that picks LangGraph vs. deterministic
                 per config, with automatic per-call fallback
  datacore/      DataCoreNode, DifferentialPrivacyEngine, PIISanitizer, SQLiteBackend
  config/        ConfigLoader, Pydantic schemas
  runner.py      CLI entry point

config/          YAML configuration files
tests/           unit/, integration/, e2e/
```

## Reasoning Agents

Three places in the mesh make a judgment call instead of following a fixed rule, and each one is a real [LangGraph](https://github.com/langchain-ai/langgraph) agent — stateful, tool-using, with deterministic safety nets — not a single prompt pretending to be one:

| Agent | Where | Graph | Grounded in |
|-------|-------|-------|-------------|
| Classification | Leaf | `recall` → `reason` ⇄ `tools` → `extract` → `calibrate` → `record` | `DynamicSchemaRegistry` (via tools) + `SessionMemory` |
| Query planning | Orchestrator | `plan` ⇄ `tools` → `finalize` → `validate_plan` | `DynamicSchemaRegistry` — known/registered tables & fields, so the model can't invent one |
| Result synthesis | Orchestrator | `merge` (deterministic, unchanged) → `reason` ⇄ `tools` → `synthesize` → `verify` | Already privacy-protected data only — the model never sees raw rows |

Every agent is wrapped behind the same abstract interface its deterministic predecessor used (`BaseClassifier`, `BaseDecomposer`, `BaseAggregator`), and every one falls back to the deterministic implementation for that single call if Ollama is unreachable or returns something unusable — logged as a warning, not a failure.

**Tool use.** Each agent can call real tools mid-reasoning instead of having everything dumped into the prompt up front — `list_domains` / `describe_domain` (classifier, planner) and `compute_percentage_change` / `format_currency` (synthesizer), capped at a few rounds so a model that always wants to call something still terminates.

**Dynamic schema.** `DynamicSchemaRegistry` wraps the static `DomainSchema` with domains registered at runtime (`register_domain(domain, table, actions)`), shared mesh-wide through Redis — add a domain without a redeploy, and the classifier, planner, and policy enforcement all see it immediately.

**Session memory.** `SessionMemory` stores structured turns (domain/action/parameters — never raw text) per user, Redis-backed, TTL'd. The classifier's `recall`/`record` nodes mean "and in sales?" gets classified using the previous turn's domain as context.

**Cross-domain consensus.** When a query genuinely spans more than one domain, `CoordinatorGraph` asks each target domain's own orchestrator (over `PeerMesh`, a real peer-to-peer request — not a shared database) what it actually has, before an LLM negotiates the final plan. No orchestrator ever answers for another domain's data.

**Self-verification.** The synthesizer's `verify` node is an independent second LLM call that fact-checks the drafted summary against the actual data and corrects or drops it if something doesn't hold up — a hallucinated or misrounded number never reaches the user silently.

**Streaming.** Strictly opt-in (`streaming.enabled`, default off, byte-for-byte unchanged behavior when off). A caller using `RedisTransport.request_stream()` gets live `STREAM_CHUNK` text as the synthesizer generates it, ahead of the authoritative, verified response — a fast preview, not a replacement for verification.

Pick the backend per layer, and opt into streaming, in config:

```yaml
leaf:
  classifier:
    backend: "auto"   # auto | langgraph | regex
  streaming:
    enabled: false

orchestrator:
  decomposition:
    backend: "auto"   # auto | langgraph | rules
  aggregation:
    backend: "auto"   # auto | langgraph | merge
  streaming:
    enabled: false

agents:
  ollama:
    model: "llama3.2"
    base_url: "http://localhost:11434"
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
    async def classify(self, text: str) -> IntentDescriptor:
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

Optional (`pip install -e ".[agents]"`), for the LangGraph reasoning agents:

- `langgraph` — agent orchestration graphs
- `langchain-core` — structured LLM output
- `langchain-ollama` — local model client (no API key, no external service)

## License

MIT
