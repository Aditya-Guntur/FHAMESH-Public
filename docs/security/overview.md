# Security Overview

FHAMESH implements an 8-component security model that spans all three layers of the mesh. Security is not an add-on -- it is built into the message flow at every step.

## Design Principles

- **Zero trust by default** -- no implicit trust between agents, layers, or services
- **Deny by default** -- if a permission is not explicitly granted, access is refused
- **Defense in depth** -- multiple independent security checks at each layer
- **Immutable messages** -- `MessageEnvelope` is a frozen dataclass; tampering creates a new object with an invalid signature
- **Audit everything** -- content hashes logged at every hop; raw data never stored in audit logs

## Security Components

| Component | Layer | Purpose |
|-----------|-------|---------|
| **InputSanitizer** | Leaf | Blocks SQL injection, XSS, prompt injection, path traversal, and command injection using 16+ compiled regex patterns |
| **ScopedToken** | All | HMAC-SHA256 signed credential attached to every message, scoped to a specific layer, domain, and set of allowed actions |
| **TokenMinter** | Leaf, Orchestrator | Creates and signs `ScopedToken` instances with configurable TTL |
| **CredentialVerifier** | Orchestrator, DataCore | 5-step verification chain: layer known, signature valid, not expired, action authorized, target matches |
| **RBACEnforcer** | Orchestrator | Field-level role-based access control with wildcard support |
| **PolicyEngine** | Orchestrator | Combines RBAC and rate limiting into a single policy decision with signed attestations |
| **RowLevelSecurity** | DataCore | Injects WHERE predicates per role so users only see authorized rows |
| **PIISanitizer** | DataCore | Detects and masks PII (email, phone, SSN, credit card, IP) in query results |

## Security Flow

Every request passes through all 8 components in sequence:

```
User Input
  |
  v
[1] InputSanitizer -----> reject if malicious
  |
  v
[2] TokenMinter ---------> mint ScopedToken
  |
  v
[3] CredentialVerifier --> verify token (5-step chain)
  |
  v
[4] UncertaintyEstimator -> reject if adversarial
  |
  v
[5] PolicyEngine --------> RBAC + rate limit check
  |
  v
[6] RowLevelSecurity ----> inject WHERE predicates
  |
  v
[7] DifferentialPrivacy -> add Laplace noise
  |
  v
[8] PIISanitizer --------> mask PII fields
  |
  v
Query Result (sanitized, noised, redacted)
```

!!! note "No single point of failure"
    Each security component operates independently. Bypassing one component does not bypass the others. For example, even if an attacker could forge a token (bypassing CredentialVerifier), they would still face RBAC checks, RLS predicates, differential privacy noise, and PII redaction.

## Detailed Documentation

- [Zero Trust Tokens](zero-trust.md) -- ScopedToken, TokenMinter, CredentialVerifier
- [RBAC](rbac.md) -- Role-based access control, permissions, and rate limits
- [Privacy & PII](privacy.md) -- Differential privacy and PII redaction
