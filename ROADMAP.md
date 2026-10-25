# FHAMESH Roadmap

## Current State

FHAMESH is a **working framework** with a complete security pipeline, 116 passing tests, and a demo that runs end-to-end through all three layers. Everything below the line marked "built" works today. Everything below "next" is what turns this from a framework demo into production software.

### What's Built

| Component | Status | Implementation |
|-----------|--------|----------------|
| 3-layer agent architecture | Complete | BaseAgent, LeafNode, OrchestratorNode, DataCoreNode |
| Redis pub/sub transport | Complete | Async transport with request/reply, channel routing |
| Zero-trust tokens | Complete | HMAC-SHA256 signed ScopedTokens on every message |
| RBAC | Complete | Role/field-level permissions, wildcard support |
| Policy engine | Complete | RBAC + rate limiting + signed attestations |
| Input sanitization | Complete | 16+ regex patterns (SQL injection, XSS, prompt injection, etc.) |
| Intent classification | Complete | LangGraph agent (Ollama), tool use + session memory, regex fallback |
| Query planning | Complete | LangGraph agent (Ollama), tool use + dynamic schema, rule-based fallback |
| Result synthesis | Complete | LangGraph agent (Ollama), tool use + self-verification, merge-only fallback |
| Cross-domain consensus | Complete | PeerMesh-backed coordinator agent reconciles multi-domain plans |
| Dynamic schema registry | Complete | Runtime domain registration, Redis-shared, no redeploy needed |
| Session memory | Complete | Structured per-user turn history, Redis-backed, TTL'd |
| Streaming responses | Complete | Opt-in STREAM_CHUNK live synthesis preview |
| Differential privacy | Complete | Laplace mechanism, per-user epsilon budget in Redis |
| PII redaction | Complete | Regex detection, configurable masking strategies |
| Row-level security | Complete | Role-based WHERE predicate injection |
| Subtree decomposition | Complete | Spawn isolated subtrees for complex queries |
| Peer mesh | Complete | Lateral orchestrator communication |
| Audit logging | Complete | SQLite append-only log with content hashes |
| Agent registry | Complete | Redis-backed with TTL heartbeats |
| Configuration | Complete | YAML config with Pydantic validation |
| CLI runner | Complete | `run`, `demo`, `interactive`, `health` commands |
| Documentation | Complete | MkDocs Material site with tutorials and API reference |
| Tests | Complete | 116 unit/integration/e2e tests (fakeredis, no Redis needed) |

---

## Phase 1: Real-World Classification (Replace Keyword Classifier) — Shipped

**Status:** Done. `fhamesh.agents.classifier_graph.LangGraphClassifier` is a
two-node LangGraph agent (`extract` → `calibrate`) backed by Ollama,
selected by default (`leaf.classifier.backend: "auto"`), falling back
to the keyword classifier below per-call if the model is unreachable.
The option picked was closest to "Ollama + local LLM" — free, private,
no API keys — via `langchain-ollama`.

**Goal:** Replace the keyword/regex intent classifier with an actual NLU backend.

The framework already has the plugin point: `BaseClassifier` (abstract class in `fhamesh/leaf/classifier.py`). The current `IntentClassifier` uses keyword matching which works for demos but won't handle real user queries.

### Options (pick one)

| Approach | Pros | Cons |
|----------|------|------|
| **Ollama + local LLM** | Free, private, no API keys | Needs GPU or slow on CPU |
| **HuggingFace Transformers** | Free, many models, offline | Model download size, needs torch |
| **spaCy + custom NER** | Fast, lightweight, trainable | Limited to pattern-based NLU |
| **Sentence-transformers + cosine similarity** | Simple, no fine-tuning needed | Less precise than fine-tuned models |

### What to Build

```python
# Example: create src/fhamesh/leaf/llm_classifier.py
class OllamaClassifier(BaseClassifier):
    """Classify intent using a local Ollama model."""

    def classify(self, text: str) -> IntentDescriptor:
        # Send structured prompt to Ollama
        # Parse response into IntentDescriptor
        ...
```

- Implement one concrete `BaseClassifier` subclass
- Add a config option in `config/leaf.yaml` to select the classifier backend
- Add fallback: if LLM is unavailable, fall back to keyword classifier
- Test with real natural language queries

---

## Phase 2: Real Storage Backend (Replace SQLite)

**Goal:** Replace SQLite with a production database for the DataCore layer.

