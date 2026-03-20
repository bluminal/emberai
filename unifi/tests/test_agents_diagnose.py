"""Tests for the diagnose agent (diagnose_target orchestrator)."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, patch

from unifi.agents.diagnose import (
    _analyze_client,
    _analyze_device,
    _device_matches_query,
    _format_bytes,
    _format_uptime,
    _resolve_target,
    diagnose_target,
)
from unifi.output import Severity

# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------


def _build_device(**overrides: Any) -> dict[str, Any]:
    """Build a device dict matching what list_devices returns."""
    base: dict[str, Any] = {
        "device_id": "64c3d4e5f6a7b8c9d0e1f2a3",
        "name": "Office-AP-Main",
        "model": "U6-Pro",
        "mac": "e0:63:da:cc:55:66",
        "ip": "192.168.1.20",
        "status": "connected",
        "uptime": 1728430,
        "firmware": "7.0.76.15293",
        "product_line": "network",
        "is_console": False,
    }
    base.update(overrides)
    return base


def _build_client(**overrides: Any) -> dict[str, Any]:
    """Build a client dict matching what search_clients returns."""
    base: dict[str, Any] = {
        "client_mac": "a4:83:e7:11:22:33",
        "hostname": "macbook-pro-jdoe",
        "ip": "192.168.1.101",
        "vlan_id": "5f9a8b7c6d5e4f3a2b1c0001",
        "ap_id": "e0:63:da:cc:55:66",
        "is_wired": False,
        "is_guest": False,
        "uptime": 43210,
        "rssi": 56,
        "ssid": "HomeNet",
        "tx_bytes": 2847291038,
        "rx_bytes": 18293746501,
    }
    base.update(overrides)
    return base


def _build_device_health(**overrides: Any) -> dict[str, Any]:
    """Build a device health dict matching what get_device_health returns."""
    base: dict[str, Any] = {
        "device_id": "64c3d4e5f6a7b8c9d0e1f2a3",
        "name": "Office-AP-Main",
        "mac": "e0:63:da:cc:55:66",
        "model": "U6-Pro",
        "status": "connected",
        "uptime": 1728430,
        "cpu_usage_pct": 8.1,
        "mem_usage_pct": 34.2,
        "temperature_c": 42.0,
        "satisfaction": 95,
        "upgrade_available": False,
        "current_firmware": "7.0.76.15293",
        "upgrade_firmware": "",
    }
    base.update(overrides)
    return base


def _build_event(**overrides: Any) -> dict[str, Any]:
    """Build an event dict matching what get_events returns."""
    base: dict[str, Any] = {
        "timestamp": "2024-03-19T14:32:10Z",
        "type": "EVT_WU_Connected",
        "severity": "info",
        "message": "Client connected",
        "subsystem": "wlan",
        "device_id": None,
        "client_mac": None,
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# Helper unit tests
# ---------------------------------------------------------------------------


class TestDeviceMatchesQuery:
    """Verify device matching helper."""

    def test_match_by_mac(self) -> None:
        device = _build_device()
        assert _device_matches_query(device, "e0:63:da:cc:55:66")

    def test_match_by_name(self) -> None:
        device = _build_device()
        assert _device_matches_query(device, "office-ap")

    def test_match_by_ip(self) -> None:
        device = _build_device()
        assert _device_matches_query(device, "192.168.1.20")

    def test_no_match(self) -> None:
        device = _build_device()
        assert not _device_matches_query(device, "nonexistent")

    def test_partial_match(self) -> None:
        """The query_lower param is pre-lowered; device fields are lowered internally."""
        device = _build_device()
        assert _device_matches_query(device, "office-ap")


class TestFormatUptime:
    """Verify uptime formatting helper."""

    def test_days(self) -> None:
        assert _format_uptime(90061) == "1d 1h 1m"

    def test_hours(self) -> None:
        assert _format_uptime(3660) == "1h 1m"

    def test_zero(self) -> None:
        assert _format_uptime(0) == "0m"


class TestFormatBytes:
    """Verify byte formatting helper."""

    def test_zero(self) -> None:
        assert _format_bytes(0) == "0 B"

    def test_none(self) -> None:
        assert _format_bytes(None) == "0 B"

    def test_megabytes(self) -> None:
        assert _format_bytes(1048576) == "1.0 MB"


# ---------------------------------------------------------------------------
# Target resolution tests
# ---------------------------------------------------------------------------


class TestResolveTarget:
    """Tests for _resolve_target."""

    async def test_resolve_device_by_exact_mac(self) -> None:
        """Exact MAC match resolves to device."""
        mock_search = AsyncMock(return_value=[])
        mock_list = AsyncMock(return_value=[_build_device()])

        with (
            patch("unifi.agents.diagnose.unifi__clients__search_clients", mock_search),
            patch("unifi.agents.diagnose.unifi__topology__list_devices", mock_list),
        ):
            result = await _resolve_target("e0:63:da:cc:55:66", "default")

        assert result["type"] == "device"
        assert result["item"]["mac"] == "e0:63:da:cc:55:66"

    async def test_resolve_client_by_exact_mac(self) -> None:
        """Exact MAC match resolves to client."""
        mock_search = AsyncMock(return_value=[_build_client()])
        mock_list = AsyncMock(return_value=[])

        with (
            patch("unifi.agents.diagnose.unifi__clients__search_clients", mock_search),
            patch("unifi.agents.diagnose.unifi__topology__list_devices", mock_list),
        ):
            result = await _resolve_target("a4:83:e7:11:22:33", "default")

        assert result["type"] == "client"
        assert result["item"]["client_mac"] == "a4:83:e7:11:22:33"

    async def test_resolve_not_found(self) -> None:
        """No matches returns not_found."""
        mock_search = AsyncMock(return_value=[])
        mock_list = AsyncMock(return_value=[])

        with (
            patch("unifi.agents.diagnose.unifi__clients__search_clients", mock_search),
            patch("unifi.agents.diagnose.unifi__topology__list_devices", mock_list),
        ):
            result = await _resolve_target("nonexistent", "default")

        assert result["type"] == "not_found"

    async def test_resolve_ambiguous(self) -> None:
        """Multiple matches returns ambiguous."""
        mock_search = AsyncMock(return_value=[
            _build_client(client_mac="aa:bb:cc:11:22:33", hostname="device-a"),
            _build_client(client_mac="aa:bb:cc:44:55:66", hostname="device-b"),
        ])
        mock_list = AsyncMock(return_value=[])

        with (
            patch("unifi.agents.diagnose.unifi__clients__search_clients", mock_search),
            patch("unifi.agents.diagnose.unifi__topology__list_devices", mock_list),
        ):
            result = await _resolve_target("aa:bb:cc", "default")

        assert result["type"] == "ambiguous"
        assert len(result["matches"]) == 2

    async def test_resolve_single_device(self) -> None:
        """Single device match resolves directly."""
        mock_search = AsyncMock(return_value=[])
        mock_list = AsyncMock(return_value=[_build_device(name="USG-Gateway")])

        with (
            patch("unifi.agents.diagnose.unifi__clients__search_clients", mock_search),
            patch("unifi.agents.diagnose.unifi__topology__list_devices", mock_list),
        ):
            result = await _resolve_target("USG-Gateway", "default")

        assert result["type"] == "device"

    async def test_resolve_single_client(self) -> None:
        """Single client match resolves directly."""
        mock_search = AsyncMock(return_value=[_build_client()])
        mock_list = AsyncMock(return_value=[])

        with (
            patch("unifi.agents.diagnose.unifi__clients__search_clients", mock_search),
            patch("unifi.agents.diagnose.unifi__topology__list_devices", mock_list),
        ):
            result = await _resolve_target("macbook-pro-jdoe", "default")

        assert result["type"] == "client"


# ---------------------------------------------------------------------------
# Analysis tests
# ---------------------------------------------------------------------------


class TestAnalyzeClient:
    """Tests for _analyze_client."""

    def test_healthy_client(self) -> None:
        """Healthy client produces informational finding."""
        client = _build_client(rssi=56)
        findings = _analyze_client(client, None, [])
        assert len(findings) == 1
        assert findings[0].severity == Severity.INFORMATIONAL
        assert "No issues" in findings[0].title

    def test_poor_signal(self) -> None:
        """Very poor RSSI triggers critical finding."""
        client = _build_client(rssi=15)
        findings = _analyze_client(client, None, [])
        assert any(f.severity == Severity.CRITICAL for f in findings)
        assert any("signal" in f.title.lower() for f in findings)

    def test_fair_signal(self) -> None:
        """Fair RSSI triggers warning finding."""
        client = _build_client(rssi=25)
        findings = _analyze_client(client, None, [])
        assert any(f.severity == Severity.WARNING for f in findings)

    def test_ap_disconnected(self) -> None:
        """Disconnected AP triggers critical finding."""
        client = _build_client()
        ap_health = _build_device_health(status="disconnected")
        findings = _analyze_client(client, ap_health, [])
        assert any(
            f.severity == Severity.CRITICAL and "AP" in f.title
            for f in findings
        )

    def test_ap_high_cpu(self) -> None:
        """AP with high CPU triggers warning."""
        client = _build_client()
        ap_health = _build_device_health(cpu_usage_pct=90.0)
        findings = _analyze_client(client, ap_health, [])
        assert any("CPU" in f.title for f in findings)

    def test_ap_high_memory(self) -> None:
        """AP with high memory triggers warning."""
        client = _build_client()
        ap_health = _build_device_health(mem_usage_pct=92.0)
        findings = _analyze_client(client, ap_health, [])
        assert any("memory" in f.title.lower() for f in findings)

    def test_disconnect_events(self) -> None:
        """Disconnect events trigger warning."""
        client = _build_client()
        events = [
            _build_event(
                type="EVT_WU_Disconnected",
                client_mac="a4:83:e7:11:22:33",
            ),
        ]
        findings = _analyze_client(client, None, events)
        assert any("disconnect" in f.title.lower() for f in findings)

    def test_wired_client_no_signal_check(self) -> None:
        """Wired clients don't get signal quality checks."""
        client = _build_client(is_wired=True, rssi=10)
        findings = _analyze_client(client, None, [])
        assert not any("signal" in f.title.lower() for f in findings)


