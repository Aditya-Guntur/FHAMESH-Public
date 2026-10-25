# API Reference: Security

The `fhamesh.security` package handles zero trust credentials, RBAC, policy enforcement, auditing, and session management.

## ScopedToken

HMAC-SHA256 signed credential attached to every message. Scoped to a layer, domain, and set of allowed actions.

::: fhamesh.security.credentials.ScopedToken

## TokenMinter

Creates and signs `ScopedToken` instances.

::: fhamesh.security.credentials.TokenMinter

## CredentialVerifier

Runs a 5-step verification chain on inbound tokens: layer known, signature valid, not expired, action authorized, target matches.

::: fhamesh.security.verifier.CredentialVerifier

## RBACEnforcer

Field-level role-based access control with wildcard support and deny-by-default semantics.

::: fhamesh.security.rbac.RBACEnforcer

## Role

Named collection of permissions assigned to a user or agent.

::: fhamesh.security.rbac.Role

## Permission

A single resource/action/field permission tuple.

::: fhamesh.security.rbac.Permission

## PolicyEngine

Combines RBAC checks and rate limiting into a single policy decision. Produces signed `PolicyAttestation` objects.

::: fhamesh.security.policy.PolicyEngine

## AuditLogger

Logs content hashes and security events to the audit trail. Never stores raw data.

::: fhamesh.security.audit.AuditLogger

## SessionManager

Manages authenticated sessions with TTL-based expiry via Redis.

::: fhamesh.security.session.SessionManager