The plugin point exists: `StorageBackend` (abstract class in `fhamesh/datacore/storage.py`). The current `SQLiteBackend` uses an in-memory database seeded with demo data.

### What to Build

- **PostgreSQL backend** — implement `StorageBackend` using `asyncpg`
- **Schema migration** — use Alembic or a simple migration system
- **Connection pooling** — asyncpg's built-in pool
- **Real data seeding** — configurable data sources instead of hardcoded demo rows

```python
# Example: create src/fhamesh/datacore/pg_storage.py
class PostgresBackend(StorageBackend):
    async def execute_query(self, query, params, rls_context) -> dict:
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(query, *params)
            ...
```

- Add config option in `config/datacore.yaml` to select storage backend
- Row-level security predicates should translate to real SQL WHERE clauses
- Differential privacy and PII redaction work unchanged (they operate on results, not queries)

---

## Phase 3: Multi-Process / Multi-Host Deployment

**Goal:** Run agents as separate processes or on separate machines.

Currently all agents run in a single Python process via `asyncio.create_task()`. The architecture already supports distribution since agents communicate exclusively through Redis pub/sub — no shared memory.

### What to Build

- **Per-agent entry point** — run `fhamesh run --agent leaf --domain hr` to start a single agent
- **Docker Compose** — one container per agent, shared Redis
- **Health monitoring** — the `health` command already works; add Prometheus metrics export
- **Horizontal scaling** — multiple Leaf nodes behind a load balancer, each subscribed to the same channels
- **Agent discovery** — the registry already supports this; add DNS-based or Consul-based discovery as alternatives

### Target Architecture

```
                    Load Balancer
                    /     |     \
              Leaf-1   Leaf-2   Leaf-3      (edge, stateless)
                 \       |       /
                  Redis Cluster
                 /       |       \
           Orch-HR   Orch-Fin   Orch-Gen    (domain orchestrators)
                 \       |       /
                  Redis Cluster
                 /       |       \
           DC-HR      DC-Fin    DC-Gen      (data cores, each owns its data)
```

---

## Phase 4: LLM-Powered Orchestrator — Shipped

**Status:** Query planning and result synthesis are both done, each with
real tool use, and the two originally-flagged gaps (guardrails,
streaming) are closed too.

- Done — `fhamesh.agents.decomposer_graph.LangGraphDecomposer`: a ReAct
  loop (`plan` ⇄ `tools` → `finalize` → `validate_plan`). The model can
  call `list_domains` / `describe_domain` against `DynamicSchemaRegistry`
  instead of guessing, and the LLM only ever sees the already-classified
  `IntentDescriptor` plus schema metadata — never row data, since
  decomposition runs before DataCore executes anything. An invalid
  table/field proposal is corrected by `validate_plan`, not trusted.
- Done — `fhamesh.agents.aggregator_graph.LangGraphAggregator`: `merge`
  (unchanged, deterministic — privacy budget accounting stays exact) →
  `reason ⇄ tools` (can call `compute_percentage_change` /
  `format_currency` instead of doing arithmetic itself) → `synthesize`
  → `verify`.
- Done — **Guardrails**: `verify` is a second, independent structured
  LLM call that fact-checks the drafted summary against the actual
  merged data and corrects or drops it if something doesn't hold up.
  Still a gap: the uncertainty estimator itself runs only on the
  *intent*, before planning — it isn't integrated with `verify`'s
  output.
- Done — **Streaming responses**: `MessageType.STREAM_CHUNK` plus
  `RedisTransport.request_stream()`. Strictly opt-in
  (`leaf.streaming.enabled` + `orchestrator.streaming.enabled`, both
  default `false`) — a plain `request()` caller is unaffected either
  way. `SynthesisGraph.astream()` is a live text preview; the
  authoritative, verified summary still comes from `aggregate()`.
- Also shipped, beyond the original Phase 4 scope — `CoordinatorGraph`:
  when a query genuinely spans more than one domain, each target
  domain's own orchestrator is asked (over `PeerMesh`, not a shared
  database) what it has, before the plan is finalized. And
  `SessionMemory`: the classifier's `recall`/`record` nodes let a
  follow-up question use the previous turn's domain as context,
  without ever storing raw text.
- Every LangGraph agent falls back to its Phase-0/1 deterministic
  implementation per call if Ollama is unreachable.

