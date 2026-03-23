"""Tests for the netex MCP server entry point."""

from __future__ import annotations

import json
import logging
from unittest.mock import patch

import pytest

from netex.server import (
    JSONFormatter,
    _configure_logging,
    _load_env,
    _parse_args,
    mcp_server,
    plugin_info,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Remove all netex env vars before each test."""
    for var in (
        "NETEX_WRITE_ENABLED",
        "NETEX_CACHE_TTL",
    ):
        monkeypatch.delenv(var, raising=False)


# ---------------------------------------------------------------------------
# CLI argument parsing
# ---------------------------------------------------------------------------


class TestParseArgs:
    def test_defaults(self) -> None:
        args = _parse_args([])
        assert args.transport == "stdio"
        assert args.check is False
        assert args.log_level is None

    def test_transport_stdio(self) -> None:
        args = _parse_args(["--transport", "stdio"])
        assert args.transport == "stdio"

    def test_transport_http(self) -> None:
        args = _parse_args(["--transport", "http"])
        assert args.transport == "http"

    def test_transport_invalid(self) -> None:
        with pytest.raises(SystemExit):
            _parse_args(["--transport", "grpc"])

    def test_check_flag(self) -> None:
        args = _parse_args(["--check"])
        assert args.check is True

    def test_log_level(self) -> None:
        args = _parse_args(["--log-level", "DEBUG"])
        assert args.log_level == "DEBUG"

    def test_combined_flags(self) -> None:
        args = _parse_args(["--transport", "http", "--log-level", "WARNING"])
        assert args.transport == "http"
        assert args.log_level == "WARNING"
        assert args.check is False


# ---------------------------------------------------------------------------
# Environment loading
# ---------------------------------------------------------------------------


class TestLoadEnv:
    def test_optional_defaults(self) -> None:
        config = _load_env()
        assert config["NETEX_WRITE_ENABLED"] == "false"
        assert config["NETEX_CACHE_TTL"] == "300"

    def test_optional_overrides(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("NETEX_WRITE_ENABLED", "true")
        monkeypatch.setenv("NETEX_CACHE_TTL", "600")

        config = _load_env()
        assert config["NETEX_WRITE_ENABLED"] == "true"
        assert config["NETEX_CACHE_TTL"] == "600"

    def test_values_are_stripped(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("NETEX_WRITE_ENABLED", "  true  ")
        config = _load_env()
        assert config["NETEX_WRITE_ENABLED"] == "true"


# ---------------------------------------------------------------------------
# JSON formatter
# ---------------------------------------------------------------------------


class TestJSONFormatter:
    def test_basic_message(self) -> None:
        formatter = JSONFormatter()
        record = logging.LogRecord(
            "netex", logging.INFO, "server.py", 1, "Server started", (), None
        )
        output = formatter.format(record)
        parsed = json.loads(output)

        assert parsed["level"] == "INFO"
        assert parsed["logger"] == "netex"
        assert parsed["message"] == "Server started"
        assert "timestamp" in parsed

    def test_message_with_args(self) -> None:
        formatter = JSONFormatter()
        record = logging.LogRecord(
            "netex", logging.WARNING, "server.py", 1, "Port %d is busy", (8080,), None
        )
        output = formatter.format(record)
        parsed = json.loads(output)

        assert parsed["message"] == "Port 8080 is busy"

    def test_exception_included(self) -> None:
        formatter = JSONFormatter()
        try:
            raise ValueError("test error")
        except ValueError:
            import sys

            record = logging.LogRecord(
                "netex",
                logging.ERROR,
                "server.py",
                1,
                "Failure",
                (),
                sys.exc_info(),
            )

        output = formatter.format(record)
        parsed = json.loads(output)

        assert "exception" in parsed
        assert "ValueError" in parsed["exception"]

    def test_extra_fields(self) -> None:
        formatter = JSONFormatter()
        record = logging.LogRecord(
            "netex", logging.INFO, "server.py", 1, "Starting", (), None
        )
        record.component = "startup"  # type: ignore[attr-defined]
        record.detail = {"transport": "stdio"}  # type: ignore[attr-defined]

        output = formatter.format(record)
        parsed = json.loads(output)

        assert parsed["component"] == "startup"
        assert parsed["detail"] == {"transport": "stdio"}


# ---------------------------------------------------------------------------
# Logging configuration
# ---------------------------------------------------------------------------


class TestConfigureLogging:
    def test_returns_logger(self) -> None:
        log = _configure_logging("INFO")
        assert isinstance(log, logging.Logger)
        assert log.name == "netex"

    def test_sets_level(self) -> None:
        log = _configure_logging("DEBUG")
        assert log.level == logging.DEBUG

    def test_handler_uses_json_formatter(self) -> None:
        log = _configure_logging("INFO")
        assert any(
            isinstance(h.formatter, JSONFormatter) for h in log.handlers
        )


# ---------------------------------------------------------------------------
# MCP server instance
# ---------------------------------------------------------------------------


class TestMCPServer:
    def test_server_name(self) -> None:
        assert mcp_server.name == "netex"

    def test_server_has_instructions(self) -> None:
        assert mcp_server.instructions is not None
        assert "orchestration" in mcp_server.instructions.lower()


# ---------------------------------------------------------------------------
# plugin_info
# ---------------------------------------------------------------------------


class TestPluginInfo:
    def test_required_fields(self) -> None:
        info = plugin_info()
        required = ["name", "version", "description", "contract_version"]
        for field in required:
            assert field in info, f"Missing field: {field}"

    def test_values(self) -> None:
        info = plugin_info()
        assert info["name"] == "netex"
        assert info["version"] == "0.3.0"
        assert info["contract_version"] == "1.0.0"

    def test_is_orchestrator(self) -> None:
        info = plugin_info()
        assert info["is_orchestrator"] is True

    def test_no_vendor_roles_skills(self) -> None:
        info = plugin_info()
        # Orchestrator should NOT declare vendor, roles, or skills
        assert "vendor" not in info
        assert "roles" not in info
        assert "skills" not in info

    def test_server_factory_returns_server(self) -> None:
        info = plugin_info()
        server = info["server_factory"]()
        assert server is mcp_server


# ---------------------------------------------------------------------------
# main() integration
# ---------------------------------------------------------------------------


class TestMain:
    def test_check_mode_exits(self) -> None:
        """--check should run health probe and exit."""
        from netex.server import main

        with pytest.raises(SystemExit):
            main(["--check"])

    def test_startup_calls_run(self) -> None:
        """With valid config, main() should call mcp_server.run()."""
        from netex.server import main

        with patch.object(mcp_server, "run") as mock_run:
            main(["--transport", "stdio"])
            mock_run.assert_called_once_with(transport="stdio")

    def test_http_transport_maps_correctly(self) -> None:
        """--transport http should map to 'streamable-http'."""
        from netex.server import main

        with patch.object(mcp_server, "run") as mock_run:
            main(["--transport", "http"])
            mock_run.assert_called_once_with(transport="streamable-http")
