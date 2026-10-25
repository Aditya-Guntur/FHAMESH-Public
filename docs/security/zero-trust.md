# Zero Trust Tokens

FHAMESH enforces zero trust between all agents and layers. Every message carries a `ScopedToken` -- an HMAC-SHA256 signed credential that is verified from scratch at every hop.

## ScopedToken

A `ScopedToken` is an immutable, signed credential with the following fields:

| Field | Type | Description |
|-------|------|-------------|
| `token_id` | `str` | Unique identifier for the token |
| `issuer_agent_id` | `str` | ID of the agent that created the token |
| `subject_agent_id` | `str` | ID of the agent the token is intended for |
| `layer` | `str` | Target layer (`leaf`, `orchestrator`, `datacore`) |
| `domain` | `str` | Business domain the token is scoped to (e.g., `hr`, `finance`) |
| `allowed_actions` | `tuple[str, ...]` | Actions the bearer is authorized to perform |
| `issued_at` | `float` | Unix timestamp when the token was created |
| `expires_at` | `float` | Unix timestamp when the token expires |
| `signature` | `str` | HMAC-SHA256 signature over all other fields |

!!! warning "Short-lived tokens"
    Tokens have a default TTL of 30 seconds (configurable via `security.token_ttl_seconds` in `config/default.yaml`). This limits the window of opportunity for token replay attacks.

## TokenMinter

The `TokenMinter` creates and signs tokens. Each layer has its own signing key configured in `config/default.yaml`:

```yaml
security:
  signing_keys:
    leaf: "change_me_leaf_key_at_least_32_bytes!"
    orchestrator: "change_me_orch_key_at_least_32_bytes!"
    datacore: "change_me_core_key_at_least_32_bytes!"
```

Minting a token:

```python
from fhamesh.security.credentials import TokenMinter

minter = TokenMinter(signing_key="your-secret-key")

token = minter.mint(
    issuer_agent_id="leaf-001",
    subject_agent_id="orchestrator-hr-001",
    layer="orchestrator",
    domain="hr",
    allowed_actions=["query"],
    ttl_seconds=300,
)
```

The signature is computed as `HMAC-SHA256(key, token_id | issuer | subject | layer | domain | actions | issued_at | expires_at)`. Modifying any field invalidates the signature.

## CredentialVerifier

The `CredentialVerifier` runs a 5-step verification chain on every inbound token:

### Step 1: Layer Known

Is the token's target layer recognized? The verifier holds signing keys for all known layers. If the layer is not in the key map, verification fails immediately.

### Step 2: Signature Valid

Recompute the HMAC-SHA256 over all token fields (excluding the signature) using the key for the token's layer. Compare with the stored signature. Any mismatch means the token was tampered with.

### Step 3: Not Expired

Compare `expires_at` against the current time. Expired tokens are rejected regardless of their signature.

### Step 4: Action Authorized

Is the requested action in the token's `allowed_actions` tuple? A token scoped to `["query"]` cannot be used for `"admin_delete"`.

### Step 5: Target Matches

Does the token's `subject_agent_id` match the ID of the receiving agent? Tokens are non-transferable.

```python
from fhamesh.security.verifier import CredentialVerifier

verifier = CredentialVerifier({
    "leaf": signing_key,
    "orchestrator": signing_key,
    "datacore": signing_key,
})

verdict = verifier.verify(token, expected_action="query")
# Returns PolicyVerdict.ALLOW or PolicyVerdict.DENY
```

If any step fails, the verdict is `PolicyVerdict.DENY` and the message is rejected.

## Cross-Layer Isolation

Each layer has its own signing key. A token minted by the leaf layer for the orchestrator layer cannot be reused to access the data core layer because:

1. The `layer` field would not match
2. The signing key would be different
3. The `subject_agent_id` would not match

This prevents lateral movement between layers even if a single key is compromised.

## Token Lifecycle

```
TokenMinter.mint()
       |
       v
  ScopedToken created with signature
       |
       v
  Attached to MessageEnvelope
       |
       v
  Transmitted via RedisTransport
       |
       v
  CredentialVerifier.verify()
       |
       +---> ALLOW: message processed
       |
       +---> DENY: message rejected, audit logged
```

!!! tip "Tamper detection"
    Because `ScopedToken` is a frozen dataclass, any modification creates a new Python object. The HMAC signature on the original object will not match the modified fields, causing verification to fail. See the [Zero Trust Tokens tutorial](../tutorials/zero-trust-tokens.md) for a hands-on demonstration of tamper detection.
