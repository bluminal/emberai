"""Tests for Phase 2 command-level MCP tools (wifi, optimize, secure, config).

Covers Tasks 62-65:
- Task 62: unifi_wifi -- delegates to analyze_wifi
- Task 63: unifi_optimize -- read-only recommendations and write-gated apply mode
- Task 64: unifi_secure -- delegates to security_audit
- Task 65: unifi_config -- delegates to config_review with optional drift param

Tests verify delegation, argument passthrough, error propagation,
MCP tool registration, write gate enforcement for optimize, and
the drift parameter for config.
"""

from __future__ import annotations

import os
from unittest.mock import AsyncMock, patch

import pytest

from unifi.errors import WriteGateError
from unifi.safety import WriteBlockReason
from unifi.tools.commands import (
    unifi_config,
    unifi_optimize,
    unifi_secure,
    unifi_wifi,
)

# ---------------------------------------------------------------------------
# Task 62: unifi_wifi tests
# ---------------------------------------------------------------------------


class TestUnifiWifi:
    """Tests for the unifi_wifi command tool."""

    async def test_wifi_delegates_to_wifi_agent(self) -> None:
        """unifi_wifi delegates to analyze_wifi and returns its result."""
        mock_analyze = AsyncMock(return_value="## WiFi Environment Analysis\nmock report")

        with patch("unifi.agents.wifi.analyze_wifi", mock_analyze):
            result = await unifi_wifi()

        assert result == "## WiFi Environment Analysis\nmock report"

    async def test_wifi_default_site_id(self) -> None:
        """unifi_wifi passes 'default' site_id when none specified."""
        mock_analyze = AsyncMock(return_value="report")

        with patch("unifi.agents.wifi.analyze_wifi", mock_analyze):
            await unifi_wifi()

        mock_analyze.assert_called_once_with("default")

    async def test_wifi_custom_site_id(self) -> None:
        """unifi_wifi passes through a custom site_id."""
        mock_analyze = AsyncMock(return_value="report")

        with patch("unifi.agents.wifi.analyze_wifi", mock_analyze):
            await unifi_wifi(site_id="branch-office")

        mock_analyze.assert_called_once_with("branch-office")

    async def test_wifi_error_propagation(self) -> None:
        """Errors from the wifi agent propagate through unifi_wifi."""
        mock_analyze = AsyncMock(side_effect=RuntimeError("WiFi scan failed"))

        with (
            patch("unifi.agents.wifi.analyze_wifi", mock_analyze),
            pytest.raises(RuntimeError, match="WiFi scan failed"),
        ):
            await unifi_wifi()

    async def test_wifi_returns_string(self) -> None:
        """unifi_wifi returns a string (the formatted report)."""
        mock_analyze = AsyncMock(return_value="## WiFi Analysis\n**APs:** 3")

        with patch("unifi.agents.wifi.analyze_wifi", mock_analyze):
            result = await unifi_wifi()

        assert isinstance(result, str)

    async def test_wifi_empty_site_id_passthrough(self) -> None:
        """An empty string site_id is passed through without modification."""
        mock_analyze = AsyncMock(return_value="report")

        with patch("unifi.agents.wifi.analyze_wifi", mock_analyze):
            await unifi_wifi(site_id="")

        mock_analyze.assert_called_once_with("")


# ---------------------------------------------------------------------------
# Task 63: unifi_optimize tests -- read-only mode
# ---------------------------------------------------------------------------


