# SPDX-License-Identifier: MIT
"""Tests for OPNsense command-level MCP tools (Tasks 101-109).

Covers:
- Task 101: opnsense_scan -- full inventory delegation
- Task 102: opnsense_health -- gateway health, IDS, firmware, WAN
- Task 103: opnsense_diagnose -- host/interface diagnosis with ambiguity
- Task 104: opnsense_firewall -- list rules + audit mode
- Task 105: opnsense_firewall_policy_from_matrix -- matrix parsing, audit, apply
- Task 106: opnsense_vlan -- list/configure/audit VLANs
- Task 107: opnsense_dhcp_reserve_batch -- batch DHCP reservations
- Task 108: opnsense_vpn, opnsense_dns, opnsense_secure, opnsense_firmware
- Task 109: This test file (50+ tests)

Test strategy:
- Mock tool functions at the agent/tool level to isolate command logic
- Verify delegation to the correct agent/tool functions
- Test parsing/validation of JSON inputs (matrix, devices)
- Verify write gate enforcement on write commands
- Verify OX-formatted output
"""

from __future__ import annotations

import json
import os
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from opnsense.errors import ValidationError
from opnsense.output import Severity
from opnsense.tools.commands import (
    _detect_shadows,
    _parse_access_matrix,
    _parse_devices_json,
)
from tests.fixtures import load_fixture

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

INTERFACES_FIXTURE = load_fixture("interfaces.json")
VLAN_INTERFACES_FIXTURE = load_fixture("vlan_interfaces.json")
DHCP_LEASES_FIXTURE = load_fixture("dhcp_leases.json")
FIREWALL_RULES_FIXTURE = load_fixture("firewall_rules.json")
GATEWAYS_FIXTURE = load_fixture("gateways.json")
IDS_ALERTS_FIXTURE = load_fixture("ids_alerts.json")


def _make_mock_client(**kwargs: Any) -> MagicMock:
    """Create a mock OPNsenseClient."""
    from opnsense.api.opnsense_client import OPNsenseClient

    client = MagicMock(spec=OPNsenseClient)
    client.close = AsyncMock()
    client.get = AsyncMock(return_value=kwargs.get("get_response", {}))
    client.get_cached = AsyncMock(return_value=kwargs.get("get_cached_response", {}))
    client.write = AsyncMock(
        return_value=kwargs.get("write_response", {"result": "saved", "uuid": "test-uuid"})
    )
    client.reconfigure = AsyncMock(return_value={"status": "ok"})
    client.post = AsyncMock(return_value=kwargs.get("post_response", {}))
    return client


# ===========================================================================
# Task 101: opnsense_scan
# ===========================================================================


class TestOpnsenseScan:
    """opnsense_scan() -- full inventory."""

    async def test_scan_produces_report(self) -> None:
        """Scan should produce a report with all subsections."""
        mock_client = _make_mock_client()
        with (
            patch(
                "opnsense.agents.interfaces.run_interface_report",
                new_callable=AsyncMock,
                return_value="## Interface Report\ndata",
            ),
            patch(
                "opnsense.agents.firewall.run_firewall_audit",
                new_callable=AsyncMock,
                return_value="## Firewall Report\ndata",
            ),
            patch(
                "opnsense.agents.routing.run_routing_report",
                new_callable=AsyncMock,
                return_value="## Routing Report\ndata",
            ),
            patch("opnsense.tools.commands._get_client", return_value=mock_client),
            patch(
                "opnsense.agents.vpn.vpn_status_report",
                new_callable=AsyncMock,
                return_value="## VPN\ndata",
            ),
            patch(
                "opnsense.agents.security.security_audit_report",
                new_callable=AsyncMock,
                return_value="## Security\ndata",
            ),
            patch(
                "opnsense.agents.services.services_report",
                new_callable=AsyncMock,
                return_value="## Services\ndata",
            ),
            patch(
                "opnsense.agents.firmware.firmware_report",
                new_callable=AsyncMock,
                return_value="## Firmware\ndata",
            ),
        ):
            from opnsense.tools.commands import opnsense_scan

            result = await opnsense_scan()

        assert "OPNsense Full Inventory Scan" in result
        assert "Interface Report" in result
        assert "Firewall Report" in result
        assert "Routing Report" in result

    async def test_scan_handles_subsystem_failure(self) -> None:
        """Scan should continue if one subsystem fails."""
        mock_client = _make_mock_client()
        with (
            patch(
                "opnsense.agents.interfaces.run_interface_report",
                new_callable=AsyncMock,
                side_effect=Exception("API error"),
            ),
            patch(
                "opnsense.agents.firewall.run_firewall_audit",
                new_callable=AsyncMock,
                return_value="## Firewall OK",
            ),
            patch(
                "opnsense.agents.routing.run_routing_report",
                new_callable=AsyncMock,
                return_value="## Routing OK",
            ),
            patch("opnsense.tools.commands._get_client", return_value=mock_client),
            patch(
                "opnsense.agents.vpn.vpn_status_report",
                new_callable=AsyncMock,
                return_value="## VPN OK",
            ),
            patch(
                "opnsense.agents.security.security_audit_report",
                new_callable=AsyncMock,
                return_value="## Security OK",
            ),
            patch(
                "opnsense.agents.services.services_report",
                new_callable=AsyncMock,
                return_value="## Services OK",
            ),
            patch(
                "opnsense.agents.firmware.firmware_report",
                new_callable=AsyncMock,
                return_value="## Firmware OK",
            ),
        ):
            from opnsense.tools.commands import opnsense_scan

            result = await opnsense_scan()

        assert "Failed to retrieve interface data" in result
        assert "Firewall OK" in result

    async def test_scan_closes_client(self) -> None:
        """Scan should always close the client."""
        mock_client = _make_mock_client()
        with (
            patch(
                "opnsense.agents.interfaces.run_interface_report",
                new_callable=AsyncMock,
                return_value="ok",
            ),
            patch(
                "opnsense.agents.firewall.run_firewall_audit",
                new_callable=AsyncMock,
                return_value="ok",
            ),
            patch(
                "opnsense.agents.routing.run_routing_report",
                new_callable=AsyncMock,
                return_value="ok",
            ),
            patch("opnsense.tools.commands._get_client", return_value=mock_client),
            patch(
                "opnsense.agents.vpn.vpn_status_report", new_callable=AsyncMock, return_value="ok"
            ),
            patch(
                "opnsense.agents.security.security_audit_report",
                new_callable=AsyncMock,
                return_value="ok",
            ),
            patch(
                "opnsense.agents.services.services_report",
                new_callable=AsyncMock,
                return_value="ok",
            ),
            patch(
                "opnsense.agents.firmware.firmware_report",
                new_callable=AsyncMock,
                return_value="ok",
            ),
        ):
            from opnsense.tools.commands import opnsense_scan

            await opnsense_scan()

        mock_client.close.assert_awaited_once()


