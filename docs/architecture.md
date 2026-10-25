# Architecture

FHAMESH is structured as a three-layer mesh. Each layer has distinct responsibilities, and messages flow between layers through signed, immutable envelopes.

## Three-Layer Diagram

```
  +-----------------------------------------------------------------+
  |                         USER INPUT                              |
  +-----------------------------------------------------------------+
                                |
  +-----------------------------v-----------------------------------+
  |                        LEAF LAYER                               |
  |                                                                 |
  |  +----------------+  +------------------+  +----------------+   |
  |  | InputSanitizer |->| IntentClassifier |->| DomainRouter   |   |
  |  +----------------+  +------------------+  +----------------+   |
  |                                                   |             |
  |                                          +--------v---------+   |
  |                                          | EligibilityGate  |   |
  |                                          +--------+---------+   |
  +-----------------------------------------------------------------+
                                |
                         ScopedToken minted
                         MessageEnvelope sent
                                |
  +-----------------------------v-----------------------------------+
  |                    ORCHESTRATOR LAYER                            |
  |                                                                 |
  |  +--------------------+  +---------------------+               |
  |  |CredentialVerifier  |->| UncertaintyEstimator|               |
  |  +--------------------+  +---------------------+               |
  |            |                       |                            |
  |  +---------v-----------+  +--------v----------+                |
  |  | QueryDecomposer     |  | PolicyEngine      |                |
  |  +---------+-----------+  | (RBAC + Rate Lim) |                |
  |            |              +--------+----------+                |
  |  +---------v-----------+           |                            |
  |  | SubtreeManager      |<----------+                            |
  |  +---------+-----------+                                       |
  |            |                                                    |
  |  +---------v-----------+                                       |
  |  | PeerMesh            |                                       |
  |  +---------------------+                                       |
  +-----------------------------------------------------------------+
                                |
                         New ScopedToken minted
                         Structured query forwarded
                                |
  +-----------------------------v-----------------------------------+
  |                      DATA CORE LAYER                            |
  |                                                                 |
  |  +----------------+  +----------------+  +-------------------+  |
  |  | QueryValidator |->| RowLevelSec.   |->| SQLiteBackend     |  |
  |  +----------------+  +----------------+  +-------------------+  |
  |                                                   |             |
  |                                          +--------v----------+  |
  |                                          | DiffPrivacyEngine |  |
  |                                          +--------+----------+  |
  |                                                   |             |
  |                                          +--------v----------+  |
  |                                          | PIISanitizer      |  |
  |                                          +-------------------+  |
  +-----------------------------------------------------------------+
                                |
                       QueryResult returned
```

## Leaf Layer

The leaf layer is the edge of the mesh. It is the only layer that touches raw user input.

### InputSanitizer

Runs 16+ compiled regex patterns against every input string. Blocks:

- SQL injection (`UNION SELECT`, `OR 1=1`, `DROP TABLE`)
- XSS (`<script>`, event handlers)
- Prompt injection (`ignore all previous instructions`)
- Path traversal (`../../etc/passwd`)
- Command injection (`; rm -rf /`)

Clean inputs pass through. Rejected inputs get a deterministic content hash logged to the audit trail -- the raw text is never stored.

### IntentClassifier

Maps natural language to a structured `IntentDescriptor` containing:

- **domain** -- which business domain the query belongs to (hr, finance, product, general)
- **category** -- the type of operation (query, command, navigation)
- **action** -- the specific action to perform (lookup_salary, lookup_product, etc.)
- **confidence** -- a float between 0 and 1

The default classifier is keyword/regex-based. Plug in your own ML model by subclassing `BaseClassifier`.

### DomainRouter

Routes classified intents to the correct orchestrator based on the `domain` field. Domain definitions are loaded from `config/domains.yaml`.

### EligibilityGate

Final check before a message leaves the leaf layer:

- Is the user authenticated?
- Is the domain valid?
- Is the action allowed for this domain?
- Does the confidence meet the minimum threshold?

If all checks pass, the gate mints a `ScopedToken` and wraps the intent in a `MessageEnvelope` for the orchestrator.

## Orchestrator Layer

The orchestrator layer handles validation, policy enforcement, and query coordination.

### CredentialVerifier

Runs a 5-step verification chain on every inbound message:

