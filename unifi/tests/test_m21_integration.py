# SPDX-License-Identifier: MIT
"""M2.1 integration tests -- WiFi, Traffic, Security, Config agents and tool registration.

Tests agent orchestrators by mocking at the tool function level and verifying
that each agent correctly gathers data, classifies findings, and produces
formatted reports via OX formatters.

Also tests cross-skill MCP tool registration on the shared ``mcp_server`` instance.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, patch

# ---------------------------------------------------------------------------
# WiFi agent fixture helpers
# ---------------------------------------------------------------------------


def _build_wlans() -> list[dict[str, Any]]:
    """Sample WLAN list returned by the get_wlans tool."""
    return [
        {
            "wlan_id": "w1",
            "name": "HomeNet",
            "ssid": "HomeNet",
            "security": "wpa2",
            "band": "both",
            "vlan_id": "net1",
            "enabled": True,
            "client_count": 12,
            "satisfaction": 95,
        },
        {
            "wlan_id": "w2",
            "name": "GuestNet",
            "ssid": "GuestNet",
            "security": "wpa2",
            "band": "2g",
            "vlan_id": "net2",
            "enabled": True,
            "client_count": 3,
            "satisfaction": 88,
        },
    ]


def _build_aps() -> list[dict[str, Any]]:
    """Sample AP list returned by the get_aps tool."""
    return [
        {
            "ap_id": "ap1",
            "name": "LivingRoom-AP",
            "mac": "aa:bb:cc:dd:ee:01",
            "model": "U6-Pro",
            "channel_2g": 6,
            "channel_5g": 36,
            "client_count": 8,
            "satisfaction": 97,
        },
        {
            "ap_id": "ap2",
            "name": "Office-AP",
            "mac": "aa:bb:cc:dd:ee:02",
            "model": "U6-LR",
            "channel_2g": 11,
            "channel_5g": 149,
            "client_count": 5,
            "satisfaction": 91,
        },
    ]


def _build_channel_util(utilization_pct: int = 30) -> dict[str, Any]:
    """Sample channel utilization dict returned by get_channel_utilization."""
    return {
        "ap_id": "ap1",
        "radio_2g": {
            "channel": 6,
            "utilization_pct": utilization_pct,
            "interference_pct": 5,
        },
        "radio_5g": {
            "channel": 36,
            "utilization_pct": utilization_pct // 2,
            "interference_pct": 2,
        },
        "radio_6g": None,
    }


def _build_rf_neighbors(count: int = 2, strong: bool = False) -> list[dict[str, Any]]:
    """Sample RF scan neighbor list."""
    base_rssi = -50 if strong else -75
    return [
        {
            "ssid": f"Neighbor-{i}",
            "bssid": f"ff:ff:ff:ff:ff:{i:02x}",
            "channel": 6 + i,
            "band": "2g",
            "rssi": base_rssi + i,
            "security": "wpa2",
            "is_own": False,
        }
        for i in range(count)
    ]


def _build_roaming_events() -> list[dict[str, Any]]:
    """Sample roaming event list."""
    return [
        {
            "timestamp": "2026-03-19T10:00:00+00:00",
            "client_mac": "11:22:33:44:55:66",
            "from_ap_id": "ap1",
            "to_ap_id": "ap2",
            "rssi_before": -65,
            "rssi_after": -55,
            "roam_reason": "signal_quality",
        },
    ]


# ---------------------------------------------------------------------------
# WiFi agent integration tests
# ---------------------------------------------------------------------------


class TestWiFiAgentIntegration:
    """Integration tests for the analyze_wifi agent orchestrator."""

    async def test_analyze_wifi_calls_all_tools_and_formats_report(self) -> None:
        """analyze_wifi calls all 5 wifi tools and produces a formatted report."""
        from unifi.agents.wifi import analyze_wifi

        mock_wlans = AsyncMock(return_value=_build_wlans())
        mock_aps = AsyncMock(return_value=_build_aps())
        mock_util = AsyncMock(return_value=_build_channel_util())
        mock_rf = AsyncMock(return_value=_build_rf_neighbors())
        mock_roam = AsyncMock(return_value=_build_roaming_events())

        with (
            patch("unifi.agents.wifi.unifi__wifi__get_wlans", mock_wlans),
            patch("unifi.agents.wifi.unifi__wifi__get_aps", mock_aps),
            patch("unifi.agents.wifi.unifi__wifi__get_channel_utilization", mock_util),
            patch("unifi.agents.wifi.unifi__wifi__get_rf_scan", mock_rf),
            patch("unifi.agents.wifi.unifi__wifi__get_roaming_events", mock_roam),
        ):
            result = await analyze_wifi()

        # All tools called
        mock_wlans.assert_called_once_with("default")
        mock_aps.assert_called_once_with("default")
        assert mock_util.call_count == 2  # Once per AP
        assert mock_rf.call_count == 2  # Once per AP
        mock_roam.assert_called_once_with("default")

        # Report contains expected sections
        assert "## WiFi Environment Analysis" in result
        assert "**WLANs:** 2" in result
        assert "**APs:** 2" in result

    async def test_report_includes_channel_utilization_table(self) -> None:
        """Report includes an AP table with channel utilization data."""
        from unifi.agents.wifi import analyze_wifi

        mock_wlans = AsyncMock(return_value=_build_wlans())
        mock_aps = AsyncMock(return_value=_build_aps())
        mock_util = AsyncMock(return_value=_build_channel_util())
        mock_rf = AsyncMock(return_value=_build_rf_neighbors())
        mock_roam = AsyncMock(return_value=_build_roaming_events())

        with (
            patch("unifi.agents.wifi.unifi__wifi__get_wlans", mock_wlans),
            patch("unifi.agents.wifi.unifi__wifi__get_aps", mock_aps),
            patch("unifi.agents.wifi.unifi__wifi__get_channel_utilization", mock_util),
            patch("unifi.agents.wifi.unifi__wifi__get_rf_scan", mock_rf),
            patch("unifi.agents.wifi.unifi__wifi__get_roaming_events", mock_roam),
        ):
            result = await analyze_wifi()

        # AP table with channel columns
        assert "### Access Points" in result
        assert "LivingRoom-AP" in result
        assert "Office-AP" in result
        assert "U6-Pro" in result

        # WLAN table
        assert "### WLANs" in result
        assert "HomeNet" in result
        assert "GuestNet" in result

    async def test_empty_ap_list_produces_clean_report(self) -> None:
        """Empty AP list still produces a valid summary report."""
        from unifi.agents.wifi import analyze_wifi

        mock_wlans = AsyncMock(return_value=_build_wlans())
        mock_aps = AsyncMock(return_value=[])
        mock_util = AsyncMock(return_value=_build_channel_util())
        mock_rf = AsyncMock(return_value=[])
        mock_roam = AsyncMock(return_value=[])

        with (
            patch("unifi.agents.wifi.unifi__wifi__get_wlans", mock_wlans),
            patch("unifi.agents.wifi.unifi__wifi__get_aps", mock_aps),
            patch("unifi.agents.wifi.unifi__wifi__get_channel_utilization", mock_util),
            patch("unifi.agents.wifi.unifi__wifi__get_rf_scan", mock_rf),
            patch("unifi.agents.wifi.unifi__wifi__get_roaming_events", mock_roam),
        ):
            result = await analyze_wifi()

        assert "## WiFi Environment Analysis" in result
        assert "**APs:** 0" in result
        # Channel utilization and RF scan should NOT be called (no APs)
        mock_util.assert_not_called()
        mock_rf.assert_not_called()

    async def test_custom_site_id_passthrough(self) -> None:
        """Custom site_id is forwarded to all wifi tool calls."""
        from unifi.agents.wifi import analyze_wifi

        mock_wlans = AsyncMock(return_value=[])
        mock_aps = AsyncMock(return_value=[])
        mock_util = AsyncMock(return_value=_build_channel_util())
        mock_rf = AsyncMock(return_value=[])
        mock_roam = AsyncMock(return_value=[])

        with (
            patch("unifi.agents.wifi.unifi__wifi__get_wlans", mock_wlans),
            patch("unifi.agents.wifi.unifi__wifi__get_aps", mock_aps),
            patch("unifi.agents.wifi.unifi__wifi__get_channel_utilization", mock_util),
            patch("unifi.agents.wifi.unifi__wifi__get_rf_scan", mock_rf),
            patch("unifi.agents.wifi.unifi__wifi__get_roaming_events", mock_roam),
        ):
            await analyze_wifi(site_id="branch-office")

        mock_wlans.assert_called_once_with("branch-office")
        mock_aps.assert_called_once_with("branch-office")
        mock_roam.assert_called_once_with("branch-office")

    async def test_high_utilization_produces_findings(self) -> None:
        """High channel utilization (>80%) produces CRITICAL findings."""
        from unifi.agents.wifi import analyze_wifi

        mock_wlans = AsyncMock(return_value=_build_wlans())
        # Single AP for simpler assertion
        aps = [_build_aps()[0]]
        mock_aps = AsyncMock(return_value=aps)
        mock_util = AsyncMock(return_value=_build_channel_util(utilization_pct=85))
        mock_rf = AsyncMock(return_value=_build_rf_neighbors())
        mock_roam = AsyncMock(return_value=[])

        with (
            patch("unifi.agents.wifi.unifi__wifi__get_wlans", mock_wlans),
            patch("unifi.agents.wifi.unifi__wifi__get_aps", mock_aps),
            patch("unifi.agents.wifi.unifi__wifi__get_channel_utilization", mock_util),
            patch("unifi.agents.wifi.unifi__wifi__get_rf_scan", mock_rf),
            patch("unifi.agents.wifi.unifi__wifi__get_roaming_events", mock_roam),
        ):
            result = await analyze_wifi()

        assert "CRITICAL" in result
        assert "utilization" in result.lower()
        assert "85%" in result


# ---------------------------------------------------------------------------
# Traffic agent fixture helpers
# ---------------------------------------------------------------------------


def _build_bandwidth(wan_rx: float = 150.0, wan_tx: float = 25.0) -> dict[str, Any]:
    """Sample bandwidth data returned by get_bandwidth."""
    return {
        "wan": {"rx_mbps": wan_rx, "tx_mbps": wan_tx, "history": []},
        "lan": {"rx_mbps": 800.0, "tx_mbps": 200.0},
    }


def _build_dpi_stats() -> list[dict[str, Any]]:
    """Sample DPI statistics returned by get_dpi_stats."""
    return [
        {
            "application": "YouTube",
            "category": "Streaming",
            "tx_bytes": 500_000,
            "rx_bytes": 50_000_000,
            "session_count": 15,
        },
        {
            "application": "Zoom",
            "category": "Video Conferencing",
            "tx_bytes": 10_000_000,
            "rx_bytes": 12_000_000,
            "session_count": 3,
        },
        {
            "application": "Slack",
            "category": "Productivity",
            "tx_bytes": 100_000,
            "rx_bytes": 200_000,
            "session_count": 42,
        },
    ]


def _build_wan_usage(days: int = 7) -> list[dict[str, Any]]:
    """Sample WAN usage data returned by get_wan_usage."""
    return [
        {
            "date": f"2026-03-{12 + i:02d}",
            "download_gb": 5.5 + i * 0.3,
            "upload_gb": 0.8 + i * 0.1,
        }
        for i in range(days)
    ]


# ---------------------------------------------------------------------------
# Traffic agent integration tests
# ---------------------------------------------------------------------------


class TestTrafficAgentIntegration:
    """Integration tests for the traffic_report agent orchestrator."""

    async def test_traffic_report_calls_all_tools(self) -> None:
        """traffic_report calls bandwidth, DPI, and WAN usage tools."""
        from unifi.agents.traffic import traffic_report

        mock_bw = AsyncMock(return_value=_build_bandwidth())
        mock_dpi = AsyncMock(return_value=_build_dpi_stats())
        mock_wan = AsyncMock(return_value=_build_wan_usage())

        with (
            patch("unifi.agents.traffic.unifi__traffic__get_bandwidth", mock_bw),
            patch("unifi.agents.traffic.unifi__traffic__get_dpi_stats", mock_dpi),
            patch("unifi.agents.traffic.unifi__traffic__get_wan_usage", mock_wan),
        ):
            result = await traffic_report()

        mock_bw.assert_called_once_with("default")
        mock_dpi.assert_called_once_with("default")
        mock_wan.assert_called_once_with("default")

        assert "## Traffic Report" in result
        assert "**WAN Download:** 150.0 Mbps" in result
        assert "**WAN Upload:** 25.0 Mbps" in result

    async def test_report_includes_top_applications(self) -> None:
        """Report includes DPI top applications table."""
        from unifi.agents.traffic import traffic_report

        mock_bw = AsyncMock(return_value=_build_bandwidth())
        mock_dpi = AsyncMock(return_value=_build_dpi_stats())
        mock_wan = AsyncMock(return_value=_build_wan_usage())

        with (
            patch("unifi.agents.traffic.unifi__traffic__get_bandwidth", mock_bw),
            patch("unifi.agents.traffic.unifi__traffic__get_dpi_stats", mock_dpi),
            patch("unifi.agents.traffic.unifi__traffic__get_wan_usage", mock_wan),
        ):
            result = await traffic_report()

        assert "### Top Applications (DPI)" in result
        assert "YouTube" in result
        assert "Zoom" in result
        assert "Streaming" in result

    async def test_empty_traffic_data_handled_gracefully(self) -> None:
        """Empty DPI and WAN usage data produces a valid report."""
        from unifi.agents.traffic import traffic_report

        mock_bw = AsyncMock(return_value=_build_bandwidth())
        mock_dpi = AsyncMock(return_value=[])
        mock_wan = AsyncMock(return_value=[])

        with (
            patch("unifi.agents.traffic.unifi__traffic__get_bandwidth", mock_bw),
            patch("unifi.agents.traffic.unifi__traffic__get_dpi_stats", mock_dpi),
            patch("unifi.agents.traffic.unifi__traffic__get_wan_usage", mock_wan),
        ):
            result = await traffic_report()

        assert "## Traffic Report" in result
        # No DPI table when empty
        assert "Top Applications" not in result
        # Total WAN usage should be 0
        assert "**Total WAN Usage:** 0.0 GB" in result

    async def test_high_bandwidth_produces_warning(self) -> None:
        """Very high WAN bandwidth (>900 Mbps) produces a WARNING finding."""
        from unifi.agents.traffic import traffic_report

        mock_bw = AsyncMock(return_value=_build_bandwidth(wan_rx=950.0, wan_tx=100.0))
        mock_dpi = AsyncMock(return_value=_build_dpi_stats())
        mock_wan = AsyncMock(return_value=_build_wan_usage())

        with (
            patch("unifi.agents.traffic.unifi__traffic__get_bandwidth", mock_bw),
            patch("unifi.agents.traffic.unifi__traffic__get_dpi_stats", mock_dpi),
            patch("unifi.agents.traffic.unifi__traffic__get_wan_usage", mock_wan),
        ):
            result = await traffic_report()

        assert "Warning" in result
        assert "WAN bandwidth" in result

    async def test_custom_site_id_passthrough(self) -> None:
        """Custom site_id is forwarded to all traffic tool calls."""
        from unifi.agents.traffic import traffic_report

        mock_bw = AsyncMock(return_value=_build_bandwidth())
        mock_dpi = AsyncMock(return_value=[])
        mock_wan = AsyncMock(return_value=[])

        with (
            patch("unifi.agents.traffic.unifi__traffic__get_bandwidth", mock_bw),
            patch("unifi.agents.traffic.unifi__traffic__get_dpi_stats", mock_dpi),
            patch("unifi.agents.traffic.unifi__traffic__get_wan_usage", mock_wan),
        ):
            await traffic_report(site_id="warehouse")

        mock_bw.assert_called_once_with("warehouse")
        mock_dpi.assert_called_once_with("warehouse")
        mock_wan.assert_called_once_with("warehouse")


# ---------------------------------------------------------------------------
# Security agent fixture helpers
# ---------------------------------------------------------------------------


def _build_firewall_rules() -> list[dict[str, Any]]:
    """Sample firewall rules returned by get_firewall_rules."""
    return [
        {
            "rule_id": "r1",
            "name": "Allow LAN to WAN",
            "action": "accept",
            "enabled": True,
            "src": "192.168.1.0/24",
            "dst": "",
            "protocol": "all",
            "position": 1,
        },
        {
            "rule_id": "r2",
            "name": "Block IoT to LAN",
            "action": "drop",
            "enabled": True,
            "src": "192.168.10.0/24",
            "dst": "192.168.1.0/24",
            "protocol": "all",
            "position": 2,
        },
    ]


def _build_overbroad_firewall_rule() -> list[dict[str, Any]]:
    """Firewall rules including an over-broad accept rule."""
    return [
        {
            "rule_id": "r3",
            "name": "Accept Everything",
            "action": "accept",
            "enabled": True,
            "src": "",
            "dst": "",
            "protocol": "all",
            "position": 1,
        },
    ]


def _build_zbf_policies() -> list[dict[str, Any]]:
    """Sample ZBF policies."""
    return [
        {
            "policy_id": "z1",
            "from_zone": "LAN",
            "to_zone": "WAN",
            "action": "accept",
            "match_all": False,
        },
    ]


def _build_acls() -> list[dict[str, Any]]:
    """Sample ACL list."""
    return [
        {"acl_id": "a1", "name": "Management ACL", "entries": [], "applied_to": []},
    ]


def _build_port_forwards(sensitive: bool = False) -> list[dict[str, Any]]:
    """Sample port forward rules. If sensitive=True, includes SSH forwarding."""
    forwards = [
        {
            "rule_id": "pf1",
            "name": "Web Server",
            "proto": "tcp",
            "wan_port": "8080",
            "lan_host": "192.168.1.100",
            "lan_port": "80",
            "enabled": True,
        },
    ]
    if sensitive:
        forwards.append(
            {
                "rule_id": "pf2",
                "name": "SSH Access",
                "proto": "tcp",
                "wan_port": "22",
                "lan_host": "192.168.1.50",
                "lan_port": "22",
                "enabled": True,
            }
        )
    return forwards


def _build_ids_alerts(severity: int | str = 3) -> list[dict[str, Any]]:
    """Sample IDS alerts. severity controls alert severity level."""
    return [
        {
            "timestamp": "2026-03-19T08:00:00+00:00",
            "signature": "ET SCAN Potential SSH Scan",
            "severity": severity,
            "src_ip": "10.0.0.99",
            "dst_ip": "192.168.1.1",
            "action_taken": "alert",
        },
    ]


# ---------------------------------------------------------------------------
# Security agent integration tests
# ---------------------------------------------------------------------------


class TestSecurityAgentIntegration:
    """Integration tests for the security_audit agent orchestrator."""

    async def test_security_audit_produces_severity_report(self) -> None:
        """security_audit produces a severity-tiered findings report."""
        from unifi.agents.security import security_audit

        mock_fw = AsyncMock(return_value=_build_firewall_rules())
        mock_zbf = AsyncMock(return_value=_build_zbf_policies())
        mock_acl = AsyncMock(return_value=_build_acls())
        mock_pf = AsyncMock(return_value=_build_port_forwards())
        mock_ids = AsyncMock(return_value=[])

        with (
            patch("unifi.agents.security.unifi__security__get_firewall_rules", mock_fw),
            patch("unifi.agents.security.unifi__security__get_zbf_policies", mock_zbf),
            patch("unifi.agents.security.unifi__security__get_acls", mock_acl),
            patch("unifi.agents.security.unifi__security__get_port_forwards", mock_pf),
            patch("unifi.agents.security.unifi__security__get_ids_alerts", mock_ids),
        ):
            result = await security_audit()

        assert "## Security Audit" in result
        assert "**Firewall Rules:** 2" in result
        assert "**Port Forwards:** 1" in result

        # All 5 tools called
        mock_fw.assert_called_once_with("default")
        mock_zbf.assert_called_once_with("default")
        mock_acl.assert_called_once_with("default")
        mock_pf.assert_called_once_with("default")
        mock_ids.assert_called_once_with("default", hours=24)

    async def test_overbroad_rules_flagged_as_warning(self) -> None:
        """Over-broad accept rules (no src/dst) produce WARNING findings."""
        from unifi.agents.security import security_audit

        mock_fw = AsyncMock(return_value=_build_overbroad_firewall_rule())
        mock_zbf = AsyncMock(return_value=[])
        mock_acl = AsyncMock(return_value=[])
        mock_pf = AsyncMock(return_value=[])
        mock_ids = AsyncMock(return_value=[])

        with (
            patch("unifi.agents.security.unifi__security__get_firewall_rules", mock_fw),
            patch("unifi.agents.security.unifi__security__get_zbf_policies", mock_zbf),
            patch("unifi.agents.security.unifi__security__get_acls", mock_acl),
            patch("unifi.agents.security.unifi__security__get_port_forwards", mock_pf),
            patch("unifi.agents.security.unifi__security__get_ids_alerts", mock_ids),
        ):
            result = await security_audit()

        assert "Warning" in result
        assert "Over-broad" in result
        assert "Accept Everything" in result

    async def test_sensitive_port_forwards_flagged(self) -> None:
        """Port forwards with sensitive ports (22, 3389, etc.) are flagged HIGH."""
        from unifi.agents.security import security_audit

        mock_fw = AsyncMock(return_value=[])
        mock_zbf = AsyncMock(return_value=[])
        mock_acl = AsyncMock(return_value=[])
        mock_pf = AsyncMock(return_value=_build_port_forwards(sensitive=True))
        mock_ids = AsyncMock(return_value=[])

        with (
            patch("unifi.agents.security.unifi__security__get_firewall_rules", mock_fw),
            patch("unifi.agents.security.unifi__security__get_zbf_policies", mock_zbf),
            patch("unifi.agents.security.unifi__security__get_acls", mock_acl),
            patch("unifi.agents.security.unifi__security__get_port_forwards", mock_pf),
            patch("unifi.agents.security.unifi__security__get_ids_alerts", mock_ids),
        ):
            result = await security_audit()

        assert "HIGH" in result
        assert "Sensitive port exposed" in result
        assert "SSH Access" in result
        assert "port 22" in result

    async def test_ids_alerts_classified_correctly(self) -> None:
        """IDS alerts with severity 1 are classified as CRITICAL."""
        from unifi.agents.security import security_audit

        mock_fw = AsyncMock(return_value=[])
        mock_zbf = AsyncMock(return_value=[])
        mock_acl = AsyncMock(return_value=[])
        mock_pf = AsyncMock(return_value=[])
        mock_ids = AsyncMock(return_value=_build_ids_alerts(severity=1))

        with (
            patch("unifi.agents.security.unifi__security__get_firewall_rules", mock_fw),
            patch("unifi.agents.security.unifi__security__get_zbf_policies", mock_zbf),
            patch("unifi.agents.security.unifi__security__get_acls", mock_acl),
            patch("unifi.agents.security.unifi__security__get_port_forwards", mock_pf),
            patch("unifi.agents.security.unifi__security__get_ids_alerts", mock_ids),
        ):
            result = await security_audit()

        assert "CRITICAL" in result
        assert "IDS alert" in result
        assert "ET SCAN" in result

    async def test_clean_audit_no_concerns(self) -> None:
        """Clean audit with no issues shows a healthy message."""
        from unifi.agents.security import security_audit

        mock_fw = AsyncMock(return_value=_build_firewall_rules())
        mock_zbf = AsyncMock(return_value=_build_zbf_policies())
        mock_acl = AsyncMock(return_value=_build_acls())
        mock_pf = AsyncMock(return_value=[])
        mock_ids = AsyncMock(return_value=[])

        with (
            patch("unifi.agents.security.unifi__security__get_firewall_rules", mock_fw),
            patch("unifi.agents.security.unifi__security__get_zbf_policies", mock_zbf),
            patch("unifi.agents.security.unifi__security__get_acls", mock_acl),
            patch("unifi.agents.security.unifi__security__get_port_forwards", mock_pf),
            patch("unifi.agents.security.unifi__security__get_ids_alerts", mock_ids),
        ):
            result = await security_audit()

        assert "No security concerns detected" in result


# ---------------------------------------------------------------------------
# Config agent fixture helpers
# ---------------------------------------------------------------------------


def _build_config_snapshot(
    networks: int = 3,
    wlans: int = 2,
    rules: int = 5,
) -> dict[str, Any]:
    """Sample config snapshot returned by get_config_snapshot."""
    return {
        "site_id": "default",
        "timestamp": "2026-03-19T12:00:00+00:00",
        "network_count": networks,
        "wlan_count": wlans,
        "rule_count": rules,
        "raw_config": {
            "networks": [{"_id": f"n{i}", "name": f"Net{i}"} for i in range(networks)],
            "wlans": [{"_id": f"w{i}", "name": f"WLAN{i}"} for i in range(wlans)],
            "firewall_rules": [{"_id": f"r{i}", "name": f"Rule{i}"} for i in range(rules)],
        },
    }


def _build_backup_state(
    has_backup: bool = True,
    cloud_enabled: bool = True,
) -> dict[str, Any]:
    """Sample backup state returned by get_backup_state."""
    return {
        "last_backup_time": "2026-03-19T06:00:00+00:00" if has_backup else "",
        "backup_type": "auto",
        "size_mb": 42,
        "cloud_enabled": cloud_enabled,
    }


def _build_diff_no_changes() -> dict[str, Any]:
    """Config diff with no changes."""
    return {"added": [], "removed": [], "modified": []}


def _build_diff_with_changes() -> dict[str, Any]:
    """Config diff showing drift from baseline."""
    return {
        "added": [{"section": "networks", "id": "n4", "name": "NewVLAN"}],
        "removed": [],
        "modified": [{"section": "firewall_rules", "id": "r1", "name": "Allow LAN"}],
    }


def _build_diff_no_baseline() -> dict[str, Any]:
    """Config diff when no baseline exists."""
    return {
        "error": "No baseline found for 'latest' at site 'default'.",
        "hint": "Save a baseline first using the config save_baseline tool.",
        "added": [],
        "removed": [],
        "modified": [],
    }


# ---------------------------------------------------------------------------
# Config agent integration tests
# ---------------------------------------------------------------------------


class TestConfigAgentIntegration:
    """Integration tests for the config_review agent orchestrator."""

    async def test_config_review_produces_summary(self) -> None:
        """config_review produces a config state summary report."""
        from unifi.agents.config import config_review

        mock_snap = AsyncMock(return_value=_build_config_snapshot())
        mock_backup = AsyncMock(return_value=_build_backup_state())
        mock_diff = AsyncMock(return_value=_build_diff_no_changes())

        with (
            patch("unifi.agents.config.unifi__config__get_config_snapshot", mock_snap),
            patch("unifi.agents.config.unifi__config__get_backup_state", mock_backup),
            patch("unifi.agents.config.unifi__config__diff_baseline", mock_diff),
        ):
            result = await config_review(drift=True)

        assert "## Config Review" in result
        assert "**Networks:** 3" in result
        assert "**WLANs:** 2" in result
        assert "**Firewall Rules:** 5" in result

        mock_snap.assert_called_once_with("default")
        mock_backup.assert_called_once_with("default")
        mock_diff.assert_called_once_with("default")

    async def test_missing_backup_state_handled(self) -> None:
        """Missing backup timestamp produces a WARNING finding."""
        from unifi.agents.config import config_review

        mock_snap = AsyncMock(return_value=_build_config_snapshot())
        mock_backup = AsyncMock(
            return_value=_build_backup_state(has_backup=False, cloud_enabled=False)
        )
        mock_diff = AsyncMock(return_value=_build_diff_no_changes())

        with (
            patch("unifi.agents.config.unifi__config__get_config_snapshot", mock_snap),
            patch("unifi.agents.config.unifi__config__get_backup_state", mock_backup),
            patch("unifi.agents.config.unifi__config__diff_baseline", mock_diff),
        ):
            result = await config_review()

        assert "Warning" in result
        assert "No backup timestamp" in result

    async def test_baseline_diff_with_changes(self) -> None:
        """Config drift from baseline produces a WARNING finding."""
        from unifi.agents.config import config_review

        mock_snap = AsyncMock(return_value=_build_config_snapshot())
        mock_backup = AsyncMock(return_value=_build_backup_state())
        mock_diff = AsyncMock(return_value=_build_diff_with_changes())

        with (
            patch("unifi.agents.config.unifi__config__get_config_snapshot", mock_snap),
            patch("unifi.agents.config.unifi__config__get_backup_state", mock_backup),
            patch("unifi.agents.config.unifi__config__diff_baseline", mock_diff),
        ):
            result = await config_review(drift=True)

        assert "Warning" in result
        assert "Configuration drift" in result
        assert "2 change(s)" in result
        assert "NewVLAN" in result

    async def test_no_baseline_available(self) -> None:
        """Missing baseline produces an informational finding, not an error."""
        from unifi.agents.config import config_review

        mock_snap = AsyncMock(return_value=_build_config_snapshot())
        mock_backup = AsyncMock(return_value=_build_backup_state())
        mock_diff = AsyncMock(return_value=_build_diff_no_baseline())

        with (
            patch("unifi.agents.config.unifi__config__get_config_snapshot", mock_snap),
            patch("unifi.agents.config.unifi__config__get_backup_state", mock_backup),
            patch("unifi.agents.config.unifi__config__diff_baseline", mock_diff),
        ):
            result = await config_review(drift=True)

        assert "No baseline available" in result
        assert "Save a baseline first" in result

    async def test_zero_networks_warning(self) -> None:
        """Zero networks configured produces a WARNING finding."""
        from unifi.agents.config import config_review

        mock_snap = AsyncMock(return_value=_build_config_snapshot(networks=0, wlans=0, rules=0))
        mock_backup = AsyncMock(return_value=_build_backup_state())
        mock_diff = AsyncMock(return_value=_build_diff_no_changes())

        with (
            patch("unifi.agents.config.unifi__config__get_config_snapshot", mock_snap),
            patch("unifi.agents.config.unifi__config__get_backup_state", mock_backup),
            patch("unifi.agents.config.unifi__config__diff_baseline", mock_diff),
        ):
            result = await config_review()

        assert "Warning" in result
        assert "No networks configured" in result
        assert "No WLANs configured" in result
        assert "No firewall rules configured" in result


# ---------------------------------------------------------------------------
# Cross-skill tool registration tests
# ---------------------------------------------------------------------------


class TestCrossSkillRegistration:
    """Verify MCP tool registration across all M2.1 skill groups."""

    def _get_tool_names(self) -> list[str]:
        """Extract registered tool names from the mcp_server instance."""
        # Import all tool modules to trigger @mcp_server.tool() registration
        import unifi.tools  # noqa: F401  # isort: skip
        from unifi.server import mcp_server  # isort: skip

        tool_manager = mcp_server._tool_manager  # type: ignore[attr-defined]
        tools = tool_manager.list_tools()
        return [t.name for t in tools]

    def test_all_tool_modules_register_on_server(self) -> None:
        """All tool modules register their tools when imported."""
        tool_names = self._get_tool_names()
        # Should have tools from all skill groups
        assert len(tool_names) > 0
        # At least one tool from each M2.1 group
        assert any(n.startswith("unifi__wifi__") for n in tool_names)
        assert any(n.startswith("unifi__traffic__") for n in tool_names)
        assert any(n.startswith("unifi__security__") for n in tool_names)
        assert any(n.startswith("unifi__config__") for n in tool_names)

    def test_tool_count_at_least_30(self) -> None:
        """Total registered tool count should be at least 30."""
        tool_names = self._get_tool_names()
        assert len(tool_names) >= 30, (
            f"Expected at least 30 registered tools, got {len(tool_names)}: {tool_names}"
        )

    def test_wifi_skill_expected_tools(self) -> None:
        """WiFi skill group has all expected tool names."""
        tool_names = self._get_tool_names()
        expected_wifi = {
            "unifi__wifi__get_wlans",
            "unifi__wifi__get_aps",
            "unifi__wifi__get_channel_utilization",
            "unifi__wifi__get_rf_scan",
            "unifi__wifi__get_roaming_events",
            "unifi__wifi__get_client_rf",
        }
        registered_wifi = {n for n in tool_names if n.startswith("unifi__wifi__")}
        assert expected_wifi == registered_wifi

    def test_traffic_skill_expected_tools(self) -> None:
        """Traffic skill group has all expected tool names."""
        tool_names = self._get_tool_names()
        expected_traffic = {
            "unifi__traffic__get_bandwidth",
            "unifi__traffic__get_dpi_stats",
            "unifi__traffic__get_port_stats",
            "unifi__traffic__get_wan_usage",
        }
        registered_traffic = {n for n in tool_names if n.startswith("unifi__traffic__")}
        assert expected_traffic == registered_traffic

    def test_security_skill_expected_tools(self) -> None:
        """Security skill group has all expected tool names."""
        tool_names = self._get_tool_names()
        expected_security = {
            "unifi__security__get_firewall_rules",
            "unifi__security__get_zbf_policies",
            "unifi__security__get_acls",
            "unifi__security__get_port_forwards",
            "unifi__security__get_ids_alerts",
        }
        registered_security = {n for n in tool_names if n.startswith("unifi__security__")}
        assert expected_security == registered_security