# ===========================================================================
# Task 102: opnsense_health
# ===========================================================================


class TestOpnsenseHealth:
    """opnsense_health() -- comprehensive health check."""

    async def test_health_produces_report(self) -> None:
        """Health check should produce a severity-tiered report."""
        mock_client = _make_mock_client(post_response={"loss": "0"})
        with (
            patch(
                "opnsense.tools.routing.opnsense__routing__list_gateways",
                new_callable=AsyncMock,
                return_value=[{"name": "WAN_GW", "status": "online", "rtt_ms": 5.0}],
            ),
            patch("opnsense.tools.commands._get_client", return_value=mock_client),
            patch(
                "opnsense.tools.security.opnsense__security__get_ids_alerts",
                new_callable=AsyncMock,
                return_value=[],
            ),
            patch(
                "opnsense.tools.firmware.opnsense__firmware__get_status",
                new_callable=AsyncMock,
                return_value={"upgrade_available": False, "current_version": "25.1"},
            ),
            patch(
                "opnsense.tools.diagnostics.opnsense__diagnostics__run_ping",
                new_callable=AsyncMock,
                return_value={"loss": "0"},
            ),
        ):
            from opnsense.tools.commands import opnsense_health

            result = await opnsense_health()

        assert "Health Check" in result
        assert "Firmware up to date" in result

    async def test_health_reports_offline_gateway(self) -> None:
        """Offline gateways should produce CRITICAL findings."""
        mock_client = _make_mock_client(post_response={"loss": "0"})
        with (
            patch(
                "opnsense.tools.routing.opnsense__routing__list_gateways",
                new_callable=AsyncMock,
                return_value=[
                    {
                        "name": "WAN_GW",
                        "status": "offline",
                        "gateway": "1.2.3.4",
                        "interface": "igb0",
                    }
                ],
            ),
            patch("opnsense.tools.commands._get_client", return_value=mock_client),
            patch(
                "opnsense.tools.security.opnsense__security__get_ids_alerts",
                new_callable=AsyncMock,
                return_value=[],
            ),
            patch(
                "opnsense.tools.firmware.opnsense__firmware__get_status",
                new_callable=AsyncMock,
                return_value={"upgrade_available": False, "current_version": "25.1"},
            ),
            patch(
                "opnsense.tools.diagnostics.opnsense__diagnostics__run_ping",
                new_callable=AsyncMock,
                return_value={"loss": "0"},
            ),
        ):
            from opnsense.tools.commands import opnsense_health

            result = await opnsense_health()

        assert "CRITICAL" in result
        assert "Gateway offline" in result

    async def test_health_reports_firmware_update(self) -> None:
        """Firmware updates should produce WARNING findings."""
        mock_client = _make_mock_client(post_response={"loss": "0"})
        with (
            patch(
                "opnsense.tools.routing.opnsense__routing__list_gateways",
                new_callable=AsyncMock,
                return_value=[],
            ),
            patch("opnsense.tools.commands._get_client", return_value=mock_client),
            patch(
                "opnsense.tools.security.opnsense__security__get_ids_alerts",
                new_callable=AsyncMock,
                return_value=[],
            ),
            patch(
                "opnsense.tools.firmware.opnsense__firmware__get_status",
                new_callable=AsyncMock,
                return_value={
                    "upgrade_available": True,
                    "latest_version": "25.2",
                    "current_version": "25.1",
                },
            ),
            patch(
                "opnsense.tools.diagnostics.opnsense__diagnostics__run_ping",
                new_callable=AsyncMock,
                return_value={"loss": "0"},
            ),
        ):
            from opnsense.tools.commands import opnsense_health

            result = await opnsense_health()

        assert "update available" in result.lower()

    async def test_health_reports_ids_alerts(self) -> None:
        """High-severity IDS alerts should produce HIGH findings."""
        mock_client = _make_mock_client(post_response={"loss": "0"})
        with (
            patch(
                "opnsense.tools.routing.opnsense__routing__list_gateways",
                new_callable=AsyncMock,
                return_value=[],
            ),
            patch("opnsense.tools.commands._get_client", return_value=mock_client),
            patch(
                "opnsense.tools.security.opnsense__security__get_ids_alerts",
                new_callable=AsyncMock,
                return_value=[{"severity": 1, "signature": "ET MALWARE"}],
            ),
            patch(
                "opnsense.tools.firmware.opnsense__firmware__get_status",
                new_callable=AsyncMock,
                return_value={"upgrade_available": False, "current_version": "25.1"},
            ),
            patch(
                "opnsense.tools.diagnostics.opnsense__diagnostics__run_ping",
                new_callable=AsyncMock,
                return_value={"loss": "0"},
            ),
        ):
            from opnsense.tools.commands import opnsense_health

            result = await opnsense_health()

        assert "IDS alert" in result

    async def test_health_reports_wan_unreachable(self) -> None:
        """WAN unreachable should produce CRITICAL findings."""
        mock_client = _make_mock_client()
        with (
            patch(
                "opnsense.tools.routing.opnsense__routing__list_gateways",
                new_callable=AsyncMock,
                return_value=[],
            ),
            patch("opnsense.tools.commands._get_client", return_value=mock_client),
            patch(
                "opnsense.tools.security.opnsense__security__get_ids_alerts",
                new_callable=AsyncMock,
                return_value=[],
            ),
            patch(
                "opnsense.tools.firmware.opnsense__firmware__get_status",
                new_callable=AsyncMock,
                return_value={"upgrade_available": False, "current_version": "25.1"},
            ),
            patch(
                "opnsense.tools.diagnostics.opnsense__diagnostics__run_ping",
                new_callable=AsyncMock,
                return_value={"loss": "100%"},
            ),
        ):
            from opnsense.tools.commands import opnsense_health

            result = await opnsense_health()

        assert "WAN unreachable" in result

    async def test_health_closes_client(self) -> None:
        """Health check should always close the client."""
        mock_client = _make_mock_client(post_response={"loss": "0"})
        with (
            patch(
                "opnsense.tools.routing.opnsense__routing__list_gateways",
                new_callable=AsyncMock,
                return_value=[],
            ),
            patch("opnsense.tools.commands._get_client", return_value=mock_client),
            patch(
                "opnsense.tools.security.opnsense__security__get_ids_alerts",
                new_callable=AsyncMock,
                return_value=[],
            ),
            patch(
                "opnsense.tools.firmware.opnsense__firmware__get_status",
                new_callable=AsyncMock,
                return_value={"upgrade_available": False, "current_version": "25.1"},
            ),
            patch(
                "opnsense.tools.diagnostics.opnsense__diagnostics__run_ping",
                new_callable=AsyncMock,
                return_value={"loss": "0"},
            ),
        ):
            from opnsense.tools.commands import opnsense_health

            await opnsense_health()

        mock_client.close.assert_awaited_once()


