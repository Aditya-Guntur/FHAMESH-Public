"""Input sanitization — defensive processing at the edge.

Assumes all user input is adversarial. Detects injection patterns
(SQL, XSS, prompt injection), normalizes Unicode, strips control
characters, and enforces length limits.
"""

from __future__ import annotations

import hashlib
import logging
import re
import unicodedata
from typing import Any

logger = logging.getLogger(__name__)


class InputSanitizer:
    """Defensive input processor. First line of defense in the mesh.

    This is not a simulation — real patterns catch real attacks.
    Extensible: subclass and override _compile_patterns() to add more.
    """

    def __init__(self, config: dict[str, Any] | None = None):
        config = config or {}
        self._max_length: int = config.get("max_length", 2000)
        self._injection_patterns: list[tuple[str, re.Pattern[str]]] = self._compile_patterns()

    def sanitize(self, raw: str) -> tuple[str, bool]:
        """Process raw input.

        Returns (sanitized_text, is_safe).
        is_safe is False if any injection pattern is detected
        or the input violates structural constraints.
        """
        if not raw or not raw.strip():
            return "", False

        if len(raw) > self._max_length:
            logger.warning("Input exceeds max length (%d > %d)", len(raw), self._max_length)
            return "", False

        # Normalize Unicode (NFC form)
        cleaned = self._normalize(raw)

        # Strip control characters (keep newlines, tabs)
        cleaned = self._strip_control_chars(cleaned)

        # Check for injection patterns
        detected = self._detect_injection(cleaned)
        if detected:
            logger.warning("Injection pattern detected: %s", detected)
            return "", False

        return cleaned.strip(), True

    def compute_hash(self, text: str) -> str:
        """SHA-256 hash of the input for audit logging (never store raw text)."""
        return hashlib.sha256(text.encode("utf-8")).hexdigest()

    def _normalize(self, text: str) -> str:
        """Unicode NFC normalization to prevent homoglyph attacks."""
        return unicodedata.normalize("NFC", text)

    def _strip_control_chars(self, text: str) -> str:
        """Remove control characters except newline, tab, carriage return."""
        return "".join(
            ch for ch in text
            if ch in ("\n", "\t", "\r") or not unicodedata.category(ch).startswith("C")
        )

    def _detect_injection(self, text: str) -> str | None:
        """Check for known injection patterns. Returns pattern name or None."""
        lower = text.lower()
        for name, pattern in self._injection_patterns:
            if pattern.search(lower):
                return name
        return None

    def _compile_patterns(self) -> list[tuple[str, re.Pattern[str]]]:
        """Compile injection detection regex patterns.

        Categories:
        - SQL injection
        - XSS / script injection
        - Prompt injection / instruction override
        - Path traversal
        - Command injection
        """
        return [
            # SQL injection patterns
            ("sql_union", re.compile(
                r"\bunion\b\s+(all\s+)?select\b", re.IGNORECASE
            )),
            ("sql_drop", re.compile(
                r"\bdrop\b\s+(table|database|index)\b", re.IGNORECASE
            )),
            ("sql_delete", re.compile(
                r"\bdelete\b\s+from\b", re.IGNORECASE
            )),
            ("sql_insert", re.compile(
                r"\binsert\b\s+into\b", re.IGNORECASE
            )),
            ("sql_update_set", re.compile(
                r"\bupdate\b\s+\w+\s+set\b", re.IGNORECASE
            )),
            ("sql_comment", re.compile(
                r"(--|/\*|\*/|;--)"
            )),
            ("sql_or_bypass", re.compile(
                r"'\s*or\s+'[^']*'\s*=\s*'[^']*'", re.IGNORECASE
            )),
            ("sql_semicolon_cmd", re.compile(
                r";\s*(drop|delete|insert|update|alter|create|exec)\b", re.IGNORECASE
            )),

            # XSS patterns
            ("xss_script", re.compile(
                r"<\s*script\b", re.IGNORECASE
            )),
            ("xss_event_handler", re.compile(
                r"\bon\w+\s*=", re.IGNORECASE
            )),
            ("xss_javascript", re.compile(
                r"javascript\s*:", re.IGNORECASE
            )),
            ("xss_iframe", re.compile(
                r"<\s*iframe\b", re.IGNORECASE
            )),

            # Prompt injection patterns
            ("prompt_ignore", re.compile(
                r"ignore\s+(all\s+)?(previous|above|prior)\s+(instructions?|prompts?|rules?)",
                re.IGNORECASE,
            )),
            ("prompt_override", re.compile(
                r"(system\s+prompt|new\s+instructions?|override\s+rules?|disregard\s+.{0,20}instructions?)",
                re.IGNORECASE,
            )),
            ("prompt_roleplay", re.compile(
                r"(you\s+are\s+now|pretend\s+(to\s+be|you\s+are)|act\s+as\s+(if|a)\b)",
                re.IGNORECASE,
            )),
            ("prompt_jailbreak", re.compile(
                r"(DAN\s+mode|developer\s+mode|jailbreak|do\s+anything\s+now)",
                re.IGNORECASE,
            )),

            # Path traversal
            ("path_traversal", re.compile(
                r"\.\./|\.\.\\|%2e%2e", re.IGNORECASE
            )),

            # Command injection
            ("cmd_injection", re.compile(
                r"[;&|`]\s*(cat|ls|rm|wget|curl|bash|sh|cmd|powershell)\b",
                re.IGNORECASE,
            )),
        ]
