# SPDX-License-Identifier: MIT
"""Tests for the opnsense path parameter validation utility.

Covers:
- Valid UUID values
- Valid alphanumeric IDs
- Valid MAC addresses
- Path traversal attempts (../, /, ..)
- Slash in ID
- Empty string and whitespace-only
- Overly long strings
- Disallowed special characters
- Whitespace stripping behavior
"""

from __future__ import annotations

import pytest

from opnsense.errors import ValidationError
from opnsense.validation import validate_path_param


# ---------------------------------------------------------------------------
# Valid inputs -- should pass through
# ---------------------------------------------------------------------------


class TestValidInputs:
    """Valid path parameter values are accepted and returned cleaned."""

    def test_valid_uuid(self) -> None:
        result = validate_path_param(
            "550e8400-e29b-41d4-a716-446655440000",
            "uuid",
        )
        assert result == "550e8400-e29b-41d4-a716-446655440000"

    def test_valid_uuid_uppercase(self) -> None:
        result = validate_path_param(
            "550E8400-E29B-41D4-A716-446655440000",
            "uuid",
        )
        assert result == "550E8400-E29B-41D4-A716-446655440000"

    def test_valid_alphanumeric_id(self) -> None:
        result = validate_path_param("abc123", "device_id")
        assert result == "abc123"

    def test_valid_id_with_underscores(self) -> None:
        result = validate_path_param("my_device_01", "device_id")
        assert result == "my_device_01"

    def test_valid_id_with_hyphens(self) -> None:
        result = validate_path_param("my-device-01", "device_id")
        assert result == "my-device-01"

    def test_valid_id_with_dots(self) -> None:
        result = validate_path_param("device.local", "device_id")
        assert result == "device.local"

    def test_valid_mac_address_colon_separated(self) -> None:
        result = validate_path_param("AA:BB:CC:DD:EE:FF", "client_mac")
        assert result == "AA:BB:CC:DD:EE:FF"

    def test_valid_mac_address_dash_separated(self) -> None:
        result = validate_path_param("aa-bb-cc-dd-ee-ff", "client_mac")
        assert result == "aa-bb-cc-dd-ee-ff"

    def test_valid_mac_address_no_separator(self) -> None:
        result = validate_path_param("aabbccddeeff", "client_mac")
        assert result == "aabbccddeeff"

    def test_valid_site_id_default(self) -> None:
        result = validate_path_param("default", "site_id")
        assert result == "default"

    def test_strips_whitespace(self) -> None:
        result = validate_path_param("  abc123  ", "device_id")
        assert result == "abc123"

    def test_single_character(self) -> None:
        result = validate_path_param("a", "param")
        assert result == "a"

    def test_numeric_only(self) -> None:
        result = validate_path_param("12345", "param")
        assert result == "12345"

    def test_max_length_128(self) -> None:
        long_id = "a" * 128
        result = validate_path_param(long_id, "param")
        assert result == long_id


# ---------------------------------------------------------------------------
# Path traversal attempts -- must be rejected
# ---------------------------------------------------------------------------


class TestPathTraversal:
    """Path traversal attempts are rejected with ValidationError."""

    def test_dot_dot_slash(self) -> None:
        with pytest.raises(ValidationError, match="path traversal"):
            validate_path_param("../../admin/config", "uuid")

    def test_dot_dot_only(self) -> None:
        with pytest.raises(ValidationError, match="path traversal"):
            validate_path_param("..", "uuid")

    def test_slash_in_id(self) -> None:
        with pytest.raises(ValidationError, match="path traversal"):
            validate_path_param("abc/def", "uuid")

    def test_leading_slash(self) -> None:
        with pytest.raises(ValidationError, match="path traversal"):
            validate_path_param("/etc/passwd", "uuid")

    def test_trailing_slash(self) -> None:
        with pytest.raises(ValidationError, match="path traversal"):
            validate_path_param("abc/", "uuid")

    def test_dot_dot_backtrack(self) -> None:
        with pytest.raises(ValidationError, match="path traversal"):
            validate_path_param("valid-id/../secret", "uuid")

    def test_encoded_traversal_still_has_dots(self) -> None:
        """Even with URL encoding, the raw string has '..' characters."""
        with pytest.raises(ValidationError, match="path traversal"):
            validate_path_param("..%2F..%2Fadmin", "uuid")


# ---------------------------------------------------------------------------
# Empty / whitespace-only
# ---------------------------------------------------------------------------


class TestEmptyInput:
    """Empty or whitespace-only inputs are rejected."""

    def test_empty_string(self) -> None:
        with pytest.raises(ValidationError, match="must not be empty"):
            validate_path_param("", "uuid")

    def test_whitespace_only(self) -> None:
        with pytest.raises(ValidationError, match="must not be empty"):
            validate_path_param("   ", "uuid")

    def test_tab_only(self) -> None:
        with pytest.raises(ValidationError, match="must not be empty"):
            validate_path_param("\t", "uuid")


# ---------------------------------------------------------------------------
# Disallowed characters
# ---------------------------------------------------------------------------


class TestDisallowedCharacters:
    """Inputs with special characters are rejected."""

    def test_spaces_in_middle(self) -> None:
        with pytest.raises(ValidationError, match="disallowed characters"):
            validate_path_param("abc def", "uuid")

    def test_semicolon(self) -> None:
        with pytest.raises(ValidationError, match="disallowed characters"):
            validate_path_param("abc;drop", "uuid")

    def test_angle_brackets(self) -> None:
        with pytest.raises(ValidationError, match="disallowed characters"):
            validate_path_param("<script>", "uuid")

    def test_question_mark(self) -> None:
        with pytest.raises(ValidationError, match="disallowed characters"):
            validate_path_param("id?param=value", "uuid")

    def test_hash(self) -> None:
        with pytest.raises(ValidationError, match="disallowed characters"):
            validate_path_param("id#fragment", "uuid")

    def test_at_sign(self) -> None:
        with pytest.raises(ValidationError, match="disallowed characters"):
            validate_path_param("user@host", "uuid")

    def test_backslash(self) -> None:
        with pytest.raises(ValidationError, match="disallowed characters"):
            validate_path_param("abc\\def", "uuid")


# ---------------------------------------------------------------------------
# Overly long strings
# ---------------------------------------------------------------------------


class TestOverlyLong:
    """Strings exceeding 128 characters (and not matching UUID/MAC) are rejected."""

    def test_129_characters(self) -> None:
        long_id = "a" * 129
        with pytest.raises(ValidationError, match="disallowed characters"):
            validate_path_param(long_id, "param")

    def test_256_characters(self) -> None:
        long_id = "x" * 256
        with pytest.raises(ValidationError, match="disallowed characters"):
            validate_path_param(long_id, "param")


# ---------------------------------------------------------------------------
# Error structure
# ---------------------------------------------------------------------------


class TestErrorStructure:
    """ValidationError carries structured details."""

    def test_error_has_field_detail(self) -> None:
        with pytest.raises(ValidationError) as exc_info:
            validate_path_param("../../admin", "my_param")
        assert exc_info.value.details.get("field") == "my_param"

    def test_error_is_validation_error(self) -> None:
        with pytest.raises(ValidationError):
            validate_path_param("", "uuid")

    def test_param_name_in_message(self) -> None:
        with pytest.raises(ValidationError, match="uuid"):
            validate_path_param("", "uuid")