# ===========================================================================
# Task 103: opnsense_diagnose
# ===========================================================================


class TestOpnsenseDiagnose:
    """opnsense_diagnose(target) -- host/interface diagnosis."""

    async def test_diagnose_empty_target(self) -> None:
        """Empty target should raise ValidationError."""
        from opnsense.tools.commands import opnsense_diagnose

        with pytest.raises(ValidationError, match="Target must not be empty"):
            await opnsense_diagnose("")

    async def test_diagnose_whitespace_target(self) -> None:
        """Whitespace-only target should raise ValidationError."""
        from opnsense.tools.commands import opnsense_diagnose

        with pytest.raises(ValidationError, match="Target must not be empty"):
            await opnsense_diagnose("   ")

    async def test_diagnose_not_found(self) -> None:
        """Non-matching target should return 'not found' message."""
        with (
            patch(
                "opnsense.tools.interfaces.opnsense__interfaces__list_interfaces",
                new_callable=AsyncMock,
                return_value=[],
            ),
            patch(
                "opnsense.tools.interfaces.opnsense__interfaces__get_dhcp_leases",
                new_callable=AsyncMock,
                return_value=[],
            ),
        ):
            from opnsense.tools.commands import opnsense_diagnose

            result = await opnsense_diagnose("nonexistent-device")

        assert "Target Not Found" in result

    async def test_diagnose_interface_match(self) -> None:
        """Matching an interface name should show interface diagnostics."""
        interfaces = [
            {
                "name": "igb0",
                "description": "WAN",
                "ip": "203.0.113.5",
                "subnet": "24",
                "if_type": "physical",
                "enabled": True,
            }
        ]
        with (
            patch(
                "opnsense.tools.interfaces.opnsense__interfaces__list_interfaces",
                new_callable=AsyncMock,
                return_value=interfaces,
            ),
            patch(
                "opnsense.tools.interfaces.opnsense__interfaces__get_dhcp_leases",
                new_callable=AsyncMock,
                return_value=[],
            ),
            patch(
                "opnsense.tools.interfaces.opnsense__interfaces__list_vlan_interfaces",
                new_callable=AsyncMock,
                return_value=[],
            ),
        ):
            from opnsense.tools.commands import opnsense_diagnose

            result = await opnsense_diagnose("igb0")

        assert "Interface: igb0" in result
        assert "WAN" in result

    async def test_diagnose_host_by_ip(self) -> None:
        """Matching a host by IP should show host diagnostics."""
        leases = [
            {
                "ip": "192.168.1.100",
                "mac": "aa:bb:cc:dd:ee:ff",
                "hostname": "my-laptop",
                "state": "active",
                "interface": "igb1",
            }
        ]
        mock_client = _make_mock_client(post_response={"loss": "0", "avg": "1.2"})
        with (
            patch(
                "opnsense.tools.interfaces.opnsense__interfaces__list_interfaces",
                new_callable=AsyncMock,
                return_value=[],
            ),
            patch(
                "opnsense.tools.interfaces.opnsense__interfaces__get_dhcp_leases",
                new_callable=AsyncMock,
                return_value=leases,
            ),
            patch("opnsense.tools.commands._get_client", return_value=mock_client),
            patch(
                "opnsense.tools.diagnostics.opnsense__diagnostics__run_ping",
                new_callable=AsyncMock,
                return_value={"loss": "0", "avg": "1.2"},
            ),
            patch(
                "opnsense.tools.diagnostics.opnsense__diagnostics__dns_lookup",
                new_callable=AsyncMock,
                return_value={"answer": "192.168.1.100"},
            ),
        ):
            from opnsense.tools.commands import opnsense_diagnose

            result = await opnsense_diagnose("192.168.1.100")

        assert "Host: my-laptop" in result
        assert "aa:bb:cc:dd:ee:ff" in result

    async def test_diagnose_host_by_mac(self) -> None:
        """Matching a host by MAC should show host diagnostics."""
        leases = [
            {
                "ip": "192.168.1.100",
                "mac": "aa:bb:cc:dd:ee:ff",
                "hostname": "my-laptop",
                "state": "active",
                "interface": "igb1",
            }
        ]
        mock_client = _make_mock_client(post_response={"loss": "0"})
        with (
            patch(
                "opnsense.tools.interfaces.opnsense__interfaces__list_interfaces",
                new_callable=AsyncMock,
                return_value=[],
            ),
            patch(
                "opnsense.tools.interfaces.opnsense__interfaces__get_dhcp_leases",
                new_callable=AsyncMock,
                return_value=leases,
            ),
            patch("opnsense.tools.commands._get_client", return_value=mock_client),
            patch(
                "opnsense.tools.diagnostics.opnsense__diagnostics__run_ping",
                new_callable=AsyncMock,
                return_value={"loss": "0"},
            ),
        ):
            from opnsense.tools.commands import opnsense_diagnose

            result = await opnsense_diagnose("aa:bb:cc:dd:ee:ff")

        assert "my-laptop" in result

    async def test_diagnose_ambiguous_target(self) -> None:
        """Target matching both interface and host should prompt for clarification."""
        interfaces = [
            {
                "name": "igb1",
                "description": "LAN",
                "ip": "192.168.1.1",
                "subnet": "24",
                "if_type": "physical",
                "enabled": True,
            }
        ]
        leases = [
            {
                "ip": "192.168.1.1",
                "mac": "aa:bb:cc:dd:ee:ff",
                "hostname": "router",
                "state": "active",
                "interface": "igb1",
            }
        ]
        with (
            patch(
                "opnsense.tools.interfaces.opnsense__interfaces__list_interfaces",
                new_callable=AsyncMock,
                return_value=interfaces,
            ),
            patch(
                "opnsense.tools.interfaces.opnsense__interfaces__get_dhcp_leases",
                new_callable=AsyncMock,
                return_value=leases,
            ),
        ):
            from opnsense.tools.commands import opnsense_diagnose

            result = await opnsense_diagnose("192.168.1.1")

        assert "Ambiguous Target" in result
        assert "Matching Interfaces" in result
        assert "Matching Hosts" in result

    async def test_diagnose_closes_client_on_host(self) -> None:
        """Diagnose should close client after host diagnosis."""
        leases = [
            {
                "ip": "10.0.0.5",
                "mac": "11:22:33:44:55:66",
                "hostname": "test",
                "state": "active",
                "interface": "igb1",
            }
        ]
        mock_client = _make_mock_client(post_response={"loss": "0"})
        with (
            patch(
                "opnsense.tools.interfaces.opnsense__interfaces__list_interfaces",
                new_callable=AsyncMock,
                return_value=[],
            ),
            patch(
                "opnsense.tools.interfaces.opnsense__interfaces__get_dhcp_leases",
                new_callable=AsyncMock,
                return_value=leases,
            ),
            patch("opnsense.tools.commands._get_client", return_value=mock_client),
            patch(
                "opnsense.tools.diagnostics.opnsense__diagnostics__run_ping",
                new_callable=AsyncMock,
                return_value={"loss": "0"},
            ),
        ):
            from opnsense.tools.commands import opnsense_diagnose

            await opnsense_diagnose("10.0.0.5")

        mock_client.close.assert_awaited_once()