1. **Layer known** -- is the token's target layer recognized?
2. **Signature valid** -- does the HMAC-SHA256 match?
3. **Not expired** -- is the token still within its TTL?
4. **Action authorized** -- is the requested action in `allowed_actions`?
5. **Target matches** -- does the token's subject match the receiving agent?

If any step fails, the verdict is `DENY`.

### UncertaintyEstimator

Scores intents across 4 anomaly dimensions:

- **parameter_plausibility** -- flags suspicious keys (password, exec, token) and parameter counts above 20
- **domain_action_consistency** -- flags mismatched domain-action pairs (e.g., "hr" + "delete_everything")
- **confidence_calibration** -- flags unrealistic confidence scores (e.g., exactly 1.0)
- **category_coherence** -- flags category-action mismatches

If any score exceeds the adversarial threshold, the intent is rejected before reaching the data layer.

### QueryDecomposer

Breaks complex queries into sub-queries that can be routed to different data core nodes or executed in parallel.

### SubtreeManager

Manages the lifecycle of spawned subtrees. Subtrees have a configurable timeout and maximum depth.

### PeerMesh

Enables peer-to-peer communication between orchestrator nodes for distributed coordination.

### PolicyEngine

Combines RBAC checks and rate limiting into a single policy decision. Produces a `PolicyAttestation` that is signed and attached to the outbound message.

## Data Core Layer

The data core layer handles storage, privacy, and PII redaction.

### QueryValidator

Validates inbound queries against the allowed tables list and checks for required justification fields.

### RowLevelSecurity

Builds an `RLSContext` with WHERE predicates based on the user's role. For example, an `engineering_lead` role gets `department = 'engineering'` injected into every query. Admin roles get no predicates (full access).

### SQLiteBackend

The default storage backend. Ships with seed data (15 employees, 8 products, 10 orders). Supports:

- Row queries with field selection and filters
- Aggregate queries (AVG, SUM, COUNT, MIN, MAX)
- RLS predicate injection as additional WHERE clauses

Implement `StorageBackend` to plug in PostgreSQL, DynamoDB, or any other backend.

### DifferentialPrivacyEngine

Adds Laplace noise to numeric query results. Key parameters:

- **epsilon** -- privacy budget per query (lower = more noise = more privacy)
- **sensitivity** -- the maximum change one record can cause in the result
- **budget** -- per-user total epsilon budget, reset on a configurable interval

Noise scale is `sensitivity / epsilon`. When the budget is exhausted, further queries are denied.

### PIISanitizer

Scans every field in query results for PII patterns:

- Email addresses
- Phone numbers
- Social Security numbers
- Credit card numbers
- IP addresses

Applies masking strategies: `full` (complete redaction), `last4` (keep last 4 characters), or `email_domain` (hide local part, keep domain).

## Message Flow

A complete request flows through the system as follows:

1. User input enters the **Leaf Layer**
2. `InputSanitizer` checks for injection attacks
3. `IntentClassifier` produces an `IntentDescriptor`
4. `DomainRouter` selects the target orchestrator
5. `EligibilityGate` validates and mints a `ScopedToken`
6. `MessageEnvelope` is sent to the **Orchestrator Layer**
7. `CredentialVerifier` validates the token (5-step chain)
8. `UncertaintyEstimator` checks for adversarial inputs
9. `PolicyEngine` enforces RBAC and rate limits
10. New `ScopedToken` minted for the **Data Core Layer**
11. `QueryValidator` validates the structured query
12. `RowLevelSecurity` injects WHERE predicates
13. `SQLiteBackend` executes the query
14. `DifferentialPrivacyEngine` adds Laplace noise to numeric fields
15. `PIISanitizer` redacts PII from the results
16. `QueryResult` returns through orchestrator back to the leaf and then to the user

Every hop produces a new `MessageEnvelope` with an incremented `hop_count`. The `correlation_id` ties all messages in a chain together for distributed tracing.

## Pluggable Extension Points

FHAMESH is designed for extensibility. The following components can be replaced:

| Component | Base Class | Purpose |
|-----------|-----------|---------|
| Classifier | `BaseClassifier` | Swap keyword matching for an ML model |
| Storage Backend | `StorageBackend` | Replace SQLite with PostgreSQL, DynamoDB, etc. |
| Transport | `RedisTransport` | Replace Redis pub/sub with Kafka, RabbitMQ, etc. |
| Agent | `BaseAgent` | Create custom agents for any layer |

See the [Extending the Framework](guides/extending.md) guide for implementation details.
