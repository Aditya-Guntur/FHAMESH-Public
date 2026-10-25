# FHAMESH

**Federated Hierarchical Agent Mesh with Zero Trust Orchestration**

FHAMESH is a pluggable Python framework for building secure, distributed agent systems. It enforces zero trust security on every message, provides differential privacy on query results, and redacts PII before data leaves the system.

## Key Features

| Feature | Description |
|---------|-------------|
| **Zero Trust** | Every message carries an HMAC-SHA256 signed `ScopedToken`. No implicit trust between layers. |
| **Pluggable Architecture** | Swap classifiers, storage backends, and transport layers without changing core logic. |
| **Differential Privacy** | Laplace noise added to numeric query results with per-user epsilon budget tracking. |
| **PII Redaction** | Automatic detection and masking of emails, phone numbers, SSNs, credit cards, and IPs. |
| **RBAC** | Field-level role-based access control with wildcard support and deny-by-default. |
| **Row-Level Security** | WHERE predicates injected per role so users only see rows they are authorized to access. |
| **Input Sanitization** | 16+ compiled regex patterns block SQL injection, XSS, prompt injection, and more at the edge. |
| **Audit Trail** | Content hashes logged at every hop. Raw data is never stored in audit logs. |

## Architecture Overview

FHAMESH is organized into three layers:

```
                        +------------------+
                        |    User Input    |
                        +--------+---------+
                                 |
                    +------------v-----------+
                    |      LEAF LAYER        |
                    |  Sanitizer, Classifier |
                    |  Router, Gate          |
                    +------------+-----------+
                                 |
                    +------------v-----------+
                    |  ORCHESTRATOR LAYER    |
                    |  Validator, RBAC,      |
                    |  Uncertainty, Policy   |
                    +------------+-----------+
                                 |
                    +------------v-----------+
                    |    DATA CORE LAYER     |
                    |  RLS, Storage, Privacy |
                    |  PII Sanitizer         |
                    +------------+-----------+
                                 |
                        +--------v---------+
                        |   Query Result   |
                        +------------------+
```

**Leaf Layer** handles edge concerns: input sanitization, intent classification, domain routing, and eligibility gating.

**Orchestrator Layer** handles logic: credential verification, RBAC enforcement, uncertainty estimation, subtree decomposition, and peer mesh communication.

**Data Core Layer** handles backend concerns: row-level security, query execution, differential privacy, and PII redaction.

## Quick Install

```bash
pip install -e ".[dev]"
```

Run the test suite (no Redis needed):

```bash
pytest
```

See the [Quick Start](quickstart.md) guide for full setup instructions.

## Documentation Sections

- [Architecture](architecture.md) -- Full architecture details and message flow
- [Quick Start](quickstart.md) -- Installation, CLI commands, and troubleshooting
- [Security](security/overview.md) -- Zero trust, RBAC, privacy, and PII redaction
- [Guides](guides/extending.md) -- Extending the framework and configuration reference
- [Tutorials](tutorials/input-sanitization.md) -- Hands-on walkthroughs of every component
- [API Reference](api/core.md) -- Auto-generated API documentation