# ===========================================================================
# Task 104: opnsense_firewall
# ===========================================================================


class TestOpnsenseFirewall:
    """opnsense_firewall(audit) -- list rules + audit."""

    async def test_firewall_list_mode(self) -> None:
        """Without audit, should list rules in a table."""
        rules = [
            {
                "position": 1,
                "action": "pass",
                "interface": "lan",
                "source": "any",
                "destination": "any",
                "protocol": "any",
                "log": False,
                "enabled": True,
            },
        ]
        with patch(
            "opnsense.tools.firewall.opnsense__firewall__list_rules",
            new_callable=AsyncMock,
            return_value=rules,
        ):
            from opnsense.tools.commands import opnsense_firewall

            result = await opnsense_firewall(audit=False)

        assert "Firewall Rules" in result
        assert "pass" in result
        assert "audit" in result.lower()

    async def test_firewall_empty_rules(self) -> None:
        """No rules should show a message."""
        with patch(
            "opnsense.tools.firewall.opnsense__firewall__list_rules",
            new_callable=AsyncMock,
            return_value=[],
        ):
            from opnsense.tools.commands import opnsense_firewall

            result = await opnsense_firewall(audit=False)

        assert "No firewall rules found" in result

    async def test_firewall_audit_mode(self) -> None:
        """With audit=True, should delegate to firewall audit agent."""
        with patch(
            "opnsense.agents.firewall.run_firewall_audit",
            new_callable=AsyncMock,
            return_value="## Firewall Audit\nFindings here",
        ):
            from opnsense.tools.commands import opnsense_firewall

            result = await opnsense_firewall(audit=True)

        assert "Firewall Audit" in result

    async def test_firewall_list_shows_summary(self) -> None:
        """List mode should include summary stats."""
        rules = [
            {
                "position": 1,
                "action": "pass",
                "interface": "lan",
                "source": "any",
                "destination": "any",
                "protocol": "any",
                "log": False,
                "enabled": True,
            },
            {
                "position": 2,
                "action": "block",
                "interface": "wan",
                "source": "any",
                "destination": "any",
                "protocol": "any",
                "log": True,
                "enabled": False,
            },
        ]
        with patch(
            "opnsense.tools.firewall.opnsense__firewall__list_rules",
            new_callable=AsyncMock,
            return_value=rules,
        ):
            from opnsense.tools.commands import opnsense_firewall

            result = await opnsense_firewall()

        assert "Total rules" in result


# ===========================================================================
# Task 105: opnsense_firewall_policy_from_matrix
# ===========================================================================


class TestParseAccessMatrix:
    """_parse_access_matrix() -- JSON parsing and validation."""

    def test_valid_matrix(self) -> None:
        matrix = json.dumps(
            [
                {"src": "LAN", "dst": "WAN", "action": "pass"},
                {"src": "IoT", "dst": "LAN", "action": "block"},
            ]
        )
        result = _parse_access_matrix(matrix)
        assert len(result) == 2
        assert result[0]["src"] == "LAN"
        assert result[0]["action"] == "pass"

    def test_invalid_json(self) -> None:
        with pytest.raises(ValidationError, match="Invalid JSON"):
            _parse_access_matrix("not-json{")

    def test_not_array(self) -> None:
        with pytest.raises(ValidationError, match="must be a JSON array"):
            _parse_access_matrix('{"src": "LAN"}')

    def test_empty_array(self) -> None:
        with pytest.raises(ValidationError, match="must not be empty"):
            _parse_access_matrix("[]")

    def test_entry_not_object(self) -> None:
        with pytest.raises(ValidationError, match="must be an object"):
            _parse_access_matrix('["string"]')

    def test_missing_src(self) -> None:
        with pytest.raises(ValidationError, match="missing 'src'"):
            _parse_access_matrix('[{"dst": "WAN", "action": "pass"}]')

    def test_missing_dst(self) -> None:
        with pytest.raises(ValidationError, match="missing 'dst'"):
            _parse_access_matrix('[{"src": "LAN", "action": "pass"}]')

    def test_invalid_action(self) -> None:
        with pytest.raises(ValidationError, match="invalid action"):
            _parse_access_matrix('[{"src": "LAN", "dst": "WAN", "action": "allow"}]')

    def test_valid_actions(self) -> None:
        for action in ("pass", "block", "reject"):
            matrix = json.dumps([{"src": "LAN", "dst": "WAN", "action": action}])
            result = _parse_access_matrix(matrix)
            assert result[0]["action"] == action

    def test_default_protocol(self) -> None:
        matrix = json.dumps([{"src": "LAN", "dst": "WAN", "action": "pass"}])
        result = _parse_access_matrix(matrix)
        assert result[0]["protocol"] == "any"

    def test_custom_protocol(self) -> None:
        matrix = json.dumps([{"src": "LAN", "dst": "WAN", "action": "pass", "protocol": "TCP"}])
        result = _parse_access_matrix(matrix)
        assert result[0]["protocol"] == "TCP"

    def test_custom_description(self) -> None:
        matrix = json.dumps(
            [
                {"src": "LAN", "dst": "WAN", "action": "pass", "description": "Allow LAN out"},
            ]
        )
        result = _parse_access_matrix(matrix)
        assert result[0]["description"] == "Allow LAN out"

    def test_whitespace_handling(self) -> None:
        matrix = json.dumps([{"src": " LAN ", "dst": " WAN ", "action": " pass "}])
        result = _parse_access_matrix(matrix)
        assert result[0]["src"] == "LAN"
        assert result[0]["dst"] == "WAN"
        assert result[0]["action"] == "pass"