class TestUnifiOptimizeReadOnly:
    """Tests for unifi_optimize in read-only (plan-only) mode."""

    async def test_optimize_delegates_to_generate_recommendations(self) -> None:
        """Without apply, unifi_optimize calls generate_recommendations."""
        mock_gen = AsyncMock(return_value="## Optimization Recommendations\nmock")

        with patch(
            "unifi.agents.optimize.generate_recommendations",
            mock_gen,
        ):
            result = await unifi_optimize()

        assert result == "## Optimization Recommendations\nmock"
        mock_gen.assert_called_once_with("default")

    async def test_optimize_readonly_default_site_id(self) -> None:
        """unifi_optimize passes 'default' site_id in read-only mode."""
        mock_gen = AsyncMock(return_value="report")

        with patch(
            "unifi.agents.optimize.generate_recommendations",
            mock_gen,
        ):
            await unifi_optimize()

        mock_gen.assert_called_once_with("default")

    async def test_optimize_readonly_custom_site_id(self) -> None:
        """unifi_optimize passes through a custom site_id in read-only mode."""
        mock_gen = AsyncMock(return_value="report")

        with patch(
            "unifi.agents.optimize.generate_recommendations",
            mock_gen,
        ):
            await unifi_optimize(site_id="warehouse")

        mock_gen.assert_called_once_with("warehouse")

    async def test_optimize_readonly_explicit_false(self) -> None:
        """Explicitly passing apply=False routes to generate_recommendations."""
        mock_gen = AsyncMock(return_value="report")
        mock_apply = AsyncMock(return_value="should not be called")

        with (
            patch("unifi.agents.optimize.generate_recommendations", mock_gen),
            patch("unifi.agents.optimize.apply_optimizations", mock_apply),
        ):
            result = await unifi_optimize(apply=False)

        assert result == "report"
        mock_gen.assert_called_once()
        mock_apply.assert_not_called()

    async def test_optimize_readonly_error_propagation(self) -> None:
        """Errors from generate_recommendations propagate through."""
        mock_gen = AsyncMock(side_effect=RuntimeError("Data gathering failed"))

        with (
            patch("unifi.agents.optimize.generate_recommendations", mock_gen),
            pytest.raises(RuntimeError, match="Data gathering failed"),
        ):
            await unifi_optimize()

    async def test_optimize_readonly_returns_string(self) -> None:
        """unifi_optimize returns a string in read-only mode."""
        mock_gen = AsyncMock(return_value="## Recommendations\nNone")

        with patch(
            "unifi.agents.optimize.generate_recommendations",
            mock_gen,
        ):
            result = await unifi_optimize()

        assert isinstance(result, str)


# ---------------------------------------------------------------------------
# Task 63: unifi_optimize tests -- apply mode (write gate enforcement)
# ---------------------------------------------------------------------------


