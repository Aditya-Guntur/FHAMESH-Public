"""PII detection and sanitization for query results.

Detects personally identifiable information using regex patterns
and applies masking strategies (full redaction, last-4, email domain).
"""

from __future__ import annotations

import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

# Pre-compiled PII detection patterns
_PII_PATTERNS: dict[str, re.Pattern[str]] = {
    "email": re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}"),
    "phone": re.compile(r"\b\d{3}[-.]?\d{3}[-.]?\d{4}\b"),
    "ssn": re.compile(r"\b\d{3}-\d{2}-\d{4}\b"),
    "credit_card": re.compile(r"\b\d{4}[- ]?\d{4}[- ]?\d{4}[- ]?\d{4}\b"),
    "ip_address": re.compile(r"\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b"),
}


class PIISanitizer:
    """Detects and redacts PII from query results.

    Supports field-level masking strategies:
    - "full": complete redaction -> "[REDACTED]"
    - "last4": keep last 4 characters -> "***-**-6789"
    - "email_domain": keep domain only -> "***@company.com"
    """

    def __init__(self, config: dict[str, Any] | None = None):
        config = config or {}
        self._mask_fields: dict[str, str] = config.get("mask_fields", {
            "ssn": "last4",
            "email": "email_domain",
            "phone": "full",
        })
        self._detect_patterns: bool = config.get("detect_patterns", True)

    def sanitize(self, data: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
        """Sanitize query result data.

        Returns (sanitized_data, list_of_redacted_field_names).
        """
        sanitized = dict(data)
        redacted: list[str] = []

        # Handle row-level results
        if "rows" in data and isinstance(data["rows"], list):
            sanitized_rows = []
            for row in data["rows"]:
                s_row, r_fields = self._sanitize_row(row)
                sanitized_rows.append(s_row)
                redacted.extend(r_fields)
            sanitized["rows"] = sanitized_rows
        else:
            # Handle flat dict results
            for key, value in data.items():
                if key in ("rows", "row_count", "table", "fields",
                           "filters_applied", "aggregate", "noise_applied"):
                    continue
                new_val, was_redacted = self._sanitize_value(key, value)
                if was_redacted:
                    sanitized[key] = new_val
                    redacted.append(key)

        return sanitized, list(set(redacted))

    def _sanitize_row(self, row: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
        """Sanitize a single row."""
        sanitized = {}
        redacted = []

        for key, value in row.items():
            new_val, was_redacted = self._sanitize_value(key, value)
            sanitized[key] = new_val
            if was_redacted:
                redacted.append(key)

        return sanitized, redacted

    def _sanitize_value(self, field_name: str, value: Any) -> tuple[Any, bool]:
        """Sanitize a single field value.

        Returns (sanitized_value, was_redacted).
        """
        if value is None:
            return value, False

        # Explicit mask field
        if field_name in self._mask_fields:
            strategy = self._mask_fields[field_name]
            return self._apply_mask(value, strategy), True

        # Pattern-based detection on string values
        if self._detect_patterns and isinstance(value, str):
            for pii_type, pattern in _PII_PATTERNS.items():
                if pattern.search(value):
                    strategy = self._mask_fields.get(pii_type, "full")
                    return self._apply_mask(value, strategy), True

        return value, False

    def _apply_mask(self, value: Any, strategy: str) -> str:
        """Apply a masking strategy to a value."""
        s = str(value)
        if not s:
            return "[REDACTED]"

        if strategy == "full":
            return "[REDACTED]"

        if strategy == "last4":
            if len(s) <= 4:
                return "[REDACTED]"
            return "***" + s[-4:]

        if strategy == "email_domain":
            if "@" in s:
                domain = s.split("@", 1)[1]
                return f"***@{domain}"
            return "[REDACTED]"

        if strategy == "first_initial":
            return s[0] + "***" if s else "[REDACTED]"

        return "[REDACTED]"