class TestDetectShadows:
    """_detect_shadows() -- shadow conflict detection."""

    def test_no_shadows(self) -> None:
        matrix = [{"src": "LAN", "dst": "WAN", "action": "pass"}]
        existing = [{"source": "LAN", "destination": "DMZ", "action": "pass", "enabled": True}]
        findings = _detect_shadows(matrix, existing)
        assert len(findings) == 0

    def test_direct_shadow(self) -> None:
        matrix = [{"src": "LAN", "dst": "WAN", "action": "pass"}]
        existing = [
            {
                "source": "LAN",
                "destination": "WAN",
                "action": "block",
                "enabled": True,
                "description": "Block LAN",
            },
        ]
        findings = _detect_shadows(matrix, existing)
        assert len(findings) == 1
        assert findings[0].severity == Severity.WARNING
        assert "Shadow conflict" in findings[0].title

    def test_any_source_shadow(self) -> None:
        matrix = [{"src": "LAN", "dst": "WAN", "action": "pass"}]
        existing = [
            {
                "source": "any",
                "destination": "WAN",
                "action": "block",
                "enabled": True,
                "description": "Block all to WAN",
            },
        ]
        findings = _detect_shadows(matrix, existing)
        assert len(findings) >= 1

    def test_disabled_rules_ignored(self) -> None:
        matrix = [{"src": "LAN", "dst": "WAN", "action": "pass"}]
        existing = [
            {
                "source": "LAN",
                "destination": "WAN",
                "action": "block",
                "enabled": False,
                "description": "Disabled block",
            },
        ]
        findings = _detect_shadows(matrix, existing)
        assert len(findings) == 0

    def test_same_action_no_shadow(self) -> None:
        matrix = [{"src": "LAN", "dst": "WAN", "action": "pass"}]
        existing = [
            {
                "source": "LAN",
                "destination": "WAN",
                "action": "pass",
                "enabled": True,
                "description": "Pass LAN",
            },
        ]
        findings = _detect_shadows(matrix, existing)
        assert len(findings) == 0


class TestPolicyFromMatrix:
    """opnsense_firewall_policy_from_matrix() -- plan/audit/apply modes."""

    async def test_plan_only_mode(self) -> None:
        """Without audit or apply, should show plan."""
        from opnsense.tools.commands import opnsense_firewall_policy_from_matrix

        matrix = json.dumps([{"src": "LAN", "dst": "WAN", "action": "pass"}])
        result = await opnsense_firewall_policy_from_matrix(matrix)

        assert "Access Matrix" in result
        assert "Plan-only mode" in result

    async def test_audit_mode(self) -> None:
        """Audit mode should compare against existing rules."""
        existing_rules = [
            {
                "source": "LAN",
                "destination": "WAN",
                "action": "block",
                "enabled": True,
                "uuid": "test",
                "description": "Test",
            },
        ]
        with patch(
            "opnsense.tools.firewall.opnsense__firewall__list_rules",
            new_callable=AsyncMock,
            return_value=existing_rules,
        ):
            from opnsense.tools.commands import opnsense_firewall_policy_from_matrix

            matrix = json.dumps([{"src": "LAN", "dst": "WAN", "action": "pass"}])
            result = await opnsense_firewall_policy_from_matrix(matrix, audit=True)

        assert "Shadow Analysis" in result
        assert "Shadow conflict" in result

    async def test_audit_no_shadows(self) -> None:
        """Audit with no conflicts should report clean."""
        with patch(
            "opnsense.tools.firewall.opnsense__firewall__list_rules",
            new_callable=AsyncMock,
            return_value=[],
        ):
            from opnsense.tools.commands import opnsense_firewall_policy_from_matrix

            matrix = json.dumps([{"src": "LAN", "dst": "WAN", "action": "pass"}])
            result = await opnsense_firewall_policy_from_matrix(matrix, audit=True)

        assert "No shadow conflicts" in result

    async def test_apply_without_write_enabled(self) -> None:
        """Apply without OPNSENSE_WRITE_ENABLED should report disabled."""
        with patch.dict(os.environ, {}, clear=True):
            from opnsense.tools.commands import opnsense_firewall_policy_from_matrix

            matrix = json.dumps([{"src": "LAN", "dst": "WAN", "action": "pass"}])
            result = await opnsense_firewall_policy_from_matrix(matrix, apply=True)

        assert "disabled" in result.lower()

    async def test_apply_creates_rules(self) -> None:
        """Apply with write enabled should create rules."""
        with (
            patch.dict(os.environ, {"OPNSENSE_WRITE_ENABLED": "true"}),
            patch(
                "opnsense.tools.firewall.opnsense__firewall__create_rule",
                new_callable=AsyncMock,
                return_value={"status": "created", "uuid": "new-uuid"},
            ),
            patch(
                "opnsense.tools.firewall.opnsense__firewall__list_aliases",
                new_callable=AsyncMock,
                return_value=[
                    {"name": "LAN", "type": "network", "content": "192.168.1.0/24"},
                    {"name": "WAN", "type": "network", "content": "0.0.0.0/0"},
                ],
            ),
        ):
            from opnsense.tools.commands import opnsense_firewall_policy_from_matrix

            matrix = json.dumps([{"src": "LAN", "dst": "WAN", "action": "pass"}])
            result = await opnsense_firewall_policy_from_matrix(matrix, apply=True)

        assert "Created" in result or "created" in result.lower()

    async def test_invalid_matrix_json(self) -> None:
        """Invalid JSON should raise ValidationError."""
        from opnsense.tools.commands import opnsense_firewall_policy_from_matrix

        with pytest.raises(ValidationError):
            await opnsense_firewall_policy_from_matrix("not-json")


# ===========================================================================
# Task 106: opnsense_vlan
# ===========================================================================