**Goal:** Let orchestrators use LLMs for query decomposition and result synthesis.

Key constraint (upheld): the LLM never sees raw data. The orchestrator sends structured queries to DataCore and receives privacy-protected results. The LLM only synthesizes the already-sanitized output.

---

## Phase 5: Production Hardening

### Security

- [ ] TLS for Redis connections (currently plaintext)
- [ ] Key rotation for HMAC signing keys (currently static in config)
- [ ] Token refresh mechanism (currently tokens are single-use with short TTL)
- [ ] Rate limiting per user, not just global (the `RateLimiter` supports this, needs wiring)
- [ ] Audit log export to external SIEM (currently SQLite only)

### Reliability

- [ ] Circuit breaker pattern for inter-agent calls (currently just timeouts)
- [ ] Dead letter queue for failed messages
- [ ] Agent crash recovery and automatic restart
- [ ] Redis Sentinel or Cluster support for HA
- [ ] Configurable retry policies with exponential backoff

### Observability

- [ ] OpenTelemetry tracing (trace a query across all three layers)
- [ ] Prometheus metrics (latency, throughput, error rates per agent)
- [ ] Structured JSON logging (currently text-based)
- [ ] Dashboard (Grafana templates)

### Performance

- [ ] Message batching for high-throughput scenarios
- [ ] Connection pooling for Redis (currently one connection per agent)
- [ ] Response caching with privacy-aware cache invalidation
- [ ] Benchmark suite (queries/sec through the full pipeline)

---

## Phase 6: Frontend & API Gateway

**Goal:** Expose the mesh through a REST/WebSocket API for web and mobile clients.

### What to Build

- **FastAPI gateway** — REST endpoints that call `MeshRunner.submit_query()`
- **WebSocket support** — streaming results for long-running queries
- **Authentication** — JWT/OAuth2 at the gateway, mapped to FHAMESH roles
- **Web UI** — simple query interface, result display, audit log viewer
- **API rate limiting** — at the gateway level, before messages enter the mesh

```
Browser/App  →  FastAPI Gateway  →  MeshRunner.submit_query()  →  Leaf  →  ...
```

---

## How the Final Software Should Look

When all phases are complete, FHAMESH is a **secure data query platform** where:

1. **Users** submit natural language questions through a web UI or API
2. **Leaf agents** sanitize input and classify intent using a real NLU model
3. **Orchestrators** plan query execution using LLM reasoning, enforce RBAC, and decompose complex queries into subtrees
4. **Data Cores** execute queries against real databases with row-level security, add calibrated noise for differential privacy, and redact PII before results leave the layer
5. **Every hop** is authenticated with short-lived HMAC tokens, logged in an append-only audit trail, and rate-limited per user
6. **Operators** monitor the mesh through Grafana dashboards with distributed tracing

The core value proposition: **an organization can let users query sensitive data through natural language while mathematically guaranteeing privacy, cryptographically enforcing access control, and maintaining a complete audit trail.**

### Example Production Query Flow

```
User: "What is the average salary in engineering?"

→ Gateway authenticates user (JWT), maps to role "analyst"
→ Leaf sanitizes input (safe), classifies as HR/aggregate query
→ Orchestrator checks RBAC (analyst can read salary aggregates, not individual records)
→ Orchestrator checks rate limit (user has 8/10 queries remaining this minute)
→ DataCore validates query, applies RLS (analyst sees own department only)
→ DataCore executes: SELECT AVG(salary) FROM employees WHERE department='engineering'
→ DataCore adds Laplace noise (epsilon=0.5, budget remaining: 3.2)
→ DataCore redacts any PII in metadata
→ Orchestrator synthesizes: "The average salary in engineering is approximately $142,300"
→ Leaf forwards to user
→ Audit log: query hash, user, role, epsilon consumed, fields accessed, timestamp
```

---

## Priority Order

For someone picking this up:

1. ~~**Phase 1** (classifier)~~ — shipped
2. **Phase 2** (storage) — now the highest-impact remaining item, connects to real data
3. **Phase 5** (hardening) — do in parallel with 2, especially TLS and key rotation
4. **Phase 3** (multi-process) — enables real deployment
5. ~~**Phase 4** (LLM orchestrator)~~ — shipped: planner, synthesizer, tool use, guardrails, streaming, cross-domain consensus, session memory
6. **Phase 6** (frontend) — last mile, makes it usable by non-developers
