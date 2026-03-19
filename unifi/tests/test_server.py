"""Tests for the UniFi MCP server entry point."""

from __future__ import annotations

import json
import logging
import os
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from unifi.src.server import (
    ConfigError,
    JSONFormatter,
    _check_connectivity,
    _configure_logging,
    _load_env,
    _parse_args,
    _run_check,
    mcp_server,
    plugin_info,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Remove all UniFi/Netex env vars before each test."""
    for var in (
        "UNIFI_LOCAL_HOST",
        "UNIFI_LOCAL_KEY",
        "UNIFI_WRITE_ENABLED",
        "UNIFI_API_KEY",
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
# Environment loading and validation
# ---------------------------------------------------------------------------


class TestLoadEnv:
    def test_all_required_set(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("UNIFI_LOCAL_HOST", "192.168.1.1")
        monkeypatch.setenv("UNIFI_LOCAL_KEY", "secret-key-123")

        config = _load_env()
        assert config["UNIFI_LOCAL_HOST"] == "192.168.1.1"
        assert config["UNIFI_LOCAL_KEY"] == "secret-key-123"

    def test_optional_defaults(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("UNIFI_LOCAL_HOST", "192.168.1.1")
        monkeypatch.setenv("UNIFI_LOCAL_KEY", "secret-key-123")

        config = _load_env()
        assert config["UNIFI_WRITE_ENABLED"] == "false"
        assert config["UNIFI_API_KEY"] == ""
        assert config["NETEX_CACHE_TTL"] == "300"

    def test_optional_overrides(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("UNIFI_LOCAL_HOST", "192.168.1.1")
        monkeypatch.setenv("UNIFI_LOCAL_KEY", "secret-key-123")
        monkeypatch.setenv("UNIFI_WRITE_ENABLED", "true")
        monkeypatch.setenv("UNIFI_API_KEY", "cloud-key-456")
        monkeypatch.setenv("NETEX_CACHE_TTL", "600")

        config = _load_env()
        assert config["UNIFI_WRITE_ENABLED"] == "true"
        assert config["UNIFI_API_KEY"] == "cloud-key-456"
        assert config["NETEX_CACHE_TTL"] == "600"

    def test_missing_local_host(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("UNIFI_LOCAL_KEY", "secret-key-123")

        with pytest.raises(ConfigError, match="UNIFI_LOCAL_HOST"):
            _load_env()

    def test_missing_local_key(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("UNIFI_LOCAL_HOST", "192.168.1.1")

        with pytest.raises(ConfigError, match="UNIFI_LOCAL_KEY"):
            _load_env()

    def test_missing_both_required(self) -> None:
        with pytest.raises(ConfigError) as exc_info:
            _load_env()
        message = str(exc_info.value)
        assert "UNIFI_LOCAL_HOST" in message
        assert "UNIFI_LOCAL_KEY" in message

    def test_empty_string_treated_as_missing(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("UNIFI_LOCAL_HOST", "")
        monkeypatch.setenv("UNIFI_LOCAL_KEY", "key")

        with pytest.raises(ConfigError, match="UNIFI_LOCAL_HOST"):
            _load_env()

    def test_whitespace_only_treated_as_missing(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("UNIFI_LOCAL_HOST", "   ")
        monkeypatch.setenv("UNIFI_LOCAL_KEY", "key")

        with pytest.raises(ConfigError, match="UNIFI_LOCAL_HOST"):
            _load_env()

    def test_values_are_stripped(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("UNIFI_LOCAL_HOST", "  192.168.1.1  ")
        monkeypatch.setenv("UNIFI_LOCAL_KEY", "  key  ")

        config = _load_env()
        assert config["UNIFI_LOCAL_HOST"] == "192.168.1.1"
        assert config["UNIFI_LOCAL_KEY"] == "key"


# ---------------------------------------------------------------------------
# Connectivity check
# ---------------------------------------------------------------------------


class TestCheckConnectivity:
    @pytest.mark.asyncio
    async def test_successful_connection(self) -> None:
        mock_response = httpx.Response(200, request=httpx.Request("GET", "https://192.168.1.1"))

        with patch("unifi.src.server.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.get.return_value = mock_response
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_cls.return_value = mock_client

            ok, detail = await _check_connectivity("192.168.1.1")
            assert ok is True
            assert "HTTP 200" in detail

    @pytest.mark.asyncio
    async def test_connection_refused(self) -> None:
        with patch("unifi.src.server.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.get.side_effect = httpx.ConnectError("Connection refused")
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_cls.return_value = mock_client

            ok, detail = await _check_connectivity("192.168.1.1")
            assert ok is False
            assert "refused" in detail.lower() or "unreachable" in detail.lower()

    @pytest.mark.asyncio
    async def test_connection_timeout(self) -> None:
        with patch("unifi.src.server.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.get.side_effect = httpx.TimeoutException("timed out")
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_cls.return_value = mock_client

            ok, detail = await _check_connectivity("192.168.1.1")
            assert ok is False
            assert "timed out" in detail.lower()

    @pytest.mark.asyncio
    async def test_unexpected_error(self) -> None:
        with patch("unifi.src.server.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.get.side_effect = RuntimeError("something broke")
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_cls.return_value = mock_client

            ok, detail = await _check_connectivity("192.168.1.1")
            assert ok is False
            assert "something broke" in detail

    @pytest.mark.asyncio
    async def test_host_without_scheme_gets_https(self) -> None:
        mock_response = httpx.Response(200, request=httpx.Request("GET", "https://192.168.1.1"))

        with patch("unifi.src.server.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.get.return_value = mock_response
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_cls.return_value = mock_client

            ok, detail = await _check_connectivity("10.0.0.1")
            assert ok is True
            mock_client.get.assert_called_once_with("https://10.0.0.1")

    @pytest.mark.asyncio
    async def test_host_with_http_scheme_preserved(self) -> None:
        mock_response = httpx.Response(
            200, request=httpx.Request("GET", "http://192.168.1.1")
        )

        with patch("unifi.src.server.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.get.return_value = mock_response
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_cls.return_value = mock_client

            ok, detail = await _check_connectivity("http://192.168.1.1")
            assert ok is True
            mock_client.get.assert_called_once_with("http://192.168.1.1")


# ---------------------------------------------------------------------------
# Health check (--check)
# ---------------------------------------------------------------------------


class TestRunCheck:
    def test_all_pass(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        monkeypatch.setenv("UNIFI_LOCAL_HOST", "192.168.1.1")
        monkeypatch.setenv("UNIFI_LOCAL_KEY", "secret-key-123")

        mock_check = AsyncMock(return_value=(True, "HTTP 200"))
        with patch("unifi.src.server._check_connectivity", mock_check):
            exit_code = _run_check()

        assert exit_code == 0
        output = capsys.readouterr().out
        assert "PASSED" in output
        assert "[PASS] UNIFI_LOCAL_HOST" in output
        assert "[PASS] UNIFI_LOCAL_KEY" in output

    def test_missing_env_vars(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        exit_code = _run_check()

        assert exit_code == 1
        output = capsys.readouterr().out
        assert "FAILED" in output
        assert "[FAIL] UNIFI_LOCAL_HOST" in output
        assert "[FAIL] UNIFI_LOCAL_KEY" in output

    def test_gateway_unreachable(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        monkeypatch.setenv("UNIFI_LOCAL_HOST", "192.168.1.1")
        monkeypatch.setenv("UNIFI_LOCAL_KEY", "secret-key-123")

        mock_check = AsyncMock(return_value=(False, "Connection refused"))
        with patch("unifi.src.server._check_connectivity", mock_check):
            exit_code = _run_check()

        assert exit_code == 1
        output = capsys.readouterr().out
        assert "FAILED" in output
        assert "[FAIL] Gateway unreachable" in output

    def test_api_key_masked(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        monkeypatch.setenv("UNIFI_LOCAL_HOST", "192.168.1.1")
        monkeypatch.setenv("UNIFI_LOCAL_KEY", "super-secret-key-12345")

        mock_check = AsyncMock(return_value=(True, "HTTP 200"))
        with patch("unifi.src.server._check_connectivity", mock_check):
            _run_check()

        output = capsys.readouterr().out
        # The key should be masked -- full value should NOT appear
        assert "super-secret-key-12345" not in output
        assert "supe****" in output

    def test_optional_vars_shown(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        monkeypatch.setenv("UNIFI_LOCAL_HOST", "192.168.1.1")
        monkeypatch.setenv("UNIFI_LOCAL_KEY", "secret-key-123")
        monkeypatch.setenv("UNIFI_WRITE_ENABLED", "true")
        monkeypatch.setenv("NETEX_CACHE_TTL", "600")

        mock_check = AsyncMock(return_value=(True, "HTTP 200"))
        with patch("unifi.src.server._check_connectivity", mock_check):
            _run_check()

        output = capsys.readouterr().out
        assert "[INFO] UNIFI_WRITE_ENABLED = true" in output
        assert "[INFO] NETEX_CACHE_TTL = 600" in output

    def test_optional_defaults_shown(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        monkeypatch.setenv("UNIFI_LOCAL_HOST", "192.168.1.1")
        monkeypatch.setenv("UNIFI_LOCAL_KEY", "key")

        mock_check = AsyncMock(return_value=(True, "HTTP 200"))
        with patch("unifi.src.server._check_connectivity", mock_check):
            _run_check()

        output = capsys.readouterr().out
        assert "(default: false)" in output
        assert "(default: 300)" in output

    def test_optional_api_key_masked(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        monkeypatch.setenv("UNIFI_LOCAL_HOST", "192.168.1.1")
        monkeypatch.setenv("UNIFI_LOCAL_KEY", "key")
        monkeypatch.setenv("UNIFI_API_KEY", "cloud-secret-abc")

        mock_check = AsyncMock(return_value=(True, "HTTP 200"))
        with patch("unifi.src.server._check_connectivity", mock_check):
            _run_check()

        output = capsys.readouterr().out
        assert "cloud-secret-abc" not in output
        assert "clou****" in output


# ---------------------------------------------------------------------------
# JSON formatter
# ---------------------------------------------------------------------------


class TestJSONFormatter:
    def test_basic_message(self) -> None:
        formatter = JSONFormatter()
        record = logging.LogRecord(
            "unifi", logging.INFO, "server.py", 1, "Server started", (), None
        )
        output = formatter.format(record)
        parsed = json.loads(output)

        assert parsed["level"] == "INFO"
        assert parsed["logger"] == "unifi"
        assert parsed["message"] == "Server started"
        assert "timestamp" in parsed

    def test_message_with_args(self) -> None:
        formatter = JSONFormatter()
        record = logging.LogRecord(
            "unifi", logging.WARNING, "server.py", 1, "Port %d is busy", (8080,), None
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
                "unifi",
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
        assert "test error" in parsed["exception"]

    def test_extra_fields(self) -> None:
        formatter = JSONFormatter()
        record = logging.LogRecord(
            "unifi", logging.INFO, "server.py", 1, "Starting", (), None
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
        assert log.name == "unifi"

    def test_sets_level(self) -> None:
        log = _configure_logging("DEBUG")
        assert log.level == logging.DEBUG

    def test_handler_uses_json_formatter(self) -> None:
        log = _configure_logging("INFO")
        assert any(
            isinstance(h.formatter, JSONFormatter) for h in log.handlers
        )

    def test_no_duplicate_handlers(self) -> None:
        """Calling _configure_logging multiple times should not add handlers."""
        log = _configure_logging("INFO")
        count_before = len(log.handlers)
        _configure_logging("DEBUG")
        assert len(log.handlers) == count_before


# ---------------------------------------------------------------------------
# MCP server instance
# ---------------------------------------------------------------------------


class TestMCPServer:
    def test_server_name(self) -> None:
        assert mcp_server.name == "unifi"

    def test_server_has_instructions(self) -> None:
        assert mcp_server.instructions is not None
        assert "UniFi" in mcp_server.instructions


# ---------------------------------------------------------------------------
# plugin_info
# ---------------------------------------------------------------------------


class TestPluginInfo:
    def test_required_fields(self) -> None:
        info = plugin_info()
        required = [
            "name",
            "version",
            "vendor",
            "description",
            "roles",
            "skills",
            "write_flag",
            "contract_version",
            "server_factory",
        ]
        for field in required:
            assert field in info, f"Missing field: {field}"

    def test_values(self) -> None:
        info = plugin_info()
        assert info["name"] == "unifi"
        assert info["version"] == "0.1.0"
        assert info["vendor"] == "unifi"
        assert info["write_flag"] == "UNIFI_WRITE_ENABLED"
        assert info["contract_version"] == "1.0.0"

    def test_roles(self) -> None:
        info = plugin_info()
        assert "edge" in info["roles"]
        assert "wireless" in info["roles"]

    def test_skills(self) -> None:
        info = plugin_info()
        expected_skills = [
            "topology",
            "health",
            "wifi",
            "clients",
            "traffic",
            "security",
            "config",
            "multisite",
        ]
        assert info["skills"] == expected_skills

    def test_server_factory_returns_server(self) -> None:
        info = plugin_info()
        server = info["server_factory"]()
        assert server is mcp_server


# ---------------------------------------------------------------------------
# main() integration
# ---------------------------------------------------------------------------


class TestMain:
    def test_check_mode_exits(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """--check should run health probe and exit via SystemExit."""
        from unifi.src.server import main

        # No env vars set -> health check will fail -> exit 1
        with pytest.raises(SystemExit) as exc_info:
            main(["--check"])
        assert exc_info.value.code == 1

    def test_missing_env_exits(self) -> None:
        """Starting without required env vars should exit 1."""
        from unifi.src.server import main

        with pytest.raises(SystemExit) as exc_info:
            main(["--transport", "stdio"])
        assert exc_info.value.code == 1

    def test_startup_calls_run(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """With valid config, main() should call mcp_server.run()."""
        from unifi.src.server import main

        monkeypatch.setenv("UNIFI_LOCAL_HOST", "192.168.1.1")
        monkeypatch.setenv("UNIFI_LOCAL_KEY", "secret-key-123")

        with patch.object(mcp_server, "run") as mock_run:
            main(["--transport", "stdio"])
            mock_run.assert_called_once_with(transport="stdio")

    def test_http_transport_maps_correctly(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """--transport http should map to 'streamable-http' for FastMCP."""
        from unifi.src.server import main

        monkeypatch.setenv("UNIFI_LOCAL_HOST", "192.168.1.1")
        monkeypatch.setenv("UNIFI_LOCAL_KEY", "secret-key-123")

        with patch.object(mcp_server, "run") as mock_run:
            main(["--transport", "http"])
            mock_run.assert_called_once_with(transport="streamable-http")

    def test_log_level_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """--log-level should reconfigure the logger."""
        from unifi.src.server import main

        monkeypatch.setenv("UNIFI_LOCAL_HOST", "192.168.1.1")
        monkeypatch.setenv("UNIFI_LOCAL_KEY", "key")

        with patch.object(mcp_server, "run"):
            main(["--log-level", "DEBUG"])

        log = logging.getLogger("unifi")
        assert log.level == logging.DEBUG
