"""Tests for the command-level MCP tools (unifi_scan, unifi_health).

These tools are thin wrappers that delegate to agent orchestrators.
Tests verify delegation, argument passthrough, error propagation,
and MCP tool registration.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from unifi.tools.commands import unifi_health, unifi_scan

# ---------------------------------------------------------------------------
# unifi_scan tests
# ---------------------------------------------------------------------------


class TestUnifiScan:
    """Tests for the unifi_scan command tool."""

    async def test_scan_delegates_to_topology_agent(self) -> None:
        """unifi_scan delegates to scan_site and returns its result."""
        mock_scan = AsyncMock(return_value="## Site Scan Complete\nmock report")

        with patch("unifi.agents.topology.scan_site", mock_scan):
            result = await unifi_scan()

        assert result == "## Site Scan Complete\nmock report"

    async def test_scan_default_site_id(self) -> None:
        """unifi_scan passes 'default' site_id when none specified."""
        mock_scan = AsyncMock(return_value="report")

        with patch("unifi.agents.topology.scan_site", mock_scan):
            await unifi_scan()

        mock_scan.assert_called_once_with("default")

    async def test_scan_custom_site_id(self) -> None:
        """unifi_scan passes through a custom site_id."""
        mock_scan = AsyncMock(return_value="report")

        with patch("unifi.agents.topology.scan_site", mock_scan):
            await unifi_scan(site_id="branch-office")

        mock_scan.assert_called_once_with("branch-office")

    async def test_scan_error_propagation(self) -> None:
        """Errors from the topology agent propagate through unifi_scan."""
        mock_scan = AsyncMock(side_effect=RuntimeError("API connection failed"))

        with (
            patch("unifi.agents.topology.scan_site", mock_scan),
            pytest.raises(RuntimeError, match="API connection failed"),
        ):
            await unifi_scan()

    async def test_scan_returns_string(self) -> None:
        """unifi_scan returns a string (the formatted report)."""
        mock_scan = AsyncMock(return_value="## Site Scan Complete\n**Devices:** 3")

        with patch("unifi.agents.topology.scan_site", mock_scan):
            result = await unifi_scan()

        assert isinstance(result, str)

    async def test_scan_empty_site_id_passthrough(self) -> None:
        """An empty string site_id is passed through without modification."""
        mock_scan = AsyncMock(return_value="report")

        with patch("unifi.agents.topology.scan_site", mock_scan):
            await unifi_scan(site_id="")

        mock_scan.assert_called_once_with("")


# ---------------------------------------------------------------------------
# unifi_health tests
# ---------------------------------------------------------------------------


class TestUnifiHealth:
    """Tests for the unifi_health command tool."""

    async def test_health_delegates_to_health_agent(self) -> None:
        """unifi_health delegates to check_health and returns its result."""
        mock_check = AsyncMock(return_value="## Health Check\nAll systems healthy")

        with patch("unifi.agents.health.check_health", mock_check):
            result = await unifi_health()

        assert result == "## Health Check\nAll systems healthy"

    async def test_health_default_site_id(self) -> None:
        """unifi_health passes 'default' site_id when none specified."""
        mock_check = AsyncMock(return_value="report")

        with patch("unifi.agents.health.check_health", mock_check):
            await unifi_health()

        mock_check.assert_called_once_with("default")

    async def test_health_custom_site_id(self) -> None:
        """unifi_health passes through a custom site_id."""
        mock_check = AsyncMock(return_value="report")

        with patch("unifi.agents.health.check_health", mock_check):
            await unifi_health(site_id="warehouse-site")

        mock_check.assert_called_once_with("warehouse-site")

    async def test_health_error_propagation(self) -> None:
        """Errors from the health agent propagate through unifi_health."""
        mock_check = AsyncMock(side_effect=ConnectionError("Gateway unreachable"))

        with (
            patch("unifi.agents.health.check_health", mock_check),
            pytest.raises(ConnectionError, match="Gateway unreachable"),
        ):
            await unifi_health()

    async def test_health_returns_string(self) -> None:
        """unifi_health returns a string (the formatted report)."""
        mock_check = AsyncMock(return_value="## Health Check\n**Devices:** 5")

        with patch("unifi.agents.health.check_health", mock_check):
            result = await unifi_health()

        assert isinstance(result, str)

    async def test_health_empty_site_id_passthrough(self) -> None:
        """An empty string site_id is passed through without modification."""
        mock_check = AsyncMock(return_value="report")

        with patch("unifi.agents.health.check_health", mock_check):
            await unifi_health(site_id="")

        mock_check.assert_called_once_with("")


# ---------------------------------------------------------------------------
# MCP tool registration tests
# ---------------------------------------------------------------------------


class TestToolRegistration:
    """Verify command tools are registered on the MCP server."""

    def test_unifi_scan_registered(self) -> None:
        """unifi_scan is registered as an MCP tool on the server."""
        from unifi.server import mcp_server

        tool_names = [t.name for t in mcp_server._tool_manager._tools.values()]
        assert "unifi_scan" in tool_names

    def test_unifi_health_registered(self) -> None:
        """unifi_health is registered as an MCP tool on the server."""
        from unifi.server import mcp_server

        tool_names = [t.name for t in mcp_server._tool_manager._tools.values()]
        assert "unifi_health" in tool_names

    def test_scan_tool_has_site_id_parameter(self) -> None:
        """unifi_scan tool accepts a site_id parameter."""
        from unifi.server import mcp_server

        tools = {t.name: t for t in mcp_server._tool_manager._tools.values()}
        scan_tool = tools["unifi_scan"]
        schema = scan_tool.parameters
        assert "site_id" in schema.get("properties", {})

    def test_health_tool_has_site_id_parameter(self) -> None:
        """unifi_health tool accepts a site_id parameter."""
        from unifi.server import mcp_server

        tools = {t.name: t for t in mcp_server._tool_manager._tools.values()}
        health_tool = tools["unifi_health"]
        schema = health_tool.parameters
        assert "site_id" in schema.get("properties", {})