class TestOpnsenseVlan:
    """opnsense_vlan(configure, audit) -- VLAN commands."""

    async def test_vlan_list(self) -> None:
        """Default mode should list VLANs."""
        vlans = [{"tag": 10, "device": "vlan0.10", "parent_if": "igb1", "description": "LAN"}]
        with (
            patch(
                "opnsense.tools.interfaces.opnsense__interfaces__list_vlan_interfaces",
                new_callable=AsyncMock,
                return_value=vlans,
            ),
            patch(
                "opnsense.tools.interfaces.opnsense__interfaces__list_interfaces",
                new_callable=AsyncMock,
                return_value=[],
            ),
        ):
            from opnsense.tools.commands import opnsense_vlan

            result = await opnsense_vlan()

        assert "VLAN Interfaces" in result
        assert "10" in result

    async def test_vlan_empty(self) -> None:
        """No VLANs should report empty."""
        with (
            patch(
                "opnsense.tools.interfaces.opnsense__interfaces__list_vlan_interfaces",
                new_callable=AsyncMock,
                return_value=[],
            ),
            patch(
                "opnsense.tools.interfaces.opnsense__interfaces__list_interfaces",
                new_callable=AsyncMock,
                return_value=[],
            ),
        ):
            from opnsense.tools.commands import opnsense_vlan

            result = await opnsense_vlan()

        assert "No VLAN interfaces configured" in result

    async def test_vlan_audit(self) -> None:
        """Audit mode should check for VLANs without IPs."""
        vlans = [{"tag": 10, "device": "vlan0.10", "parent_if": "igb1", "description": "LAN"}]
        interfaces = [{"name": "igb0", "ip": "1.2.3.4"}]  # No VLAN interface has IP
        with (
            patch(
                "opnsense.tools.interfaces.opnsense__interfaces__list_vlan_interfaces",
                new_callable=AsyncMock,
                return_value=vlans,
            ),
            patch(
                "opnsense.tools.interfaces.opnsense__interfaces__list_interfaces",
                new_callable=AsyncMock,
                return_value=interfaces,
            ),
            patch(
                "opnsense.tools.firewall.opnsense__firewall__list_rules",
                new_callable=AsyncMock,
                return_value=[],
            ),
        ):
            from opnsense.tools.commands import opnsense_vlan

            result = await opnsense_vlan(audit=True)

        assert "VLAN Audit" in result
        assert "no IP address" in result

    async def test_vlan_configure_guidance(self) -> None:
        """Configure mode should show guidance."""
        vlans = [{"tag": 10, "device": "vlan0.10", "parent_if": "igb1", "description": "LAN"}]
        with (
            patch(
                "opnsense.tools.interfaces.opnsense__interfaces__list_vlan_interfaces",
                new_callable=AsyncMock,
                return_value=vlans,
            ),
            patch(
                "opnsense.tools.interfaces.opnsense__interfaces__list_interfaces",
                new_callable=AsyncMock,
                return_value=[],
            ),
        ):
            from opnsense.tools.commands import opnsense_vlan

            result = await opnsense_vlan(configure=True)

        assert "VLAN Configuration" in result
        assert "configure_vlan" in result


# ===========================================================================
# Task 107: opnsense_dhcp_reserve_batch
# ===========================================================================


class TestParseDevicesJson:
    """_parse_devices_json() -- JSON parsing and validation."""

    def test_valid_devices(self) -> None:
        devices = json.dumps(
            [
                {"hostname": "printer", "mac": "aa:bb:cc:dd:ee:ff", "ip": "192.168.1.50"},
                {"hostname": "camera", "mac": "11:22:33:44:55:66", "ip": "192.168.1.51"},
            ]
        )
        result = _parse_devices_json(devices)
        assert len(result) == 2
        assert result[0]["hostname"] == "printer"
        assert result[0]["mac"] == "aa:bb:cc:dd:ee:ff"

    def test_invalid_json(self) -> None:
        with pytest.raises(ValidationError, match="Invalid JSON"):
            _parse_devices_json("not-json{")

    def test_not_array(self) -> None:
        with pytest.raises(ValidationError, match="must be a JSON array"):
            _parse_devices_json('{"mac": "aa:bb:cc:dd:ee:ff"}')

    def test_empty_array(self) -> None:
        with pytest.raises(ValidationError, match="must not be empty"):
            _parse_devices_json("[]")

    def test_entry_not_object(self) -> None:
        with pytest.raises(ValidationError, match="must be an object"):
            _parse_devices_json('["string"]')

    def test_missing_mac(self) -> None:
        with pytest.raises(ValidationError, match="missing 'mac'"):
            _parse_devices_json('[{"hostname": "test", "ip": "1.2.3.4"}]')

    def test_missing_ip(self) -> None:
        with pytest.raises(ValidationError, match="missing 'ip'"):
            _parse_devices_json('[{"hostname": "test", "mac": "aa:bb:cc:dd:ee:ff"}]')

    def test_invalid_mac_format(self) -> None:
        with pytest.raises(ValidationError, match="invalid MAC format"):
            _parse_devices_json('[{"hostname": "test", "mac": "invalid", "ip": "1.2.3.4"}]')

    def test_mac_lowercase(self) -> None:
        devices = json.dumps([{"hostname": "test", "mac": "AA:BB:CC:DD:EE:FF", "ip": "1.2.3.4"}])
        result = _parse_devices_json(devices)
        assert result[0]["mac"] == "aa:bb:cc:dd:ee:ff"

    def test_default_hostname(self) -> None:
        devices = json.dumps([{"mac": "aa:bb:cc:dd:ee:ff", "ip": "1.2.3.4"}])
        result = _parse_devices_json(devices)
        assert result[0]["hostname"] == "device-0"