class TestUnifiOptimizeApplyMode:
    """Tests for unifi_optimize with apply=True (write-gated)."""

    async def test_optimize_apply_delegates_to_apply_optimizations(self) -> None:
        """With apply=True, unifi_optimize calls apply_optimizations."""
        mock_apply = AsyncMock(return_value="## Change Plan\nmock plan")

        with (
            patch("unifi.agents.optimize.apply_optimizations", mock_apply),
            patch.dict(os.environ, {"UNIFI_WRITE_ENABLED": "true"}),
        ):
            result = await unifi_optimize(apply=True)

        assert result == "## Change Plan\nmock plan"

    async def test_optimize_apply_passes_site_id(self) -> None:
        """With apply=True, site_id is forwarded to apply_optimizations."""
        mock_apply = AsyncMock(return_value="plan")

        with (
            patch("unifi.agents.optimize.apply_optimizations", mock_apply),
            patch.dict(os.environ, {"UNIFI_WRITE_ENABLED": "true"}),
        ):
            await unifi_optimize(site_id="branch", apply=True)

        mock_apply.assert_called_once_with("branch", apply=True)

    async def test_optimize_apply_blocked_when_env_var_disabled(self) -> None:
        """apply_optimizations raises WriteGateError when UNIFI_WRITE_ENABLED is not true."""
        from unifi.agents.optimize import apply_optimizations

        with (
            patch.dict(os.environ, {"UNIFI_WRITE_ENABLED": "false"}, clear=False),
            pytest.raises(WriteGateError) as exc_info,
        ):
            await apply_optimizations("default", apply=True)

        assert exc_info.value.reason == WriteBlockReason.ENV_VAR_DISABLED

    async def test_optimize_apply_blocked_when_env_var_unset(self) -> None:
        """apply_optimizations raises WriteGateError when UNIFI_WRITE_ENABLED is unset."""
        from unifi.agents.optimize import apply_optimizations

        with (
            patch.dict(os.environ, {}, clear=True),
            pytest.raises(WriteGateError) as exc_info,
        ):
            await apply_optimizations("default", apply=True)

        assert exc_info.value.reason == WriteBlockReason.ENV_VAR_DISABLED

    async def test_optimize_apply_blocked_when_apply_false(self) -> None:
        """apply_optimizations raises WriteGateError when apply=False."""
        from unifi.agents.optimize import apply_optimizations

        with (
            patch.dict(os.environ, {"UNIFI_WRITE_ENABLED": "true"}),
            pytest.raises(WriteGateError) as exc_info,
        ):
            await apply_optimizations("default", apply=False)

        assert exc_info.value.reason == WriteBlockReason.APPLY_FLAG_MISSING

    async def test_optimize_apply_blocked_when_apply_omitted(self) -> None:
        """apply_optimizations raises WriteGateError when apply is omitted (defaults to False)."""
        from unifi.agents.optimize import apply_optimizations

        with (
            patch.dict(os.environ, {"UNIFI_WRITE_ENABLED": "true"}),
            pytest.raises(WriteGateError) as exc_info,
        ):
            await apply_optimizations("default")

        assert exc_info.value.reason == WriteBlockReason.APPLY_FLAG_MISSING

    async def test_optimize_env_var_takes_priority_over_apply_flag(self) -> None:
        """When env var is disabled, error is ENV_VAR_DISABLED even with apply=False."""
        from unifi.agents.optimize import apply_optimizations

        with (
            patch.dict(os.environ, {}, clear=True),
            pytest.raises(WriteGateError) as exc_info,
        ):
            await apply_optimizations("default", apply=False)

        assert exc_info.value.reason == WriteBlockReason.ENV_VAR_DISABLED

    async def test_optimize_write_gate_error_has_plugin_name(self) -> None:
        """WriteGateError from optimize carries plugin_name='UNIFI'."""
        from unifi.agents.optimize import apply_optimizations

        with (
            patch.dict(os.environ, {}, clear=True),
            pytest.raises(WriteGateError) as exc_info,
        ):
            await apply_optimizations("default", apply=True)

        assert exc_info.value.plugin_name == "UNIFI"

    async def test_optimize_write_gate_error_has_env_var(self) -> None:
        """WriteGateError from optimize carries env_var='UNIFI_WRITE_ENABLED'."""
        from unifi.agents.optimize import apply_optimizations

        with (
            patch.dict(os.environ, {}, clear=True),
            pytest.raises(WriteGateError) as exc_info,
        ):
            await apply_optimizations("default", apply=True)

        assert exc_info.value.env_var == "UNIFI_WRITE_ENABLED"


# ---------------------------------------------------------------------------
# Task 63: unifi_optimize tests -- generate_recommendations unit tests
# ---------------------------------------------------------------------------


