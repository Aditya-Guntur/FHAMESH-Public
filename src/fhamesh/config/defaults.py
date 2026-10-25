"""Default configuration values.

These are used when no config files are provided. They produce a
working system suitable for local development and testing.
"""

from __future__ import annotations

DEFAULT_CONFIG: dict = {
    "system": {
        "name": "fhamesh",
        "log_level": "INFO",
    },
    "redis": {
        "url": "redis://localhost:6379",
        "session_ttl_seconds": 60,
    },
    "security": {
        "token_ttl_seconds": 30,
        "max_hops": 10,
        "signing_keys": {
            "leaf": "default_leaf_signing_key_change_me!",
            "orchestrator": "default_orch_signing_key_change_me!",
            "datacore": "default_core_signing_key_change_me!",
        },
    },
    "leaf": {
        "sanitizer": {"max_length": 2000},
        "classifier": {"min_confidence": 0.3},
        "eligibility": {"min_confidence": 0.3},
    },
    "orchestrator": {
        "validation": {"max_subtree_depth": 5},
        "uncertainty": {"rejection_threshold": 0.2, "adversarial_threshold": 0.8},
        "subtree": {"timeout_seconds": 30.0},
    },
    "datacore": {
        "db_path": "data.db",
        "query_validation": {
            "require_justification": True,
            "allowed_tables": ["employees", "products", "orders"],
        },
    },
    "audit": {"db_path": "audit.db"},
}