class TestDhcpReserveBatch:
    """opnsense_dhcp_reserve_batch() -- batch DHCP reservations."""

    async def test_empty_interface(self) -> None:
        """Empty interface should raise ValidationError."""
        from opnsense.tools.commands import opnsense_dhcp_reserve_batch

        with pytest.raises(ValidationError, match="Interface must not be empty"):
            await opnsense_dhcp_reserve_batch(
                interface="",
                devices='[{"hostname": "x", "mac": "aa:bb:cc:dd:ee:ff", "ip": "1.2.3.4"}]',
            )

    async def test_plan_only_mode(self) -> None:
        """Without apply, should show plan."""
        with patch(
            "opnsense.tools.interfaces.opnsense__interfaces__get_dhcp_leases",
            new_callable=AsyncMock,
            return_value=[],
        ):
            from opnsense.tools.commands import opnsense_dhcp_reserve_batch

            result = await opnsense_dhcp_reserve_batch(
                interface="igb1",
                devices=(
                    '[{"hostname": "printer", "mac": "aa:bb:cc:dd:ee:ff", "ip": "192.168.1.50"}]'
                ),
            )

        assert "Planned DHCP Reservations" in result
        assert "Plan-only mode" in result

    async def test_mac_verified_against_leases(self) -> None:
        """MACs found in dnsmasq leases should be marked as verified."""
        mock_client = _make_mock_client(
            get_response={"rows": [{"hwaddr": "aa:bb:cc:dd:ee:ff", "ip": "192.168.1.50"}]},
        )
        with patch("opnsense.tools.commands._get_client", return_value=mock_client):
            from opnsense.tools.commands import opnsense_dhcp_reserve_batch

            result = await opnsense_dhcp_reserve_batch(
                interface="igb1",
                devices=(
                    '[{"hostname": "printer", "mac": "aa:bb:cc:dd:ee:ff", "ip": "192.168.1.50"}]'
                ),
            )

        assert "1 device(s) verified" in result

    async def test_mac_not_verified(self) -> None:
        """MACs not in leases should be flagged."""
        mock_client = _make_mock_client(get_response={"rows": []})
        with patch("opnsense.tools.commands._get_client", return_value=mock_client):
            from opnsense.tools.commands import opnsense_dhcp_reserve_batch

            result = await opnsense_dhcp_reserve_batch(
                interface="igb1",
                devices=(
                    '[{"hostname": "printer", "mac": "aa:bb:cc:dd:ee:ff", "ip": "192.168.1.50"}]'
                ),
            )

        assert "not found" in result

    async def test_apply_without_write_enabled(self) -> None:
        """Apply without OPNSENSE_WRITE_ENABLED should report disabled."""
        mock_client = _make_mock_client(get_response={"rows": []})
        with (
            patch.dict(os.environ, {}, clear=True),
            patch("opnsense.tools.commands._get_client", return_value=mock_client),
        ):
            from opnsense.tools.commands import opnsense_dhcp_reserve_batch

            result = await opnsense_dhcp_reserve_batch(
                interface="igb1",
                devices='[{"hostname": "test", "mac": "aa:bb:cc:dd:ee:ff", "ip": "1.2.3.4"}]',
                apply=True,
            )

        assert "disabled" in result.lower()

    async def test_apply_creates_reservations(self) -> None:
        """Apply with write enabled should create reservations."""
        # First _get_client() call is for lease verification,
        # second is for apply mode.
        mock_verify_client = _make_mock_client(get_response={"rows": []})
        mock_apply_client = _make_mock_client()
        with (
            patch.dict(os.environ, {"OPNSENSE_WRITE_ENABLED": "true"}),
            patch(
                "opnsense.tools.commands._get_client",
                side_effect=[mock_verify_client, mock_apply_client],
            ),
        ):
            from opnsense.tools.commands import opnsense_dhcp_reserve_batch

            result = await opnsense_dhcp_reserve_batch(
                interface="igb1",
                devices=(
                    '[{"hostname": "printer", "mac": "aa:bb:cc:dd:ee:ff", "ip": "192.168.1.50"}]'
                ),
                apply=True,
            )

        assert "Created" in result

    async def test_apply_batch_with_errors(self) -> None:
        """Partial failures should be reported."""
        # First _get_client() call is for lease verification (plan mode),
        # second is for apply mode.
        mock_verify_client = _make_mock_client(get_response={"rows": []})
        mock_apply_client = _make_mock_client()
        mock_apply_client.write = AsyncMock(
            side_effect=[
                {"result": "saved", "uuid": "uuid-1"},
                Exception("API Error"),
            ],
        )
        with (
            patch.dict(os.environ, {"OPNSENSE_WRITE_ENABLED": "true"}),
            patch(
                "opnsense.tools.commands._get_client",
                side_effect=[mock_verify_client, mock_apply_client],
            ),
        ):
            from opnsense.tools.commands import opnsense_dhcp_reserve_batch

            devices = json.dumps(
                [
                    {"hostname": "ok-device", "mac": "aa:bb:cc:dd:ee:ff", "ip": "1.2.3.4"},
                    {"hostname": "fail-device", "mac": "11:22:33:44:55:66", "ip": "1.2.3.5"},
                ]
            )
            result = await opnsense_dhcp_reserve_batch(
                interface="igb1",
                devices=devices,
                apply=True,
            )

        assert "Created" in result
        assert "Failed" in result
        assert "Errors" in result

    async def test_invalid_devices_json(self) -> None:
        """Invalid JSON should raise ValidationError."""
        from opnsense.tools.commands import opnsense_dhcp_reserve_batch

        with pytest.raises(ValidationError):
            await opnsense_dhcp_reserve_batch(
                interface="igb1",
                devices="not-json{",
            )


# ===========================================================================
# Task 108: opnsense_vpn, opnsense_dns, opnsense_secure, opnsense_firmware
# ===========================================================================


class TestOpnsenseVpn:
    """opnsense_vpn() -- VPN status report."""

    async def test_vpn_delegates_to_agent(self) -> None:
        """Should delegate to vpn_status_report agent."""
        mock_client = _make_mock_client()
        with (
            patch("opnsense.tools.commands._get_client", return_value=mock_client),
            patch(
                "opnsense.agents.vpn.vpn_status_report",
                new_callable=AsyncMock,
                return_value="## VPN Report\ndata",
            ),
        ):
            from opnsense.tools.commands import opnsense_vpn

            result = await opnsense_vpn()

        assert "VPN Report" in result
        mock_client.close.assert_awaited_once()

    async def test_vpn_closes_client_on_error(self) -> None:
        """Should close client even on error."""
        mock_client = _make_mock_client()
        with (
            patch("opnsense.tools.commands._get_client", return_value=mock_client),
            patch(
                "opnsense.agents.vpn.vpn_status_report",
                new_callable=AsyncMock,
                side_effect=Exception("API error"),
            ),
        ):
            from opnsense.tools.commands import opnsense_vpn

            with pytest.raises(Exception, match="API error"):
                await opnsense_vpn()

        mock_client.close.assert_awaited_once()


class TestOpnsenseDns:
    """opnsense_dns() -- DNS/services report."""

    async def test_dns_delegates_to_agent(self) -> None:
        """Should delegate to services_report agent."""
        mock_client = _make_mock_client()
        with (
            patch("opnsense.tools.commands._get_client", return_value=mock_client),
            patch(
                "opnsense.agents.services.services_report",
                new_callable=AsyncMock,
                return_value="## Services\nDNS data",
            ),
        ):
            from opnsense.tools.commands import opnsense_dns

            result = await opnsense_dns()

        assert "Services" in result
        mock_client.close.assert_awaited_once()