class TestGenerateRecommendations:
    """Tests for the generate_recommendations agent function."""

    async def test_returns_string(self) -> None:
        """generate_recommendations returns a markdown string."""
        from unifi.agents.optimize import generate_recommendations

        with (
            patch("unifi.agents.optimize._gather_wifi_data", AsyncMock(return_value=[])),
            patch("unifi.agents.optimize._gather_security_data", AsyncMock(return_value=[])),
            patch("unifi.agents.optimize._gather_config_data", AsyncMock(return_value=[])),
            patch("unifi.agents.optimize._gather_traffic_data", AsyncMock(return_value=[])),
        ):
            result = await generate_recommendations("default")

        assert isinstance(result, str)
        assert "Optimization Recommendations" in result

    async def test_includes_write_status(self) -> None:
        """generate_recommendations includes write status in output."""
        from unifi.agents.optimize import generate_recommendations

        with (
            patch("unifi.agents.optimize._gather_wifi_data", AsyncMock(return_value=[])),
            patch("unifi.agents.optimize._gather_security_data", AsyncMock(return_value=[])),
            patch("unifi.agents.optimize._gather_config_data", AsyncMock(return_value=[])),
            patch("unifi.agents.optimize._gather_traffic_data", AsyncMock(return_value=[])),
            patch.dict(os.environ, {}, clear=True),
        ):
            result = await generate_recommendations("default")

        assert "read-only" in result.lower()

    async def test_shows_no_recommendations_when_healthy(self) -> None:
        """generate_recommendations shows healthy message when no findings."""
        from unifi.agents.optimize import generate_recommendations

        with (
            patch("unifi.agents.optimize._gather_wifi_data", AsyncMock(return_value=[])),
            patch("unifi.agents.optimize._gather_security_data", AsyncMock(return_value=[])),
            patch("unifi.agents.optimize._gather_config_data", AsyncMock(return_value=[])),
            patch("unifi.agents.optimize._gather_traffic_data", AsyncMock(return_value=[])),
        ):
            result = await generate_recommendations("default")

        assert "healthy" in result.lower() or "no recommendations" in result.lower()

    async def test_includes_findings_from_all_agents(self) -> None:
        """generate_recommendations aggregates findings from all four agents."""
        from unifi.agents.optimize import generate_recommendations
        from unifi.output import Finding, Severity

        wifi_finding = Finding(
            severity=Severity.WARNING,
            title="AP-1 2.4 GHz at 75%",
            detail="High channel utilization.",
            recommendation="Change channel.",
        )
        security_finding = Finding(
            severity=Severity.HIGH,
            title="Sensitive port 22 exposed",
            detail="SSH port forward active.",
            recommendation="Use VPN instead.",
        )

        mock_wifi = AsyncMock(return_value=[wifi_finding])
        mock_sec = AsyncMock(return_value=[security_finding])
        mock_cfg = AsyncMock(return_value=[])
        mock_trf = AsyncMock(return_value=[])

        with (
            patch("unifi.agents.optimize._gather_wifi_data", mock_wifi),
            patch("unifi.agents.optimize._gather_security_data", mock_sec),
            patch("unifi.agents.optimize._gather_config_data", mock_cfg),
            patch("unifi.agents.optimize._gather_traffic_data", mock_trf),
        ):
            result = await generate_recommendations("default")

        assert "AP-1" in result
        assert "port 22" in result or "SSH" in result


# ---------------------------------------------------------------------------
# Task 63: unifi_optimize tests -- apply_optimizations unit tests
# ---------------------------------------------------------------------------


class TestApplyOptimizations:
    """Tests for the apply_optimizations agent function."""

    async def test_returns_change_plan_when_findings_exist(self) -> None:
        """apply_optimizations returns a change plan when there are findings."""
        from unifi.agents.optimize import apply_optimizations
        from unifi.output import Finding, Severity

        finding = Finding(
            severity=Severity.WARNING,
            title="No recent backup",
            detail="No backup timestamp found.",
            recommendation="Configure backups.",
        )

        with (
            patch.dict(os.environ, {"UNIFI_WRITE_ENABLED": "true"}),
            patch("unifi.agents.optimize._gather_wifi_data", AsyncMock(return_value=[])),
            patch("unifi.agents.optimize._gather_security_data", AsyncMock(return_value=[])),
            patch("unifi.agents.optimize._gather_config_data", AsyncMock(return_value=[finding])),
            patch("unifi.agents.optimize._gather_traffic_data", AsyncMock(return_value=[])),
        ):
            result = await apply_optimizations("default", apply=True)

        assert "Change Plan" in result
        assert "Confirm" in result or "confirm" in result

    async def test_returns_no_changes_when_healthy(self) -> None:
        """apply_optimizations indicates no changes needed when no findings."""
        from unifi.agents.optimize import apply_optimizations

        with (
            patch.dict(os.environ, {"UNIFI_WRITE_ENABLED": "true"}),
            patch("unifi.agents.optimize._gather_wifi_data", AsyncMock(return_value=[])),
            patch("unifi.agents.optimize._gather_security_data", AsyncMock(return_value=[])),
            patch("unifi.agents.optimize._gather_config_data", AsyncMock(return_value=[])),
            patch("unifi.agents.optimize._gather_traffic_data", AsyncMock(return_value=[])),
        ):
            result = await apply_optimizations("default", apply=True)

        assert "No actionable recommendations" in result or "healthy" in result.lower()


