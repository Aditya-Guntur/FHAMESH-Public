# Tutorial: Message Envelopes

Every message in the mesh is wrapped in an immutable `MessageEnvelope`. Replies preserve the `correlation_id` for distributed tracing. Each hop increments `hop_count`, which is capped at `max_hops`.

## Code Example

```python
from fhamesh.core.message import MessageEnvelope

# Leaf agent creates the initial message
msg = MessageEnvelope(
    message_type="intent",
    source_agent_id="leaf-001",
    target_agent_id="orchestrator-hr-001",
    correlation_id="trace-abc123",
    payload={"query": "Show me engineering salaries", "domain": "hr"},
)

print(f"Message ID:     {msg.message_id}")
print(f"Correlation ID: {msg.correlation_id}")
print(f"Source:         {msg.source_agent_id}")
print(f"Target:         {msg.target_agent_id}")
print(f"Hop count:      {msg.hop_count}")
print(f"Content hash:   {msg.content_hash()}")
print()

# Orchestrator replies — correlation_id preserved, hop incremented
reply = msg.reply(
    message_type="response",
    payload={"rows": [{"name": "Alice", "salary": 95000}]},
    source_agent_id="orchestrator-hr-001",
)

print(f"Reply target:      {reply.target_agent_id}")
print(f"Correlation ID:    {reply.correlation_id}  (same)")
print(f"Parent message ID: {reply.parent_message_id}")
print(f"Hop count:         {reply.hop_count}")
print()

# Each with_hop() returns a new frozen envelope
hopped = reply.with_hop()
print(f"After with_hop():  hop_count={hopped.hop_count}")
```

## Expected Output

```
Message ID:     d7d0df6c28db4d4a
Correlation ID: trace-abc123
Source:         leaf-001
Target:         orchestrator-hr-001
Hop count:      0
Content hash:   29163ead51da4e58035a287649b6e60f9600475a127beec341eb96e34e9ab700

Reply target:      leaf-001
Correlation ID:    trace-abc123  (same)
Parent message ID: d7d0df6c28db4d4a
Hop count:         1

After with_hop():  hop_count=2
```

!!! note "Values will differ"
    The `message_id` and `content_hash` will be different on each run. The `correlation_id` is preserved across replies.

## Explanation

### Immutable Envelopes

`MessageEnvelope` is a frozen dataclass. Once created, its fields cannot be modified. Operations like `reply()` and `with_hop()` return new envelope objects.

### Correlation ID

The `correlation_id` ties all messages in a request/response chain together. When the orchestrator creates a reply, the `correlation_id` is copied from the original message. This enables distributed tracing across the entire mesh.

### Parent Message ID

The reply's `parent_message_id` is set to the original message's `message_id`. This creates a linked chain: you can trace from any reply back to the original request.

### Hop Count

Each `with_hop()` call returns a new envelope with `hop_count` incremented by 1. The mesh enforces a maximum hop count (default: 10, configurable via `security.max_hops` in `config/default.yaml`). If a message exceeds the maximum, it is rejected to prevent infinite routing loops.

### Content Hash

The `content_hash()` method produces a SHA-256 hash of the envelope's payload. This hash is logged to the audit trail at every hop -- the raw payload is never stored in audit logs.

!!! tip "Distributed tracing"
    Use the `correlation_id` to find all messages related to a single user request across all agents and layers. The `parent_message_id` chain lets you reconstruct the exact sequence of hops.
