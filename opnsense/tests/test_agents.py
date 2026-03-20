"""Tests for OPNsense agent report generators.

Covers:
- VPN agent: status report with findings, empty state
- Security agent: IDS alert analysis, certificate expiry detection
- Services agent: DNS/DHCP report formatting
- Diagnostics agent: connectivity report
- Firmware agent: upgrade available, up-to-date states
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from tests.fixtures import load_fixture


def _make_client_multi(responses: dict[tuple[str, str, str], dict[str, Any]]) -> AsyncMock:
    """Create a mock client with per-endpoint responses."""
    client = AsyncMock()

    async def _get(
        module: str, controller: str, command: str, **kwargs: Any
    ) -> dict[str, Any]:
        key = (module, controller, command)
        if key in responses:
            return responses[key]
        return {"rows": []}

    async def _post(
        module: str, controller: str, command: str, **kwargs: Any
    ) -> dict[str, Any]:
        key = (module, controller, command)
        if key in responses:
            return responses[key]
        return {}

    client.get = AsyncMock(side_effect=_get)
    client.post = AsyncMock(side_effect=_post)
    return client


# ---------------------------------------------------------------------------
# VPN agent
# ---------------------------------------------------------------------------


class TestVPNAgent:
    @pytest.mark.asyncio
    async def test_report_with_mixed_status(self) -> None:
        from opnsense.agents.vpn import vpn_status_report

        client = _make_client_multi({
            ("ipsec", "sessions", "search"): load_fixture("ipsec_sessions.json"),
            ("openvpn", "instances", "search"): {"rows": []},
            ("wireguard", "client", "search"): load_fixture("wireguard_peers.json"),
        })

        report = await vpn_status_report(client)

        assert "VPN Status Report" in report
        assert "IPSec Tunnels" in report
        assert "WireGuard Peers" in report
        # Should mention disconnected tunnels
        assert "disconnected" in report.lower()

    @pytest.mark.asyncio
    async def test_report_all_empty(self) -> None:
        from opnsense.agents.vpn import vpn_status_report

        client = _make_client_multi({
            ("ipsec", "sessions", "search"): {"rows": []},
            ("openvpn", "instances", "search"): {"rows": []},
            ("wireguard", "client", "search"): {"rows": []},
        })

        report = await vpn_status_report(client)

        assert "No VPN tunnels configured" in report

    @pytest.mark.asyncio
    async def test_report_contains_peer_names(self) -> None:
        from opnsense.agents.vpn import vpn_status_report

        client = _make_client_multi({
            ("ipsec", "sessions", "search"): {"rows": []},
            ("openvpn", "instances", "search"): {"rows": []},
            ("wireguard", "client", "search"): load_fixture("wireguard_peers.json"),
        })

        report = await vpn_status_report(client)

        assert "mobile-laptop" in report
        assert "remote-office" in report


# ---------------------------------------------------------------------------
# Security agent
# ---------------------------------------------------------------------------


class TestSecurityAgent:
    @pytest.mark.asyncio
    async def test_report_with_alerts(self) -> None:
        from opnsense.agents.security import security_audit_report

        client = _make_client_multi({
            ("ids", "service", "queryAlerts"): load_fixture("ids_alerts.json"),
            ("trust", "cert", "search"): {"rows": []},
        })

        report = await security_audit_report(client)

        assert "Security Audit Report" in report
        assert "IDS Alerts" in report

    @pytest.mark.asyncio
    async def test_report_detects_high_severity(self) -> None:
        from opnsense.agents.security import security_audit_report

        client = _make_client_multi({
            ("ids", "service", "queryAlerts"): load_fixture("ids_alerts.json"),
            ("trust", "cert", "search"): {"rows": []},
        })

        report = await security_audit_report(client)

        # Should flag severity-1 alerts as HIGH
        assert "high-severity" in report.lower()

    @pytest.mark.asyncio
    async def test_report_with_expiring_cert(self) -> None:
        from opnsense.agents.security import security_audit_report

        cert_data = {
            "rows": [
                {
                    "cn": "about-to-expire.local",
                    "san": [],
                    "issuer": "CA",
                    "valid_from": "2025-01-01",
                    "valid_to": "2026-04-01",
                    "days_left": 13,
                    "in_use": ["webgui"],
                },
            ],
        }
        client = _make_client_multi({
            ("ids", "service", "queryAlerts"): {"rows": []},
            ("trust", "cert", "search"): cert_data,
        })

        report = await security_audit_report(client)

        assert "expiring soon" in report.lower()
        assert "about-to-expire.local" in report

    @pytest.mark.asyncio
    async def test_report_with_expired_cert(self) -> None:
        from opnsense.agents.security import security_audit_report

        cert_data = {
            "rows": [
                {
                    "cn": "expired.local",
                    "san": [],
                    "issuer": "CA",
                    "valid_from": "2024-01-01",
                    "valid_to": "2025-01-01",
                    "days_left": -78,
                    "in_use": ["openvpn"],
                },
            ],
        }
        client = _make_client_multi({
            ("ids", "service", "queryAlerts"): {"rows": []},
            ("trust", "cert", "search"): cert_data,
        })

        report = await security_audit_report(client)

        assert "expired" in report.lower()
        assert "expired.local" in report

    @pytest.mark.asyncio
    async def test_report_no_alerts_no_certs(self) -> None:
        from opnsense.agents.security import security_audit_report

        client = _make_client_multi({
            ("ids", "service", "queryAlerts"): {"rows": []},
            ("trust", "cert", "search"): {"rows": []},
        })

        report = await security_audit_report(client)

        assert "No IDS alerts" in report


# ---------------------------------------------------------------------------
# Services agent
# ---------------------------------------------------------------------------


class TestServicesAgent:
    @pytest.mark.asyncio
    async def test_report_with_data(self) -> None:
        from opnsense.agents.services import services_report

        dns_data = {
            "rows": [
                {
                    "uuid": "dns-1",
                    "hostname": "nas",
                    "domain": "home.local",
                    "server": "192.168.1.200",
                    "description": "NAS",
                },
            ],
        }

        client = _make_client_multi({
            ("unbound", "host", "searchHost"): dns_data,
            ("kea", "leases4", "search"): load_fixture("dhcp_leases.json"),
        })

        report = await services_report(client)

        assert "Services Report" in report
        assert "DNS Host Overrides" in report
        assert "DHCP Leases" in report
        assert "nas.home.local" in report

    @pytest.mark.asyncio
    async def test_report_empty_state(self) -> None:
        from opnsense.agents.services import services_report

        client = _make_client_multi({
            ("unbound", "host", "searchHost"): {"rows": []},
            ("kea", "leases4", "search"): {"rows": []},
        })

        report = await services_report(client)

        assert "No DNS host overrides" in report
        assert "No DHCP leases" in report

    @pytest.mark.asyncio
    async def test_report_detects_no_hostname_leases(self) -> None:
        from opnsense.agents.services import services_report

        client = _make_client_multi({
            ("unbound", "host", "searchHost"): {"rows": []},
            ("kea", "leases4", "search"): load_fixture("dhcp_leases.json"),
        })

        report = await services_report(client)

        # Fixture has one lease with empty hostname
        assert "no hostname" in report.lower()


# ---------------------------------------------------------------------------
# Firmware agent
# ---------------------------------------------------------------------------


class TestFirmwareAgent:
    @pytest.mark.asyncio
    async def test_report_upgrade_available(self) -> None:
        from opnsense.agents.firmware import firmware_report

        client = _make_client_multi({
            ("core", "firmware", "status"): {
                "product_version": "24.7.1",
                "product_latest": "24.7.2",
                "upgrade_available": True,
                "last_check": "2026-03-19T09:00:00Z",
            },
            ("core", "firmware", "info"): {"package": [
                {"name": "opnsense", "version": "24.7.1", "comment": "OPNsense core"},
            ]},
        })

        report = await firmware_report(client)

        assert "Firmware Report" in report
        assert "update available" in report.lower()
        assert "24.7.2" in report

    @pytest.mark.asyncio
    async def test_report_up_to_date(self) -> None:
        from opnsense.agents.firmware import firmware_report

        client = _make_client_multi({
            ("core", "firmware", "status"): {
                "product_version": "24.7.2",
                "upgrade_available": False,
            },
            ("core", "firmware", "info"): {"package": []},
        })

        report = await firmware_report(client)

        assert "up to date" in report.lower()


# ---------------------------------------------------------------------------
# Diagnostics agent
# ---------------------------------------------------------------------------


class TestDiagnosticsAgent:
    @pytest.mark.asyncio
    async def test_report_with_reachable_targets(self) -> None:
        from opnsense.agents.diagnostics import diagnostics_report

        client = AsyncMock()
        client.post = AsyncMock(return_value={
            "loss": "0",
            "avg": "5.2",
        })

        report = await diagnostics_report(client, targets=["8.8.8.8"])

        assert "Network Diagnostics" in report
        assert "8.8.8.8" in report

    @pytest.mark.asyncio
    async def test_report_with_unreachable_target(self) -> None:
        from opnsense.agents.diagnostics import diagnostics_report

        client = AsyncMock()
        client.post = AsyncMock(side_effect=Exception("Connection refused"))

        report = await diagnostics_report(client, targets=["10.0.0.1"])

        assert "Ping failed" in report
        assert "10.0.0.1" in report