# ---------------------------------------------------------------------------
# Task 64: unifi_secure tests
# ---------------------------------------------------------------------------


class TestUnifiSecure:
    """Tests for the unifi_secure command tool."""

    async def test_secure_delegates_to_security_agent(self) -> None:
        """unifi_secure delegates to security_audit and returns its result."""
        mock_audit = AsyncMock(return_value="## Security Audit\nmock report")

        with patch("unifi.agents.security.security_audit", mock_audit):
            result = await unifi_secure()

        assert result == "## Security Audit\nmock report"

    async def test_secure_default_site_id(self) -> None:
        """unifi_secure passes 'default' site_id when none specified."""
        mock_audit = AsyncMock(return_value="report")

        with patch("unifi.agents.security.security_audit", mock_audit):
            await unifi_secure()

        mock_audit.assert_called_once_with("default")

    async def test_secure_custom_site_id(self) -> None:
        """unifi_secure passes through a custom site_id."""
        mock_audit = AsyncMock(return_value="report")

        with patch("unifi.agents.security.security_audit", mock_audit):
            await unifi_secure(site_id="data-center")

        mock_audit.assert_called_once_with("data-center")

    async def test_secure_error_propagation(self) -> None:
        """Errors from the security agent propagate through unifi_secure."""
        mock_audit = AsyncMock(side_effect=RuntimeError("Firewall API error"))

        with (
            patch("unifi.agents.security.security_audit", mock_audit),
            pytest.raises(RuntimeError, match="Firewall API error"),
        ):
            await unifi_secure()

    async def test_secure_returns_string(self) -> None:
        """unifi_secure returns a string (the formatted report)."""
        mock_audit = AsyncMock(return_value="## Security Audit\n**Rules:** 12")

        with patch("unifi.agents.security.security_audit", mock_audit):
            result = await unifi_secure()

        assert isinstance(result, str)

    async def test_secure_empty_site_id_passthrough(self) -> None:
        """An empty string site_id is passed through without modification."""
        mock_audit = AsyncMock(return_value="report")

        with patch("unifi.agents.security.security_audit", mock_audit):
            await unifi_secure(site_id="")

        mock_audit.assert_called_once_with("")


# ---------------------------------------------------------------------------
# Task 65: unifi_config tests
# ---------------------------------------------------------------------------


class TestUnifiConfig:
    """Tests for the unifi_config command tool."""

    async def test_config_delegates_to_config_agent(self) -> None:
        """unifi_config delegates to config_review and returns its result."""
        mock_review = AsyncMock(return_value="## Config Review\nmock report")

        with patch("unifi.agents.config.config_review", mock_review):
            result = await unifi_config()

        assert result == "## Config Review\nmock report"

    async def test_config_default_parameters(self) -> None:
        """unifi_config passes default site_id and drift=False."""
        mock_review = AsyncMock(return_value="report")

        with patch("unifi.agents.config.config_review", mock_review):
            await unifi_config()

        mock_review.assert_called_once_with("default", drift=False)

    async def test_config_custom_site_id(self) -> None:
        """unifi_config passes through a custom site_id."""
        mock_review = AsyncMock(return_value="report")

        with patch("unifi.agents.config.config_review", mock_review):
            await unifi_config(site_id="remote-site")

        mock_review.assert_called_once_with("remote-site", drift=False)

    async def test_config_with_drift_true(self) -> None:
        """unifi_config passes drift=True to config_review."""
        mock_review = AsyncMock(return_value="report")

        with patch("unifi.agents.config.config_review", mock_review):
            await unifi_config(drift=True)

        mock_review.assert_called_once_with("default", drift=True)

    async def test_config_with_drift_false(self) -> None:
        """unifi_config passes drift=False explicitly."""
        mock_review = AsyncMock(return_value="report")

        with patch("unifi.agents.config.config_review", mock_review):
            await unifi_config(drift=False)

        mock_review.assert_called_once_with("default", drift=False)

    async def test_config_with_site_and_drift(self) -> None:
        """unifi_config passes both custom site_id and drift=True."""
        mock_review = AsyncMock(return_value="report")

        with patch("unifi.agents.config.config_review", mock_review):
            await unifi_config(site_id="branch", drift=True)

        mock_review.assert_called_once_with("branch", drift=True)

    async def test_config_error_propagation(self) -> None:
        """Errors from the config agent propagate through unifi_config."""
        mock_review = AsyncMock(side_effect=RuntimeError("Config fetch failed"))

        with (
            patch("unifi.agents.config.config_review", mock_review),
            pytest.raises(RuntimeError, match="Config fetch failed"),
        ):
            await unifi_config()

    async def test_config_returns_string(self) -> None:
        """unifi_config returns a string (the formatted report)."""
        mock_review = AsyncMock(return_value="## Config Review\n**Networks:** 4")

        with patch("unifi.agents.config.config_review", mock_review):
            result = await unifi_config()

        assert isinstance(result, str)


