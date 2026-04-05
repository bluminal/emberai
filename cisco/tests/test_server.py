"""Tests for the Cisco SG-300 MCP server module.

Covers:
- _load_env() with valid env vars and missing required vars
- _mask_host() IP masking
- _mask_password() password masking
- plugin_info() metadata dict
- _parse_args() CLI argument parsing
- ConfigError exception
- JSONFormatter log formatting
- _configure_logging() setup
- mcp_server instance creation
"""

from __future__ import annotations

import json
import logging
import os
from unittest.mock import patch

import pytest

# ---------------------------------------------------------------------------
# _load_env
# ---------------------------------------------------------------------------


class TestLoadEnv:
    """Environment variable loading and validation."""

    def test_load_env_with_all_required_vars(self) -> None:
        env = {
            "CISCO_HOST": "192.168.1.2",
            "CISCO_SSH_USERNAME": "admin",
            "CISCO_SSH_PASSWORD": "s3cret",
        }
        with patch.dict(os.environ, env, clear=True):
            from cisco.server import _load_env

            config = _load_env()
            assert config["CISCO_HOST"] == "192.168.1.2"
            assert config["CISCO_SSH_USERNAME"] == "admin"
            assert config["CISCO_SSH_PASSWORD"] == "s3cret"

    def test_load_env_includes_optional_defaults(self) -> None:
        env = {
            "CISCO_HOST": "192.168.1.2",
            "CISCO_SSH_USERNAME": "admin",
            "CISCO_SSH_PASSWORD": "s3cret",
        }
        with patch.dict(os.environ, env, clear=True):
            from cisco.server import _load_env

            config = _load_env()
            assert config["CISCO_WRITE_ENABLED"] == "false"
            assert config["CISCO_VERIFY_SSH_HOST_KEY"] == "true"
            assert config["NETEX_CACHE_TTL"] == "300"
            assert config["CISCO_SNMP_COMMUNITY"] == "public"

    def test_load_env_optional_override(self) -> None:
        env = {
            "CISCO_HOST": "192.168.1.2",
            "CISCO_SSH_USERNAME": "admin",
            "CISCO_SSH_PASSWORD": "s3cret",
            "CISCO_WRITE_ENABLED": "true",
            "NETEX_CACHE_TTL": "60",
        }
        with patch.dict(os.environ, env, clear=True):
            from cisco.server import _load_env

            config = _load_env()
            assert config["CISCO_WRITE_ENABLED"] == "true"
            assert config["NETEX_CACHE_TTL"] == "60"

    def test_load_env_missing_host_raises_config_error(self) -> None:
        env = {
            "CISCO_SSH_USERNAME": "admin",
            "CISCO_SSH_PASSWORD": "s3cret",
        }
        with patch.dict(os.environ, env, clear=True):
            from cisco.server import ConfigError, _load_env

            with pytest.raises(ConfigError, match="CISCO_HOST"):
                _load_env()

    def test_load_env_missing_all_required_raises_config_error(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            from cisco.server import ConfigError, _load_env

            with pytest.raises(ConfigError) as exc_info:
                _load_env()
            msg = str(exc_info.value)
            assert "CISCO_HOST" in msg
            assert "CISCO_SSH_USERNAME" in msg
            assert "CISCO_SSH_PASSWORD" in msg

    def test_load_env_empty_value_treated_as_missing(self) -> None:
        env = {
            "CISCO_HOST": "  ",
            "CISCO_SSH_USERNAME": "admin",
            "CISCO_SSH_PASSWORD": "s3cret",
        }
        with patch.dict(os.environ, env, clear=True):
            from cisco.server import ConfigError, _load_env

            with pytest.raises(ConfigError, match="CISCO_HOST"):
                _load_env()

    def test_load_env_strips_whitespace(self) -> None:
        env = {
            "CISCO_HOST": "  192.168.1.2  ",
            "CISCO_SSH_USERNAME": "  admin  ",
            "CISCO_SSH_PASSWORD": "  s3cret  ",
        }
        with patch.dict(os.environ, env, clear=True):
            from cisco.server import _load_env

            config = _load_env()
            assert config["CISCO_HOST"] == "192.168.1.2"
            assert config["CISCO_SSH_USERNAME"] == "admin"
            assert config["CISCO_SSH_PASSWORD"] == "s3cret"


# ---------------------------------------------------------------------------
# _mask_host
# ---------------------------------------------------------------------------


class TestMaskHost:
    """IP address masking for logging."""

    def test_mask_ipv4_address(self) -> None:
        from cisco.server import _mask_host

        assert _mask_host("192.168.1.2") == "*.*.*. 2"[:-1] or True
        result = _mask_host("192.168.1.2")
        assert result == "*.*.*.2"

    def test_mask_multiple_octets(self) -> None:
        from cisco.server import _mask_host

        assert _mask_host("10.0.0.1") == "*.*.*.1"

    def test_non_ip_hostname_unchanged(self) -> None:
        from cisco.server import _mask_host

        assert _mask_host("switch.local") == "switch.local"

    def test_empty_string(self) -> None:
        from cisco.server import _mask_host

        assert _mask_host("") == ""

    def test_ip_in_longer_string(self) -> None:
        from cisco.server import _mask_host

        result = _mask_host("host 10.20.30.40 port 22")
        assert "*.*.*.40" in result
        # The non-IP parts should remain
        assert "host" in result


# ---------------------------------------------------------------------------
# _mask_password
# ---------------------------------------------------------------------------


class TestMaskPassword:
    """Password masking for safe logging."""

    def test_mask_long_password(self) -> None:
        from cisco.server import _mask_password

        result = _mask_password("supersecret")
        assert result == "****et"

    def test_mask_short_password(self) -> None:
        from cisco.server import _mask_password

        result = _mask_password("ab")
        assert result == "****"

    def test_mask_single_char_password(self) -> None:
        from cisco.server import _mask_password

        result = _mask_password("x")
        assert result == "****"

    def test_mask_empty_password(self) -> None:
        from cisco.server import _mask_password

        result = _mask_password("")
        assert result == "****"

    def test_mask_three_char_password(self) -> None:
        from cisco.server import _mask_password

        result = _mask_password("abc")
        assert result == "****bc"


# ---------------------------------------------------------------------------
# plugin_info
# ---------------------------------------------------------------------------


class TestPluginInfo:
    """Plugin metadata for Netex Plugin Registry."""

    def test_plugin_info_returns_dict(self) -> None:
        from cisco.server import plugin_info

        info = plugin_info()
        assert isinstance(info, dict)

    def test_plugin_info_name(self) -> None:
        from cisco.server import plugin_info

        info = plugin_info()
        assert info["name"] == "cisco"

    def test_plugin_info_version(self) -> None:
        from cisco.server import plugin_info

        info = plugin_info()
        assert info["version"] == "0.1.0"

    def test_plugin_info_vendor(self) -> None:
        from cisco.server import plugin_info

        info = plugin_info()
        assert info["vendor"] == "cisco"

    def test_plugin_info_has_description(self) -> None:
        from cisco.server import plugin_info

        info = plugin_info()
        assert "description" in info
        assert len(info["description"]) > 0

    def test_plugin_info_roles(self) -> None:
        from cisco.server import plugin_info

        info = plugin_info()
        assert info["roles"] == ["edge"]

    def test_plugin_info_skills(self) -> None:
        from cisco.server import plugin_info

        info = plugin_info()
        assert "topology" in info["skills"]
        assert "health" in info["skills"]
        assert "config" in info["skills"]

    def test_plugin_info_write_flag(self) -> None:
        from cisco.server import plugin_info

        info = plugin_info()
        assert info["write_flag"] == "CISCO_WRITE_ENABLED"

    def test_plugin_info_contract_version(self) -> None:
        from cisco.server import plugin_info

        info = plugin_info()
        assert info["contract_version"] == "1.0.0"

    def test_plugin_info_server_factory_callable(self) -> None:
        from cisco.server import plugin_info

        info = plugin_info()
        assert callable(info["server_factory"])


# ---------------------------------------------------------------------------
# _parse_args
# ---------------------------------------------------------------------------


class TestParseArgs:
    """CLI argument parsing."""

    def test_default_transport_is_stdio(self) -> None:
        from cisco.server import _parse_args

        args = _parse_args([])
        assert args.transport == "stdio"

    def test_http_transport(self) -> None:
        from cisco.server import _parse_args

        args = _parse_args(["--transport", "http"])
        assert args.transport == "http"

    def test_stdio_transport_explicit(self) -> None:
        from cisco.server import _parse_args

        args = _parse_args(["--transport", "stdio"])
        assert args.transport == "stdio"

    def test_check_flag(self) -> None:
        from cisco.server import _parse_args

        args = _parse_args(["--check"])
        assert args.check is True

    def test_check_flag_default_false(self) -> None:
        from cisco.server import _parse_args

        args = _parse_args([])
        assert args.check is False

    def test_log_level_default_none(self) -> None:
        from cisco.server import _parse_args

        args = _parse_args([])
        assert args.log_level is None

    def test_log_level_debug(self) -> None:
        from cisco.server import _parse_args

        args = _parse_args(["--log-level", "DEBUG"])
        assert args.log_level == "DEBUG"

    def test_log_level_warning(self) -> None:
        from cisco.server import _parse_args

        args = _parse_args(["--log-level", "WARNING"])
        assert args.log_level == "WARNING"

    def test_combined_args(self) -> None:
        from cisco.server import _parse_args

        args = _parse_args(["--transport", "http", "--check", "--log-level", "ERROR"])
        assert args.transport == "http"
        assert args.check is True
        assert args.log_level == "ERROR"

    def test_invalid_transport_exits(self) -> None:
        from cisco.server import _parse_args

        with pytest.raises(SystemExit):
            _parse_args(["--transport", "grpc"])

    def test_invalid_log_level_exits(self) -> None:
        from cisco.server import _parse_args

        with pytest.raises(SystemExit):
            _parse_args(["--log-level", "TRACE"])


# ---------------------------------------------------------------------------
# ConfigError
# ---------------------------------------------------------------------------


class TestConfigError:
    """ConfigError exception."""

    def test_config_error_is_exception(self) -> None:
        from cisco.server import ConfigError

        err = ConfigError("missing vars")
        assert isinstance(err, Exception)

    def test_config_error_message(self) -> None:
        from cisco.server import ConfigError

        err = ConfigError("missing CISCO_HOST")
        assert str(err) == "missing CISCO_HOST"


# ---------------------------------------------------------------------------
# JSONFormatter
# ---------------------------------------------------------------------------


class TestJSONFormatter:
    """Structured JSON log formatting."""

    def test_format_basic_log_record(self) -> None:
        from cisco.server import JSONFormatter

        formatter = JSONFormatter()
        record = logging.LogRecord(
            name="cisco.test",
            level=logging.INFO,
            pathname="test.py",
            lineno=1,
            msg="test message",
            args=(),
            exc_info=None,
        )
        output = formatter.format(record)
        data = json.loads(output)
        assert data["level"] == "INFO"
        assert data["logger"] == "cisco.test"
        assert data["message"] == "test message"
        assert "timestamp" in data

    def test_format_with_exception(self) -> None:
        from cisco.server import JSONFormatter

        formatter = JSONFormatter()
        try:
            raise ValueError("test error")
        except ValueError:
            import sys

            exc_info = sys.exc_info()

        record = logging.LogRecord(
            name="cisco.test",
            level=logging.ERROR,
            pathname="test.py",
            lineno=1,
            msg="error occurred",
            args=(),
            exc_info=exc_info,
        )
        output = formatter.format(record)
        data = json.loads(output)
        assert "exception" in data
        assert "ValueError" in data["exception"]

    def test_format_with_extra_component(self) -> None:
        from cisco.server import JSONFormatter

        formatter = JSONFormatter()
        record = logging.LogRecord(
            name="cisco.test",
            level=logging.INFO,
            pathname="test.py",
            lineno=1,
            msg="test",
            args=(),
            exc_info=None,
        )
        record.component = "startup"  # type: ignore[attr-defined]
        output = formatter.format(record)
        data = json.loads(output)
        assert data["component"] == "startup"

    def test_format_with_extra_detail(self) -> None:
        from cisco.server import JSONFormatter

        formatter = JSONFormatter()
        record = logging.LogRecord(
            name="cisco.test",
            level=logging.INFO,
            pathname="test.py",
            lineno=1,
            msg="test",
            args=(),
            exc_info=None,
        )
        record.detail = {"key": "value"}  # type: ignore[attr-defined]
        output = formatter.format(record)
        data = json.loads(output)
        assert data["detail"] == {"key": "value"}


# ---------------------------------------------------------------------------
# _configure_logging
# ---------------------------------------------------------------------------


class TestConfigureLogging:
    """Logging configuration."""

    def test_configure_logging_returns_logger(self) -> None:
        from cisco.server import _configure_logging

        logger = _configure_logging("DEBUG")
        assert isinstance(logger, logging.Logger)
        assert logger.name == "cisco"

    def test_configure_logging_sets_level(self) -> None:
        from cisco.server import _configure_logging

        logger = _configure_logging("WARNING")
        assert logger.level == logging.WARNING

    def test_configure_logging_invalid_level_defaults_to_info(self) -> None:
        from cisco.server import _configure_logging

        logger = _configure_logging("NONEXISTENT")
        assert logger.level == logging.INFO


# ---------------------------------------------------------------------------
# mcp_server instance
# ---------------------------------------------------------------------------


class TestMcpServerInstance:
    """Verify the mcp_server is created with correct attributes."""

    def test_mcp_server_exists(self) -> None:
        from cisco.server import mcp_server

        assert mcp_server is not None

    def test_mcp_server_name(self) -> None:
        from cisco.server import mcp_server

        assert mcp_server.name == "cisco"
