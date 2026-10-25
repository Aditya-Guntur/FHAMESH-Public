# Tutorial: Zero Trust Tokens

Every message in FHAMESH carries a `ScopedToken` -- an HMAC-SHA256 signed credential scoped to a specific layer, domain, and set of allowed actions. This tutorial covers both token creation and verification, including tamper detection.

## Part 1: Creating Tokens

### Code Example

```python
from fhamesh.security.credentials import TokenMinter

signing_key = "super-secret-key-for-demo"
minter = TokenMinter(signing_key=signing_key)

token = minter.mint(
    issuer_agent_id="leaf-001",
    subject_agent_id="orchestrator-hr-001",
    layer="orchestrator",
    domain="hr",
    allowed_actions=["query"],
    ttl_seconds=300,
)

print(f"Token ID:    {token.token_id}")
print(f"Layer:       {token.layer}")
print(f"Domain:      {token.domain}")
print(f"Actions:     {token.allowed_actions}")
print(f"Issuer:      {token.issuer_agent_id}")
print(f"Subject:     {token.subject_agent_id}")
print(f"Expires at:  {token.expires_at}")
print(f"Signature:   {token.signature[:40]}...")
```

### Expected Output

```
Token ID:    c15dc12b0d14d363
Layer:       orchestrator
Domain:      hr
Actions:     ('query',)
Issuer:      leaf-001
Subject:     orchestrator-hr-001
Expires at:  1771398843.0625215
Signature:   aa781b9d9f6e929842c1f7a3b0e5d812f6...
```

!!! note "Values will differ"
    The `token_id`, `expires_at`, and `signature` will be different on each run because they depend on random generation and the current time.

The signature is an HMAC-SHA256 computed over all token fields (excluding the signature itself). Any modification to any field invalidates the signature.

---

## Part 2: Verification and Tamper Detection

The `CredentialVerifier` runs a 5-step chain on every inbound message: layer known, signature valid, not expired, action authorized, target matches.

### Code Example

```python
import dataclasses
from fhamesh.security.credentials import TokenMinter
from fhamesh.security.verifier import CredentialVerifier

signing_key = "super-secret-key-for-demo"
minter = TokenMinter(signing_key=signing_key)

token = minter.mint(
    issuer_agent_id="leaf-001",
    subject_agent_id="orchestrator-hr-001",
    layer="orchestrator",
    domain="hr",
    allowed_actions=["query"],
    ttl_seconds=300,
)

verifier = CredentialVerifier({
    "leaf": signing_key,
    "orchestrator": signing_key,
    "datacore": signing_key,
})

# Valid token
verdict = verifier.verify(token, expected_action="query")
print(f"Valid token:   {verdict}")     # PolicyVerdict.ALLOW

# Tampered token — change the allowed actions
tampered = dataclasses.replace(token, allowed_actions=("admin_delete",))
verdict = verifier.verify(tampered, expected_action="admin_delete")
print(f"Tampered:      {verdict}")     # PolicyVerdict.DENY (signature mismatch)

# Wrong action requested
verdict = verifier.verify(token, expected_action="admin_delete")
print(f"Wrong action:  {verdict}")     # PolicyVerdict.DENY (action not allowed)
```

### Expected Output

```
Valid token:   PolicyVerdict.ALLOW
Tampered:      PolicyVerdict.DENY     <- HMAC signature no longer matches
Wrong action:  PolicyVerdict.DENY     <- "admin_delete" not in allowed_actions
```

## Explanation

**Valid token**: The token was minted with `allowed_actions=["query"]` and verified with `expected_action="query"`. All 5 steps pass.

**Tampered token**: Using `dataclasses.replace()` creates a new token object with `allowed_actions=("admin_delete",)`, but the original signature was computed over `allowed_actions=("query",)`. The HMAC no longer matches, so verification fails at step 2 (signature valid).

**Wrong action**: The token is unmodified (valid signature), but the requested action `"admin_delete"` is not in the token's `allowed_actions` tuple `("query",)`. Verification fails at step 4 (action authorized).

!!! warning "Trust is never inherited"
    Every hop in the mesh re-verifies from scratch. A token that was valid at the leaf layer does not carry trust to the orchestrator layer -- a new token must be minted with the appropriate signing key for each layer transition.