# ---------------------------------------------------------------------------
# Task 65: config_review drift parameter unit tests
# ---------------------------------------------------------------------------


_CFG_SNAPSHOT = {
    "network_count": 3,
    "wlan_count": 2,
    "rule_count": 5,
}
_CFG_BACKUP = {
    "last_backup_time": "2026-03-18",
    "cloud_enabled": True,
}
_CFG_NO_DIFF = {"added": [], "removed": [], "modified": []}


class TestConfigReviewDrift:
    """Tests for the config_review agent function's drift parameter."""

    async def test_config_review_without_drift_skips_baseline_diff(self) -> None:
        """config_review with drift=False does NOT call diff_baseline."""
        from unifi.agents.config import config_review

        mock_snapshot = AsyncMock(return_value=_CFG_SNAPSHOT)
        mock_backup = AsyncMock(return_value=_CFG_BACKUP)
        mock_diff = AsyncMock(return_value=_CFG_NO_DIFF)

        with (
            patch("unifi.agents.config.unifi__config__get_config_snapshot", mock_snapshot),
            patch("unifi.agents.config.unifi__config__get_backup_state", mock_backup),
            patch("unifi.agents.config.unifi__config__diff_baseline", mock_diff),
        ):
            await config_review("default", drift=False)

        mock_snapshot.assert_called_once()
        mock_backup.assert_called_once()
        mock_diff.assert_not_called()

    async def test_config_review_with_drift_calls_baseline_diff(self) -> None:
        """config_review with drift=True calls diff_baseline."""
        from unifi.agents.config import config_review

        mock_snapshot = AsyncMock(return_value=_CFG_SNAPSHOT)
        mock_backup = AsyncMock(return_value=_CFG_BACKUP)
        mock_diff = AsyncMock(return_value=_CFG_NO_DIFF)

        with (
            patch("unifi.agents.config.unifi__config__get_config_snapshot", mock_snapshot),
            patch("unifi.agents.config.unifi__config__get_backup_state", mock_backup),
            patch("unifi.agents.config.unifi__config__diff_baseline", mock_diff),
        ):
            await config_review("default", drift=True)

        mock_snapshot.assert_called_once()
        mock_backup.assert_called_once()
        mock_diff.assert_called_once_with("default")

    async def test_config_review_drift_includes_drift_findings(self) -> None:
        """config_review with drift=True includes drift findings in report."""
        from unifi.agents.config import config_review

        mock_snapshot = AsyncMock(return_value=_CFG_SNAPSHOT)
        mock_backup = AsyncMock(return_value=_CFG_BACKUP)
        mock_diff = AsyncMock(
            return_value={
                "added": [{"name": "new-vlan"}],
                "removed": [],
                "modified": [{"name": "main-network"}],
            }
        )

        with (
            patch("unifi.agents.config.unifi__config__get_config_snapshot", mock_snapshot),
            patch("unifi.agents.config.unifi__config__get_backup_state", mock_backup),
            patch("unifi.agents.config.unifi__config__diff_baseline", mock_diff),
        ):
            result = await config_review("default", drift=True)

        assert "drift" in result.lower() or "change" in result.lower()

    async def test_config_review_default_drift_is_false(self) -> None:
        """config_review defaults to drift=False when not specified."""
        from unifi.agents.config import config_review

        snap = {"network_count": 1, "wlan_count": 1, "rule_count": 1}
        mock_snapshot = AsyncMock(return_value=snap)
        mock_backup = AsyncMock(return_value=_CFG_BACKUP)
        mock_diff = AsyncMock(return_value=_CFG_NO_DIFF)

        with (
            patch("unifi.agents.config.unifi__config__get_config_snapshot", mock_snapshot),
            patch("unifi.agents.config.unifi__config__get_backup_state", mock_backup),
            patch("unifi.agents.config.unifi__config__diff_baseline", mock_diff),
        ):
            await config_review("default")

        mock_diff.assert_not_called()