class TestAnalyzeDevice:
    """Tests for _analyze_device."""

    def test_healthy_device(self) -> None:
        """Healthy device produces informational finding."""
        health = _build_device_health()
        findings = _analyze_device(health, [])
        assert len(findings) == 1
        assert findings[0].severity == Severity.INFORMATIONAL

    def test_disconnected_device(self) -> None:
        """Disconnected device triggers critical finding."""
        health = _build_device_health(status="disconnected")
        findings = _analyze_device(health, [])
        assert any(f.severity == Severity.CRITICAL for f in findings)

    def test_high_cpu(self) -> None:
        """High CPU triggers warning."""
        health = _build_device_health(cpu_usage_pct=90.0)
        findings = _analyze_device(health, [])
        assert any("CPU" in f.title for f in findings)

    def test_high_memory(self) -> None:
        """High memory triggers warning."""
        health = _build_device_health(mem_usage_pct=92.0)
        findings = _analyze_device(health, [])
        assert any("memory" in f.title.lower() for f in findings)

    def test_high_temperature(self) -> None:
        """High temperature triggers warning."""
        health = _build_device_health(temperature_c=80.0)
        findings = _analyze_device(health, [])
        assert any("temperature" in f.title.lower() for f in findings)

    def test_firmware_upgrade_available(self) -> None:
        """Firmware upgrade available triggers informational finding."""
        health = _build_device_health(
            upgrade_available=True,
            current_firmware="7.0.50",
            upgrade_firmware="7.0.76",
        )
        findings = _analyze_device(health, [])
        assert any("firmware" in f.title.lower() for f in findings)

    def test_warning_events(self) -> None:
        """Warning events trigger finding."""
        health = _build_device_health()
        events = [
            _build_event(
                severity="warning",
                type="EVT_SW_PoeOverload",
                message="PoE overload",
                device_id="e0:63:da:cc:55:66",
            ),
        ]
        findings = _analyze_device(health, events)
        assert any("event" in f.title.lower() for f in findings)

    def test_normal_cpu_no_warning(self) -> None:
        """Normal CPU usage does not trigger warning."""
        health = _build_device_health(cpu_usage_pct=50.0)
        findings = _analyze_device(health, [])
        assert not any("CPU" in f.title for f in findings)

    def test_normal_temperature_no_warning(self) -> None:
        """Normal temperature does not trigger warning."""
        health = _build_device_health(temperature_c=45.0)
        findings = _analyze_device(health, [])
        assert not any("temperature" in f.title.lower() for f in findings)


