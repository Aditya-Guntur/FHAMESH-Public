# Extending the Framework

FHAMESH is designed to be pluggable. You can replace classifiers, storage backends, and entire agents without modifying core framework code.

## Custom Agents

All agents in the mesh inherit from `BaseAgent`. To create a custom agent, subclass `BaseAgent` and implement the `handle` method.

### BaseAgent Interface

```python
from fhamesh.core.agent import BaseAgent
from fhamesh.core.message import MessageEnvelope


class MyCustomAgent(BaseAgent):
    """A custom agent that processes messages in a specific way."""

    @property
    def agent_id(self) -> str:
        return "my-custom-agent-001"

    @property
    def layer(self) -> str:
        return "orchestrator"  # or "leaf", "datacore"

    async def handle(self, message: MessageEnvelope) -> MessageEnvelope:
        """Process an inbound message and return a response.

        Args:
            message: The inbound MessageEnvelope to process.

        Returns:
            A new MessageEnvelope containing the response.
        """
        # Your custom processing logic here
        result = await self._process(message.payload)

        return message.reply(
            message_type="response",
            payload=result,
            source_agent_id=self.agent_id,
        )

    async def _process(self, payload: dict) -> dict:
        # Custom business logic
        return {"status": "processed", "data": payload}
```

### Registering Your Agent

Register custom agents with the `AgentRegistry` so the mesh can discover and route to them:

```python
from fhamesh.core.registry import AgentRegistry

registry = AgentRegistry()
agent = MyCustomAgent()
registry.register(agent)

# Later, look up agents by ID
found = registry.get("my-custom-agent-001")
```

## Custom Classifiers

The default `IntentClassifier` uses keyword/regex matching. To use an ML model or external service, subclass `BaseClassifier`.

### BaseClassifier Interface

```python
from fhamesh.leaf.classifier import BaseClassifier
from fhamesh.core.message import IntentDescriptor


class MLClassifier(BaseClassifier):
    """Intent classifier backed by a machine learning model."""

    def __init__(self, model_path: str):
        self._model = self._load_model(model_path)

    def classify(self, text: str) -> IntentDescriptor:
        """Classify a user input string into an IntentDescriptor.

        Args:
            text: The sanitized user input.

        Returns:
            An IntentDescriptor with domain, category, action, and confidence.
        """
        prediction = self._model.predict(text)

        return IntentDescriptor(
            domain=prediction["domain"],
            category=prediction["category"],
            action=prediction["action"],
            confidence=prediction["score"],
        )

    def _load_model(self, path: str):
        # Load your model here (scikit-learn, HuggingFace, etc.)
        ...
```

### Using Your Classifier

Pass your custom classifier when constructing a `LeafNode`:

```python
from fhamesh.leaf.node import LeafNode

classifier = MLClassifier(model_path="models/intent_v2.pkl")
leaf = LeafNode(classifier=classifier)
```

!!! tip "No framework changes needed"
    The `LeafNode` accepts any object that implements the `BaseClassifier` interface. You do not need to modify any framework code.

## Custom Storage Backends

The default `SQLiteBackend` uses an in-process SQLite database. To use PostgreSQL, DynamoDB, or any other data store, implement the `StorageBackend` interface.

### StorageBackend Interface

```python
from fhamesh.datacore.storage import StorageBackend, RLSContext


class PostgresBackend(StorageBackend):
    """Storage backend using PostgreSQL."""

    def __init__(self, connection_string: str):
        self._conn_str = connection_string
        self._pool = None

    async def initialize(self) -> None:
        """Set up the connection pool and ensure schema exists."""
        import asyncpg
        self._pool = await asyncpg.create_pool(self._conn_str)

    async def execute(
        self, query: dict, rls_context: RLSContext
    ) -> dict:
        """Execute a query with RLS predicates applied.

        Args:
            query: Structured query dict with table, fields, filters,
                   and optional aggregate.
            rls_context: Row-level security context with WHERE predicates.

        Returns:
            Dict with 'rows' (list of dicts) or 'value' (for aggregates).
        """
        sql, params = self._build_sql(query, rls_context)
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(sql, *params)
            return {"rows": [dict(r) for r in rows]}

    async def close(self) -> None:
        """Close the connection pool."""
        if self._pool:
            await self._pool.close()

    def _build_sql(self, query: dict, rls_context: RLSContext):
        # Build SQL with RLS predicates as WHERE clauses
        ...
```

### Using Your Backend

Pass your custom backend when constructing a `DataCoreNode`:

```python
from fhamesh.datacore.node import DataCoreNode

backend = PostgresBackend("postgresql://user:pass@localhost/mydb")
datacore = DataCoreNode(storage_backend=backend)
```

## Extension Checklist

When creating a custom component, verify:

- [ ] Your class inherits from the correct base class
- [ ] All abstract methods are implemented
- [ ] The component works with `MessageEnvelope` (immutable, frozen dataclass)
- [ ] Security tokens are properly verified/forwarded (do not strip tokens)
- [ ] Your component does not store raw user input (use content hashes for audit)
- [ ] Tests cover both the happy path and error cases