class TestOpnsenseSecure:
    """opnsense_secure() -- security posture audit."""

    async def test_secure_delegates_to_agent(self) -> None:
        """Should delegate to security_audit_report agent."""
        mock_client = _make_mock_client()
        with (
            patch("opnsense.tools.commands._get_client", return_value=mock_client),
            patch(
                "opnsense.agents.security.security_audit_report",
                new_callable=AsyncMock,
                return_value="## Security Audit\nfindings",
            ),
        ):
            from opnsense.tools.commands import opnsense_secure

            result = await opnsense_secure()

        assert "Security Audit" in result
        mock_client.close.assert_awaited_once()


class TestOpnsenseFirmware:
    """opnsense_firmware() -- firmware status report."""

    async def test_firmware_delegates_to_agent(self) -> None:
        """Should delegate to firmware_report agent."""
        mock_client = _make_mock_client()
        with (
            patch("opnsense.tools.commands._get_client", return_value=mock_client),
            patch(
                "opnsense.agents.firmware.firmware_report",
                new_callable=AsyncMock,
                return_value="## Firmware\nstatus",
            ),
        ):
            from opnsense.tools.commands import opnsense_firmware

            result = await opnsense_firmware()

        assert "Firmware" in result
        mock_client.close.assert_awaited_once()

    async def test_firmware_closes_client_on_error(self) -> None:
        """Should close client even on error."""
        mock_client = _make_mock_client()
        with (
            patch("opnsense.tools.commands._get_client", return_value=mock_client),
            patch(
                "opnsense.agents.firmware.firmware_report",
                new_callable=AsyncMock,
                side_effect=Exception("Connection error"),
            ),
        ):
            from opnsense.tools.commands import opnsense_firmware

            with pytest.raises(Exception, match="Connection error"):
                await opnsense_firmware()

        mock_client.close.assert_awaited_once()


# ===========================================================================
# Write gate enforcement tests
# ===========================================================================


class TestWriteGateEnforcement:
    """Verify write gate enforcement across all write-gated commands."""

    async def test_dhcp_batch_write_gate_env_var(self) -> None:
        """DHCP batch without OPNSENSE_WRITE_ENABLED returns disabled message."""
        with (
            patch.dict(os.environ, {}, clear=True),
            patch(
                "opnsense.tools.interfaces.opnsense__interfaces__get_dhcp_leases",
                new_callable=AsyncMock,
                return_value=[],
            ),
        ):
            from opnsense.tools.commands import opnsense_dhcp_reserve_batch

            result = await opnsense_dhcp_reserve_batch(
                interface="igb1",
                devices='[{"hostname": "x", "mac": "aa:bb:cc:dd:ee:ff", "ip": "1.2.3.4"}]',
                apply=True,
            )
            # Should not throw but report disabled
            assert "disabled" in result.lower()

    async def test_policy_matrix_write_gate_env_var(self) -> None:
        """Policy from matrix without OPNSENSE_WRITE_ENABLED returns disabled message."""
        with patch.dict(os.environ, {}, clear=True):
            from opnsense.tools.commands import opnsense_firewall_policy_from_matrix

            result = await opnsense_firewall_policy_from_matrix(
                matrix='[{"src": "LAN", "dst": "WAN", "action": "pass"}]',
                apply=True,
            )
            assert "disabled" in result.lower()


# ===========================================================================
# Custom parameter passthrough tests
# ===========================================================================


class TestParameterPassthrough:
    """Verify custom parameters are passed through correctly."""

    async def test_diagnose_passes_target(self) -> None:
        """Target parameter should be used for searching."""
        with (
            patch(
                "opnsense.tools.interfaces.opnsense__interfaces__list_interfaces",
                new_callable=AsyncMock,
                return_value=[],
            ),
            patch(
                "opnsense.tools.interfaces.opnsense__interfaces__get_dhcp_leases",
                new_callable=AsyncMock,
                return_value=[],
            ),
        ):
            from opnsense.tools.commands import opnsense_diagnose

            result = await opnsense_diagnose("specific-target-123")
            assert "specific-target-123" in result

    async def test_firewall_audit_flag(self) -> None:
        """audit=True should trigger audit agent."""
        with patch(
            "opnsense.agents.firewall.run_firewall_audit",
            new_callable=AsyncMock,
            return_value="audit-output",
        ):
            from opnsense.tools.commands import opnsense_firewall

            result = await opnsense_firewall(audit=True)
            assert "audit-output" in result

    async def test_firewall_no_audit_flag(self) -> None:
        """audit=False should trigger simple listing."""
        with patch(
            "opnsense.tools.firewall.opnsense__firewall__list_rules",
            new_callable=AsyncMock,
            return_value=[],
        ):
            from opnsense.tools.commands import opnsense_firewall

            result = await opnsense_firewall(audit=False)
            assert "No firewall rules" in result

    async def test_vlan_audit_flag(self) -> None:
        """audit=True on vlan should include findings report."""
        vlans = [{"tag": 10, "device": "vlan0.10", "parent_if": "igb1", "description": "LAN"}]
        with (
            patch(
                "opnsense.tools.interfaces.opnsense__interfaces__list_vlan_interfaces",
                new_callable=AsyncMock,
                return_value=vlans,
            ),
            patch(
                "opnsense.tools.interfaces.opnsense__interfaces__list_interfaces",
                new_callable=AsyncMock,
                return_value=[],
            ),
            patch(
                "opnsense.tools.firewall.opnsense__firewall__list_rules",
                new_callable=AsyncMock,
                return_value=[],
            ),
        ):
            from opnsense.tools.commands import opnsense_vlan

            result = await opnsense_vlan(audit=True)
            assert "VLAN Audit" in result

    async def test_dhcp_batch_interface_passed(self) -> None:
        """Interface parameter should appear in the output plan."""
        mock_client = _make_mock_client(get_response={"rows": []})
        with patch("opnsense.tools.commands._get_client", return_value=mock_client):
            from opnsense.tools.commands import opnsense_dhcp_reserve_batch

            result = await opnsense_dhcp_reserve_batch(
                interface="igb1_vlan20",
                devices='[{"hostname": "x", "mac": "aa:bb:cc:dd:ee:ff", "ip": "1.2.3.4"}]',
            )

        # The interface should appear in the planned reservations table
        assert "igb1_vlan20" in result
        # The dnsmasq leases endpoint should have been queried
        mock_client.get.assert_awaited_once_with("dnsmasq", "leases", "search")
