"""Tests for PIISanitizer."""

import pytest

from fhamesh.datacore.pii import PIISanitizer


class TestPIISanitizer:
    def setup_method(self):
        self.sanitizer = PIISanitizer()

    def test_redact_email(self):
        data = {"rows": [{"name": "Alice", "email": "alice@company.com"}]}
        result, redacted = self.sanitizer.sanitize(data)
        assert result["rows"][0]["email"] == "***@company.com"
        assert "email" in redacted

    def test_redact_phone(self):
        data = {"rows": [{"name": "Bob", "phone": "555-123-4567"}]}
        result, redacted = self.sanitizer.sanitize(data)
        assert result["rows"][0]["phone"] == "[REDACTED]"
        assert "phone" in redacted

    def test_redact_ssn_last4(self):
        sanitizer = PIISanitizer({"mask_fields": {"ssn": "last4"}})
        data = {"rows": [{"ssn": "123-45-6789"}]}
        result, redacted = sanitizer.sanitize(data)
        assert result["rows"][0]["ssn"] == "***6789"
        assert "ssn" in redacted

    def test_no_redaction_for_safe_fields(self):
        data = {"rows": [{"name": "Charlie", "department": "Engineering"}]}
        result, redacted = self.sanitizer.sanitize(data)
        assert result["rows"][0]["name"] == "Charlie"
        assert result["rows"][0]["department"] == "Engineering"
        assert len(redacted) == 0

    def test_pattern_detection_email_in_value(self):
        data = {"rows": [{"contact": "reach me at user@test.org"}]}
        result, redacted = self.sanitizer.sanitize(data)
        assert "***@" in result["rows"][0]["contact"]

    def test_pattern_detection_ssn_in_value(self):
        data = {"rows": [{"info": "SSN is 123-45-6789"}]}
        result, redacted = self.sanitizer.sanitize(data)
        assert "123-45-6789" not in result["rows"][0]["info"]

    def test_full_redaction_strategy(self):
        sanitizer = PIISanitizer({"mask_fields": {"secret": "full"}})
        data = {"rows": [{"secret": "top_secret_value"}]}
        result, _ = sanitizer.sanitize(data)
        assert result["rows"][0]["secret"] == "[REDACTED]"

    def test_empty_rows(self):
        data = {"rows": []}
        result, redacted = self.sanitizer.sanitize(data)
        assert result["rows"] == []
        assert len(redacted) == 0