# ---------------------------------------------------------------------------
# MCP tool registration tests
# ---------------------------------------------------------------------------


class TestPhase2ToolRegistration:
    """Verify Phase 2 command tools are registered on the MCP server."""

    def test_unifi_wifi_registered(self) -> None:
        """unifi_wifi is registered as an MCP tool on the server."""
        from unifi.server import mcp_server

        tool_names = [t.name for t in mcp_server._tool_manager._tools.values()]
        assert "unifi_wifi" in tool_names

    def test_unifi_optimize_registered(self) -> None:
        """unifi_optimize is registered as an MCP tool on the server."""
        from unifi.server import mcp_server

        tool_names = [t.name for t in mcp_server._tool_manager._tools.values()]
        assert "unifi_optimize" in tool_names

    def test_unifi_secure_registered(self) -> None:
        """unifi_secure is registered as an MCP tool on the server."""
        from unifi.server import mcp_server

        tool_names = [t.name for t in mcp_server._tool_manager._tools.values()]
        assert "unifi_secure" in tool_names

    def test_unifi_config_registered(self) -> None:
        """unifi_config is registered as an MCP tool on the server."""
        from unifi.server import mcp_server

        tool_names = [t.name for t in mcp_server._tool_manager._tools.values()]
        assert "unifi_config" in tool_names

    def test_wifi_tool_has_site_id_parameter(self) -> None:
        """unifi_wifi tool accepts a site_id parameter."""
        from unifi.server import mcp_server

        tools = {t.name: t for t in mcp_server._tool_manager._tools.values()}
        tool = tools["unifi_wifi"]
        schema = tool.parameters
        assert "site_id" in schema.get("properties", {})

    def test_optimize_tool_has_site_id_parameter(self) -> None:
        """unifi_optimize tool accepts a site_id parameter."""
        from unifi.server import mcp_server

        tools = {t.name: t for t in mcp_server._tool_manager._tools.values()}
        tool = tools["unifi_optimize"]
        schema = tool.parameters
        assert "site_id" in schema.get("properties", {})

    def test_optimize_tool_has_apply_parameter(self) -> None:
        """unifi_optimize tool accepts an apply parameter."""
        from unifi.server import mcp_server

        tools = {t.name: t for t in mcp_server._tool_manager._tools.values()}
        tool = tools["unifi_optimize"]
        schema = tool.parameters
        assert "apply" in schema.get("properties", {})

    def test_secure_tool_has_site_id_parameter(self) -> None:
        """unifi_secure tool accepts a site_id parameter."""
        from unifi.server import mcp_server

        tools = {t.name: t for t in mcp_server._tool_manager._tools.values()}
        tool = tools["unifi_secure"]
        schema = tool.parameters
        assert "site_id" in schema.get("properties", {})

    def test_config_tool_has_site_id_parameter(self) -> None:
        """unifi_config tool accepts a site_id parameter."""
        from unifi.server import mcp_server

        tools = {t.name: t for t in mcp_server._tool_manager._tools.values()}
        tool = tools["unifi_config"]
        schema = tool.parameters
        assert "site_id" in schema.get("properties", {})

    def test_config_tool_has_drift_parameter(self) -> None:
        """unifi_config tool accepts a drift parameter."""
        from unifi.server import mcp_server

        tools = {t.name: t for t in mcp_server._tool_manager._tools.values()}
        tool = tools["unifi_config"]
        schema = tool.parameters
        assert "drift" in schema.get("properties", {})