# ---------------------------------------------------------------------------
# End-to-end agent tests
# ---------------------------------------------------------------------------


class TestDiagnoseTarget:
    """Tests for the diagnose_target agent function."""

    async def test_diagnose_client(self) -> None:
        """Client diagnosis produces a full report."""
        mock_search = AsyncMock(return_value=[_build_client()])
        mock_list_devices = AsyncMock(return_value=[])
        mock_get_client = AsyncMock(return_value=_build_client())
        mock_device_health = AsyncMock(return_value=_build_device_health())
        mock_events = AsyncMock(return_value=[])

        with (
            patch("unifi.agents.diagnose.unifi__clients__search_clients", mock_search),
            patch("unifi.agents.diagnose.unifi__topology__list_devices", mock_list_devices),
            patch("unifi.agents.diagnose.unifi__clients__get_client", mock_get_client),
            patch("unifi.agents.diagnose.unifi__health__get_device_health", mock_device_health),
            patch("unifi.agents.diagnose.unifi__health__get_events", mock_events),
        ):
            result = await diagnose_target("a4:83:e7:11:22:33")

        assert "Diagnosis:" in result
        assert "macbook-pro-jdoe" in result
        assert "Client Details" in result
        assert "Diagnostic Findings" in result
        assert isinstance(result, str)

    async def test_diagnose_device(self) -> None:
        """Device diagnosis produces a full report."""
        mock_search = AsyncMock(return_value=[])
        mock_list_devices = AsyncMock(return_value=[_build_device()])
        mock_device_health = AsyncMock(return_value=_build_device_health())
        mock_events = AsyncMock(return_value=[])

        with (
            patch("unifi.agents.diagnose.unifi__clients__search_clients", mock_search),
            patch("unifi.agents.diagnose.unifi__topology__list_devices", mock_list_devices),
            patch("unifi.agents.diagnose.unifi__health__get_device_health", mock_device_health),
            patch("unifi.agents.diagnose.unifi__health__get_events", mock_events),
        ):
            result = await diagnose_target("e0:63:da:cc:55:66")

        assert "Diagnosis:" in result
        assert "Office-AP-Main" in result
        assert "Device Details" in result
        assert "Diagnostic Findings" in result

    async def test_diagnose_not_found(self) -> None:
        """Not-found target produces appropriate message."""
        mock_search = AsyncMock(return_value=[])
        mock_list_devices = AsyncMock(return_value=[])

        with (
            patch("unifi.agents.diagnose.unifi__clients__search_clients", mock_search),
            patch("unifi.agents.diagnose.unifi__topology__list_devices", mock_list_devices),
        ):
            result = await diagnose_target("nonexistent")

        assert "Not Found" in result
        assert "nonexistent" in result

    async def test_diagnose_ambiguous(self) -> None:
        """Ambiguous target returns assumption resolution prompt."""
        mock_search = AsyncMock(return_value=[
            _build_client(client_mac="aa:bb:cc:11:22:33", hostname="device-a"),
            _build_client(client_mac="aa:bb:cc:44:55:66", hostname="device-b"),
        ])
        mock_list_devices = AsyncMock(return_value=[])

        with (
            patch("unifi.agents.diagnose.unifi__clients__search_clients", mock_search),
            patch("unifi.agents.diagnose.unifi__topology__list_devices", mock_list_devices),
        ):
            result = await diagnose_target("aa:bb:cc")

        assert "Assumption Resolution" in result
        assert "device-a" in result
        assert "device-b" in result

    async def test_diagnose_custom_site_id(self) -> None:
        """Custom site_id is passed through."""
        mock_search = AsyncMock(return_value=[_build_client()])
        mock_list_devices = AsyncMock(return_value=[])
        mock_get_client = AsyncMock(return_value=_build_client())
        mock_device_health = AsyncMock(return_value=_build_device_health())
        mock_events = AsyncMock(return_value=[])

        with (
            patch("unifi.agents.diagnose.unifi__clients__search_clients", mock_search),
            patch("unifi.agents.diagnose.unifi__topology__list_devices", mock_list_devices),
            patch("unifi.agents.diagnose.unifi__clients__get_client", mock_get_client),
            patch("unifi.agents.diagnose.unifi__health__get_device_health", mock_device_health),
            patch("unifi.agents.diagnose.unifi__health__get_events", mock_events),
        ):
            await diagnose_target("a4:83:e7:11:22:33", site_id="branch")

        mock_search.assert_called_once_with("a4:83:e7:11:22:33", site_id="branch")

    async def test_diagnose_device_with_issues(self) -> None:
        """Device with issues shows critical/warning findings."""
        mock_search = AsyncMock(return_value=[])
        mock_list_devices = AsyncMock(return_value=[_build_device()])
        mock_device_health = AsyncMock(return_value=_build_device_health(
            status="disconnected",
            cpu_usage_pct=95.0,
        ))
        mock_events = AsyncMock(return_value=[])

        with (
            patch("unifi.agents.diagnose.unifi__clients__search_clients", mock_search),
            patch("unifi.agents.diagnose.unifi__topology__list_devices", mock_list_devices),
            patch("unifi.agents.diagnose.unifi__health__get_device_health", mock_device_health),
            patch("unifi.agents.diagnose.unifi__health__get_events", mock_events),
        ):
            result = await diagnose_target("e0:63:da:cc:55:66")

        assert "CRITICAL" in result
        assert "disconnected" in result

    async def test_diagnose_client_poor_signal(self) -> None:
        """Client with poor signal shows critical finding."""
        mock_search = AsyncMock(return_value=[_build_client(rssi=10)])
        mock_list_devices = AsyncMock(return_value=[])
        mock_get_client = AsyncMock(return_value=_build_client(rssi=10))
        mock_device_health = AsyncMock(return_value=_build_device_health())
        mock_events = AsyncMock(return_value=[])

        with (
            patch("unifi.agents.diagnose.unifi__clients__search_clients", mock_search),
            patch("unifi.agents.diagnose.unifi__topology__list_devices", mock_list_devices),
            patch("unifi.agents.diagnose.unifi__clients__get_client", mock_get_client),
            patch("unifi.agents.diagnose.unifi__health__get_device_health", mock_device_health),
            patch("unifi.agents.diagnose.unifi__health__get_events", mock_events),
        ):
            result = await diagnose_target("a4:83:e7:11:22:33")

        assert "CRITICAL" in result
        assert "signal" in result.lower()

    async def test_diagnose_client_ap_health_failure_graceful(self) -> None:
        """AP health fetch failure is handled gracefully."""
        mock_search = AsyncMock(return_value=[_build_client()])
        mock_list_devices = AsyncMock(return_value=[])
        mock_get_client = AsyncMock(return_value=_build_client())
        mock_device_health = AsyncMock(side_effect=RuntimeError("AP unreachable"))
        mock_events = AsyncMock(return_value=[])

        with (
            patch("unifi.agents.diagnose.unifi__clients__search_clients", mock_search),
            patch("unifi.agents.diagnose.unifi__topology__list_devices", mock_list_devices),
            patch("unifi.agents.diagnose.unifi__clients__get_client", mock_get_client),
            patch("unifi.agents.diagnose.unifi__health__get_device_health", mock_device_health),
            patch("unifi.agents.diagnose.unifi__health__get_events", mock_events),
        ):
            result = await diagnose_target("a4:83:e7:11:22:33")

        # Should still produce a report even without AP health
        assert "Diagnosis:" in result
        assert "macbook-pro-jdoe" in result

    async def test_diagnose_device_health_failure_graceful(self) -> None:
        """Device health fetch failure is handled gracefully."""
        mock_search = AsyncMock(return_value=[])
        mock_list_devices = AsyncMock(return_value=[_build_device()])
        mock_device_health = AsyncMock(side_effect=RuntimeError("API error"))
        mock_events = AsyncMock(return_value=[])

        with (
            patch("unifi.agents.diagnose.unifi__clients__search_clients", mock_search),
            patch("unifi.agents.diagnose.unifi__topology__list_devices", mock_list_devices),
            patch("unifi.agents.diagnose.unifi__health__get_device_health", mock_device_health),
            patch("unifi.agents.diagnose.unifi__health__get_events", mock_events),
        ):
            result = await diagnose_target("e0:63:da:cc:55:66")

        # Should still produce a report with fallback data
        assert "Diagnosis:" in result
        assert "Office-AP-Main" in result

    async def test_diagnose_wired_client_no_ap_health(self) -> None:
        """Wired client diagnosis skips AP health fetch."""
        wired = _build_client(is_wired=True, ap_id=None, rssi=None)
        mock_search = AsyncMock(return_value=[wired])
        mock_list_devices = AsyncMock(return_value=[])
        mock_get_client = AsyncMock(return_value=wired)
        mock_device_health = AsyncMock()
        mock_events = AsyncMock(return_value=[])

        with (
            patch("unifi.agents.diagnose.unifi__clients__search_clients", mock_search),
            patch("unifi.agents.diagnose.unifi__topology__list_devices", mock_list_devices),
            patch("unifi.agents.diagnose.unifi__clients__get_client", mock_get_client),
            patch("unifi.agents.diagnose.unifi__health__get_device_health", mock_device_health),
            patch("unifi.agents.diagnose.unifi__health__get_events", mock_events),
        ):
            result = await diagnose_target("a4:83:e7:11:22:33")

        # AP health should not have been called
        mock_device_health.assert_not_called()
        assert "Wired" in result
