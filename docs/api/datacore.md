# API Reference: Data Core

The `fhamesh.datacore` package implements the backend layer: storage, row-level security, differential privacy, PII redaction, and query validation.

## StorageBackend

Abstract base class for storage backends. Implement this to use PostgreSQL, DynamoDB, or any other data store.

::: fhamesh.datacore.storage.StorageBackend

## SQLiteBackend

Default storage backend using SQLite. Ships with seed data (15 employees, 8 products, 10 orders).

::: fhamesh.datacore.storage.SQLiteBackend

## RLSContext

Row-level security context containing user identity and WHERE predicates to inject into queries.

::: fhamesh.datacore.storage.RLSContext

## DifferentialPrivacyEngine

Adds Laplace noise to numeric query results with per-user epsilon budget tracking.

::: fhamesh.datacore.privacy.DifferentialPrivacyEngine

## PIISanitizer

Detects and masks PII (email, phone, SSN, credit card, IP) in query results.

::: fhamesh.datacore.pii.PIISanitizer

## RowLevelSecurity

Builds `RLSContext` objects with WHERE predicates based on the user's role.

::: fhamesh.datacore.rls.RowLevelSecurity

## QueryValidator

Validates inbound queries against allowed tables and required justification fields.

::: fhamesh.datacore.query_validator.QueryValidator

## DataCoreNode

Top-level data core agent that composes validation, RLS, storage, privacy, and PII redaction into a single pipeline.

::: fhamesh.datacore.node.DataCoreNode