# ---------------------------------------------------------------------------
# Optimize internal helpers tests
# ---------------------------------------------------------------------------


class TestOptimizeHelpers:
    """Tests for internal helper functions in the optimize agent."""

    def test_findings_to_recommendations_sorts_by_priority(self) -> None:
        """Recommendations are sorted by priority (critical > high > medium > low)."""
        from unifi.agents.optimize import _findings_to_recommendations
        from unifi.output import Finding, Severity

        findings = [
            Finding(
                severity=Severity.INFORMATIONAL,
                title="Low item",
                detail="Low detail",
                recommendation="Low action",
            ),
            Finding(
                severity=Severity.CRITICAL,
                title="Critical item",
                detail="Critical detail",
                recommendation="Critical action",
            ),
            Finding(
                severity=Severity.WARNING,
                title="Medium item",
                detail="Medium detail",
                recommendation="Medium action",
            ),
        ]

        recs = _findings_to_recommendations(findings)
        assert len(recs) == 3
        assert recs[0]["priority"] == "critical"
        assert recs[1]["priority"] == "medium"
        assert recs[2]["priority"] == "low"

    def test_findings_without_recommendations_are_skipped(self) -> None:
        """Findings without a recommendation field are not converted."""
        from unifi.agents.optimize import _findings_to_recommendations
        from unifi.output import Finding, Severity

        findings = [
            Finding(
                severity=Severity.INFORMATIONAL,
                title="Info only",
                detail="Detail",
                recommendation=None,
            ),
            Finding(
                severity=Severity.WARNING,
                title="Actionable",
                detail="Detail",
                recommendation="Do something",
            ),
        ]

        recs = _findings_to_recommendations(findings)
        assert len(recs) == 1
        assert recs[0]["title"] == "Actionable"

    def test_categorize_finding_wifi(self) -> None:
        """WiFi-related findings are categorized as 'wifi'."""
        from unifi.agents.optimize import _categorize_finding
        from unifi.output import Finding, Severity

        finding = Finding(
            severity=Severity.WARNING,
            title="AP-1 2.4 GHz at 75%",
            detail="High utilization",
        )
        assert _categorize_finding(finding) == "wifi"

    def test_categorize_finding_security(self) -> None:
        """Security-related findings are categorized as 'security'."""
        from unifi.agents.optimize import _categorize_finding
        from unifi.output import Finding, Severity

        finding = Finding(
            severity=Severity.HIGH,
            title="Sensitive port 22 exposed",
            detail="SSH forward active",
        )
        assert _categorize_finding(finding) == "security"

    def test_categorize_finding_traffic(self) -> None:
        """Traffic-related findings are categorized as 'traffic'."""
        from unifi.agents.optimize import _categorize_finding
        from unifi.output import Finding, Severity

        finding = Finding(
            severity=Severity.WARNING,
            title="High WAN bandwidth utilization",
            detail="WAN throughput elevated",
        )
        assert _categorize_finding(finding) == "traffic"

    def test_categorize_finding_config(self) -> None:
        """Config-related findings are categorized as 'config'."""
        from unifi.agents.optimize import _categorize_finding
        from unifi.output import Finding, Severity

        finding = Finding(
            severity=Severity.WARNING,
            title="No recent backup found",
            detail="No backup timestamp",
        )
        assert _categorize_finding(finding) == "config"

    def test_categorize_finding_general(self) -> None:
        """Uncategorizable findings default to 'general'."""
        from unifi.agents.optimize import _categorize_finding
        from unifi.output import Finding, Severity

        finding = Finding(
            severity=Severity.INFORMATIONAL,
            title="Something unrelated",
            detail="Unknown category",
        )
        assert _categorize_finding(finding) == "general"
