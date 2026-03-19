"""Tests for the health agent (check_health orchestrator)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, patch

from unifi.agents.health import (
    _classify_events,
    _classify_firmware,
    _classify_isp,
    _classify_site_health,
    check_health,
)
from unifi.output import Severity

# ---------------------------------------------------------------------------
# Fixture helpers -- build dicts matching what each tool returns
# ---------------------------------------------------------------------------


def _build_healthy_site_health() -> dict[str, Any]:
    """Build a site health dict where all subsystems are ok."""
    return {
        "wan_status": "ok",
        "lan_status": "ok",
        "wlan_status": "ok",
        "www_status": "ok",
        "device_count": 3,
        "adopted_count": 3,
        "offline_count": 0,
        "client_count": 47,
    }


def _build_wan_down_site_health() -> dict[str, Any]:
    """Build a site health dict where WAN is down."""
    return {
        "wan_status": "error",
        "lan_status": "ok",
        "wlan_status": "ok",
        "www_status": "error",
        "device_count": 3,
        "adopted_count": 3,
        "offline_count": 0,
        "client_count": 47,
    }


def _build_offline_devices_health() -> dict[str, Any]:
    """Build a site health dict with offline devices."""
    return {
        "wan_status": "ok",
        "lan_status": "ok",
        "wlan_status": "ok",
        "www_status": "ok",
        "device_count": 3,
        "adopted_count": 2,
        "offline_count": 1,
        "client_count": 30,
    }


def _build_empty_site_health() -> dict[str, Any]:
    """Build a site health dict for an empty site."""
    return {
        "wan_status": "unknown",
        "lan_status": "unknown",
        "wlan_status": "unknown",
        "www_status": "unknown",
        "device_count": 0,
        "adopted_count": 0,
        "offline_count": 0,
        "client_count": 0,
    }


def _build_no_events() -> list[dict[str, Any]]:
    """Build an empty event list."""
    return []


def _build_warning_events() -> list[dict[str, Any]]:
    """Build an event list with warning-level events."""
    return [
        {
            "timestamp": datetime.now(tz=UTC).isoformat(),
            "type": "EVT_SW_PoeOverload",
            "severity": "warning",
            "message": "PoE overload detected on port 5",
            "subsystem": "lan",
            "device_id": "74:ac:b9:bb:33:44",
            "client_mac": None,
        },
        {
            "timestamp": datetime.now(tz=UTC).isoformat(),
            "type": "EVT_AP_ChannelChange",
            "severity": "info",
            "message": "AP changed channel from 6 to 11",
            "subsystem": "wlan",
            "device_id": None,
            "client_mac": None,
        },
    ]


def _build_critical_events() -> list[dict[str, Any]]:
    """Build an event list with critical-level events."""
    return [
        {
            "timestamp": datetime.now(tz=UTC).isoformat(),
            "type": "EVT_GW_WANTransition",
            "severity": "critical",
            "message": "WAN interface went down",
            "subsystem": "wan",
            "device_id": "f0:9f:c2:aa:11:22",
            "client_mac": None,
        },
    ]


def _build_no_firmware_updates() -> list[dict[str, Any]]:
    """Build a firmware list where everything is up to date."""
    return [
        {
            "device_id": "64a1b2c3d4e5f6a7b8c9d0e1",
            "model": "UXG-Max",
            "current_version": "4.0.6.6754",
            "latest_version": "",
            "upgrade_available": False,
            "product_line": "network",
        },
        {
            "device_id": "64c3d4e5f6a7b8c9d0e1f2a3",
            "model": "U6-Pro",
            "current_version": "7.0.76.15293",
            "latest_version": "",
            "upgrade_available": False,
            "product_line": "network",
        },
    ]


def _build_firmware_updates_available() -> list[dict[str, Any]]:
    """Build a firmware list with upgrades available."""
    return [
        {
            "device_id": "64a1b2c3d4e5f6a7b8c9d0e1",
            "model": "UXG-Max",
            "current_version": "4.0.6.6754",
            "latest_version": "",
            "upgrade_available": False,
            "product_line": "network",
        },
        {
            "device_id": "64b2c3d4e5f6a7b8c9d0e1f2",
            "model": "USLITE16P",
            "current_version": "7.0.50.15116",
            "latest_version": "7.0.72.15290",
            "upgrade_available": True,
            "product_line": "network",
        },
    ]


def _build_healthy_isp() -> dict[str, Any]:
    """Build healthy ISP metrics."""
    return {
        "wan_ip": "203.0.113.42",
        "isp_name": "Example ISP",
        "isp_organization": "Example Telecom Corp",
        "latency_ms": 8,
        "speedtest_ping_ms": 8,
        "download_mbps": 423.7,
        "upload_mbps": 38.2,
        "speedtest_lastrun": 1710876000,
        "uptime_seconds": 1728432,
        "drops": 0,
        "tx_bytes_rate": 482910,
        "rx_bytes_rate": 1293847,
        "wan_status": "ok",
    }


def _build_wan_down_isp() -> dict[str, Any]:
    """Build ISP metrics with WAN down."""
    return {
        "wan_ip": "",
        "isp_name": "",
        "isp_organization": "",
        "latency_ms": None,
        "speedtest_ping_ms": None,
        "download_mbps": None,
        "upload_mbps": None,
        "speedtest_lastrun": None,
        "uptime_seconds": None,
        "drops": None,
        "tx_bytes_rate": 0,
        "rx_bytes_rate": 0,
        "wan_status": "error",
    }


# ---------------------------------------------------------------------------
# Helper to build mock context manager for all 4 tools
# ---------------------------------------------------------------------------


def _patch_all_tools(
    health: dict[str, Any] | None = None,
    events: list[dict[str, Any]] | None = None,
    firmware: list[dict[str, Any]] | None = None,
    isp: dict[str, Any] | None = None,
) -> tuple[AsyncMock, AsyncMock, AsyncMock, AsyncMock]:
    """Create AsyncMock instances for all 4 health tools with specified return values."""
    mock_site_health = AsyncMock(
        return_value=health if health is not None else _build_healthy_site_health()
    )
    mock_events = AsyncMock(
        return_value=events if events is not None else _build_no_events()
    )
    mock_firmware = AsyncMock(
        return_value=firmware if firmware is not None else _build_no_firmware_updates()
    )
    mock_isp = AsyncMock(
        return_value=isp if isp is not None else _build_healthy_isp()
    )
    return mock_site_health, mock_events, mock_firmware, mock_isp


# ---------------------------------------------------------------------------
# Classification unit tests
# ---------------------------------------------------------------------------


class TestClassifySiteHealth:
    """Unit tests for _classify_site_health."""

    def test_all_healthy_no_findings(self) -> None:
        findings = _classify_site_health(_build_healthy_site_health())
        # No critical or warning findings for a healthy site.
        critical = [f for f in findings if f.severity == Severity.CRITICAL]
        warning = [f for f in findings if f.severity == Severity.WARNING]
        assert len(critical) == 0
        assert len(warning) == 0

    def test_wan_down_is_critical(self) -> None:
        findings = _classify_site_health(_build_wan_down_site_health())
        critical = [f for f in findings if f.severity == Severity.CRITICAL]
        assert len(critical) >= 1
        titles = [f.title for f in critical]
        assert any("WAN" in t for t in titles)

    def test_offline_devices_is_critical(self) -> None:
        findings = _classify_site_health(_build_offline_devices_health())
        critical = [f for f in findings if f.severity == Severity.CRITICAL]
        assert len(critical) >= 1
        titles = [f.title for f in critical]
        assert any("offline" in t for t in titles)

    def test_empty_site_subsystems_unknown(self) -> None:
        """Unknown subsystem statuses should generate critical findings."""
        findings = _classify_site_health(_build_empty_site_health())
        critical = [f for f in findings if f.severity == Severity.CRITICAL]
        # All 4 subsystems are "unknown", which != "ok"
        assert len(critical) == 4


class TestClassifyEvents:
    """Unit tests for _classify_events."""

    def test_no_events_no_findings(self) -> None:
        findings = _classify_events([])
        assert len(findings) == 0

    def test_info_events_ignored(self) -> None:
        events = [
            {"type": "EVT_INFO", "severity": "info", "message": "Normal event"},
        ]
        findings = _classify_events(events)
        assert len(findings) == 0

    def test_warning_event_classified(self) -> None:
        events = _build_warning_events()
        findings = _classify_events(events)
        # Only the warning event should create a finding.
        assert len(findings) == 1
        assert findings[0].severity == Severity.WARNING
        assert "EVT_SW_PoeOverload" in findings[0].title

    def test_critical_event_classified(self) -> None:
        events = _build_critical_events()
        findings = _classify_events(events)
        assert len(findings) == 1
        assert findings[0].severity == Severity.CRITICAL


class TestClassifyFirmware:
    """Unit tests for _classify_firmware."""

    def test_no_updates_no_findings(self) -> None:
        findings = _classify_firmware(_build_no_firmware_updates())
        assert len(findings) == 0

    def test_updates_available_is_warning(self) -> None:
        findings = _classify_firmware(_build_firmware_updates_available())
        assert len(findings) == 1
        assert findings[0].severity == Severity.WARNING
        assert "1 device(s)" in findings[0].title
        assert "USLITE16P" in findings[0].detail

    def test_empty_firmware_list(self) -> None:
        findings = _classify_firmware([])
        assert len(findings) == 0


class TestClassifyIsp:
    """Unit tests for _classify_isp."""

    def test_healthy_isp_informational_only(self) -> None:
        findings = _classify_isp(_build_healthy_isp())
        critical = [f for f in findings if f.severity == Severity.CRITICAL]
        info = [f for f in findings if f.severity == Severity.INFORMATIONAL]
        assert len(critical) == 0
        assert len(info) == 1
        assert "ISP metrics" in info[0].title
        assert "Example ISP" in info[0].detail

    def test_wan_down_is_critical(self) -> None:
        findings = _classify_isp(_build_wan_down_isp())
        critical = [f for f in findings if f.severity == Severity.CRITICAL]
        assert len(critical) == 1
        assert "WAN link" in critical[0].title


# ---------------------------------------------------------------------------
# check_health integration tests
# ---------------------------------------------------------------------------


class TestCheckHealth:
    """Test the check_health health agent orchestrator."""

    async def test_all_healthy(self) -> None:
        """All-healthy data produces no critical/warning findings."""
        mock_health, mock_events, mock_firmware, mock_isp = _patch_all_tools()

        with (
            patch("unifi.agents.health.unifi__health__get_site_health", mock_health),
            patch("unifi.agents.health.unifi__health__get_events", mock_events),
            patch("unifi.agents.health.unifi__health__get_firmware_status", mock_firmware),
            patch("unifi.agents.health.unifi__health__get_isp_metrics", mock_isp),
        ):
            result = await check_health()

        assert "## Health Check" in result
        assert "**Devices:** 3" in result
        assert "**Clients:** 47" in result
        assert "All systems healthy" in result
        assert "3 device(s) online" in result
        assert "47 client(s) connected" in result

    async def test_wan_down_critical(self) -> None:
        """WAN down produces critical findings in the report."""
        mock_health, mock_events, mock_firmware, mock_isp = _patch_all_tools(
            health=_build_wan_down_site_health(),
            isp=_build_wan_down_isp(),
        )

        with (
            patch("unifi.agents.health.unifi__health__get_site_health", mock_health),
            patch("unifi.agents.health.unifi__health__get_events", mock_events),
            patch("unifi.agents.health.unifi__health__get_firmware_status", mock_firmware),
            patch("unifi.agents.health.unifi__health__get_isp_metrics", mock_isp),
        ):
            result = await check_health()

        assert "CRITICAL" in result
        assert "WAN" in result
        # Should NOT show "All systems healthy"
        assert "All systems healthy" not in result

    async def test_firmware_updates_warning(self) -> None:
        """Firmware updates produce warning findings."""
        mock_health, mock_events, mock_firmware, mock_isp = _patch_all_tools(
            firmware=_build_firmware_updates_available(),
        )

        with (
            patch("unifi.agents.health.unifi__health__get_site_health", mock_health),
            patch("unifi.agents.health.unifi__health__get_events", mock_events),
            patch("unifi.agents.health.unifi__health__get_firmware_status", mock_firmware),
            patch("unifi.agents.health.unifi__health__get_isp_metrics", mock_isp),
        ):
            result = await check_health()

        assert "Warning" in result
        assert "Firmware update" in result
        assert "USLITE16P" in result
        # Should NOT show "All systems healthy" (there's a warning)
        assert "All systems healthy" not in result

    async def test_warning_events(self) -> None:
        """Recent warning events produce warning findings."""
        mock_health, mock_events, mock_firmware, mock_isp = _patch_all_tools(
            events=_build_warning_events(),
        )

        with (
            patch("unifi.agents.health.unifi__health__get_site_health", mock_health),
            patch("unifi.agents.health.unifi__health__get_events", mock_events),
            patch("unifi.agents.health.unifi__health__get_firmware_status", mock_firmware),
            patch("unifi.agents.health.unifi__health__get_isp_metrics", mock_isp),
        ):
            result = await check_health()

        assert "Warning" in result
        assert "EVT_SW_PoeOverload" in result

    async def test_offline_devices_critical(self) -> None:
        """Offline devices produce critical findings."""
        mock_health, mock_events, mock_firmware, mock_isp = _patch_all_tools(
            health=_build_offline_devices_health(),
        )

        with (
            patch("unifi.agents.health.unifi__health__get_site_health", mock_health),
            patch("unifi.agents.health.unifi__health__get_events", mock_events),
            patch("unifi.agents.health.unifi__health__get_firmware_status", mock_firmware),
            patch("unifi.agents.health.unifi__health__get_isp_metrics", mock_isp),
        ):
            result = await check_health()

        assert "CRITICAL" in result
        assert "offline" in result
        assert "All systems healthy" not in result

    async def test_mixed_findings(self) -> None:
        """Mixed critical + warning + informational all appear in report."""
        # Use offline devices for CRITICAL, firmware for WARNING,
        # and healthy ISP for INFORMATIONAL (ISP metrics summary).
        mock_health, mock_events, mock_firmware, mock_isp = _patch_all_tools(
            health=_build_offline_devices_health(),
            events=_build_warning_events(),
            firmware=_build_firmware_updates_available(),
            isp=_build_healthy_isp(),
        )

        with (
            patch("unifi.agents.health.unifi__health__get_site_health", mock_health),
            patch("unifi.agents.health.unifi__health__get_events", mock_events),
            patch("unifi.agents.health.unifi__health__get_firmware_status", mock_firmware),
            patch("unifi.agents.health.unifi__health__get_isp_metrics", mock_isp),
        ):
            result = await check_health()

        # All three severity levels should appear.
        assert "[!!!] CRITICAL" in result
        assert "[!] Warning" in result
        assert "[i] Informational" in result
        assert "All systems healthy" not in result

    async def test_severity_ordering(self) -> None:
        """Critical findings appear before warning before informational."""
        # Use offline devices for CRITICAL, firmware for WARNING,
        # and healthy ISP for INFORMATIONAL (ISP metrics summary).
        mock_health, mock_events, mock_firmware, mock_isp = _patch_all_tools(
            health=_build_offline_devices_health(),
            events=_build_warning_events(),
            firmware=_build_firmware_updates_available(),
            isp=_build_healthy_isp(),
        )

        with (
            patch("unifi.agents.health.unifi__health__get_site_health", mock_health),
            patch("unifi.agents.health.unifi__health__get_events", mock_events),
            patch("unifi.agents.health.unifi__health__get_firmware_status", mock_firmware),
            patch("unifi.agents.health.unifi__health__get_isp_metrics", mock_isp),
        ):
            result = await check_health()

        # Verify ordering by finding positions.
        critical_pos = result.index("[!!!] CRITICAL")
        warning_pos = result.index("[!] Warning")
        info_pos = result.index("[i] Informational")

        assert critical_pos < warning_pos < info_pos

    async def test_empty_site(self) -> None:
        """Empty site (no devices) still produces a valid report."""
        mock_health, mock_events, mock_firmware, mock_isp = _patch_all_tools(
            health=_build_empty_site_health(),
            events=[],
            firmware=[],
            isp={
                "wan_ip": "",
                "isp_name": "",
                "isp_organization": "",
                "latency_ms": None,
                "speedtest_ping_ms": None,
                "download_mbps": None,
                "upload_mbps": None,
                "speedtest_lastrun": None,
                "uptime_seconds": None,
                "drops": None,
                "tx_bytes_rate": 0,
                "rx_bytes_rate": 0,
                "wan_status": "unknown",
            },
        )

        with (
            patch("unifi.agents.health.unifi__health__get_site_health", mock_health),
            patch("unifi.agents.health.unifi__health__get_events", mock_events),
            patch("unifi.agents.health.unifi__health__get_firmware_status", mock_firmware),
            patch("unifi.agents.health.unifi__health__get_isp_metrics", mock_isp),
        ):
            result = await check_health()

        assert "## Health Check" in result
        assert "**Devices:** 0" in result
        assert "**Clients:** 0" in result
        # Unknown subsystem statuses generate critical findings
        assert "CRITICAL" in result

    async def test_custom_site_id_passthrough(self) -> None:
        """Custom site_id is passed through to all tool calls."""
        mock_health, mock_events, mock_firmware, mock_isp = _patch_all_tools()

        with (
            patch("unifi.agents.health.unifi__health__get_site_health", mock_health),
            patch("unifi.agents.health.unifi__health__get_events", mock_events),
            patch("unifi.agents.health.unifi__health__get_firmware_status", mock_firmware),
            patch("unifi.agents.health.unifi__health__get_isp_metrics", mock_isp),
        ):
            await check_health(site_id="my-remote-site")

        mock_health.assert_called_once_with("my-remote-site")
        mock_events.assert_called_once_with("my-remote-site", hours=24)
        mock_firmware.assert_called_once_with("my-remote-site")
        mock_isp.assert_called_once_with("my-remote-site")

    async def test_default_site_id(self) -> None:
        """Default site_id is 'default'."""
        mock_health, mock_events, mock_firmware, mock_isp = _patch_all_tools()

        with (
            patch("unifi.agents.health.unifi__health__get_site_health", mock_health),
            patch("unifi.agents.health.unifi__health__get_events", mock_events),
            patch("unifi.agents.health.unifi__health__get_firmware_status", mock_firmware),
            patch("unifi.agents.health.unifi__health__get_isp_metrics", mock_isp),
        ):
            await check_health()

        mock_health.assert_called_once_with("default")
        mock_events.assert_called_once_with("default", hours=24)
        mock_firmware.assert_called_once_with("default")
        mock_isp.assert_called_once_with("default")

    async def test_report_uses_ox_format_severity_report(self) -> None:
        """Report uses OX format_severity_report with proper severity markers."""
        mock_health, mock_events, mock_firmware, mock_isp = _patch_all_tools(
            health=_build_wan_down_site_health(),
            isp=_build_wan_down_isp(),
        )

        with (
            patch("unifi.agents.health.unifi__health__get_site_health", mock_health),
            patch("unifi.agents.health.unifi__health__get_events", mock_events),
            patch("unifi.agents.health.unifi__health__get_firmware_status", mock_firmware),
            patch("unifi.agents.health.unifi__health__get_isp_metrics", mock_isp),
        ):
            result = await check_health()

        # OX format_severity_report uses "## Findings" heading.
        assert "## Findings" in result
        # OX severity markers.
        assert "[!!!]" in result

    async def test_report_uses_ox_format_summary(self) -> None:
        """Report uses OX format_summary with pipe-separated stats."""
        mock_health, mock_events, mock_firmware, mock_isp = _patch_all_tools()

        with (
            patch("unifi.agents.health.unifi__health__get_site_health", mock_health),
            patch("unifi.agents.health.unifi__health__get_events", mock_events),
            patch("unifi.agents.health.unifi__health__get_firmware_status", mock_firmware),
            patch("unifi.agents.health.unifi__health__get_isp_metrics", mock_isp),
        ):
            result = await check_health()

        # OX format_summary uses pipe-separated stats.
        assert "**Devices:** 3 | **Clients:** 47" in result

    async def test_isp_summary_in_informational(self) -> None:
        """ISP metrics appear as an informational finding."""
        mock_health, mock_events, mock_firmware, mock_isp = _patch_all_tools()

        with (
            patch("unifi.agents.health.unifi__health__get_site_health", mock_health),
            patch("unifi.agents.health.unifi__health__get_events", mock_events),
            patch("unifi.agents.health.unifi__health__get_firmware_status", mock_firmware),
            patch("unifi.agents.health.unifi__health__get_isp_metrics", mock_isp),
        ):
            result = await check_health()

        assert "ISP metrics" in result
        assert "Example ISP" in result
        assert "423.7 Mbps" in result

    async def test_critical_count_in_summary(self) -> None:
        """Summary stats include critical count when findings exist."""
        mock_health, mock_events, mock_firmware, mock_isp = _patch_all_tools(
            health=_build_wan_down_site_health(),
            isp=_build_wan_down_isp(),
        )

        with (
            patch("unifi.agents.health.unifi__health__get_site_health", mock_health),
            patch("unifi.agents.health.unifi__health__get_events", mock_events),
            patch("unifi.agents.health.unifi__health__get_firmware_status", mock_firmware),
            patch("unifi.agents.health.unifi__health__get_isp_metrics", mock_isp),
        ):
            result = await check_health()

        assert "**Critical:**" in result
