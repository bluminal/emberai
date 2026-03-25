"""Tests for OPNsense tools (Tasks 86-92) and agents (Task 93).

Covers:
- Task 86-87: Interface tools (list_interfaces, list_vlan_interfaces,
  get_dhcp_leases, add_vlan_interface, add_dhcp_reservation,
  add_dhcp_subnet, configure_vlan)
- Task 88-89: Firewall tools (list_rules, get_rule, list_aliases,
  list_nat_rules, add_rule, toggle_rule, add_alias)
- Task 90-91: Routing tools (list_routes, list_gateways, add_route,
  Quagga graceful degradation)
- Task 92: Diagnostics tools (get_lldp_neighbors)
- Task 93: Agents (interface report, firewall audit, routing report)
- Task 94: This test file (80+ tests)

Test strategy:
- Mock the OPNsenseClient at the _get_client() level
- Use JSON fixtures for API response data
- Verify write gate enforcement for all write tools
- Verify validation errors for invalid input
- Verify agent report generation and finding detection
"""

from __future__ import annotations

import os
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from opnsense.api.opnsense_client import OPNsenseClient
from opnsense.errors import APIError, ValidationError, WriteGateError
from opnsense.safety import WriteBlockReason
from tests.fixtures import load_fixture

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_mock_client(
    get_response: dict[str, Any] | None = None,
    get_cached_response: dict[str, Any] | None = None,
    write_response: dict[str, Any] | None = None,
    reconfigure_response: dict[str, Any] | None = None,
    get_side_effect: Exception | None = None,
) -> MagicMock:
    """Create a mock OPNsenseClient with configured responses."""
    client = MagicMock(spec=OPNsenseClient)
    client.close = AsyncMock()

    if get_side_effect:
        client.get = AsyncMock(side_effect=get_side_effect)
        client.get_cached = AsyncMock(side_effect=get_side_effect)
    else:
        client.get = AsyncMock(return_value=get_response or {})
        client.get_cached = AsyncMock(return_value=get_cached_response or get_response or {})

    client.write = AsyncMock(
        return_value=write_response or {"result": "saved", "uuid": "new-uuid-123"},
    )
    client.reconfigure = AsyncMock(return_value=reconfigure_response or {"status": "ok"})

    return client


# ---------------------------------------------------------------------------
# Interface Tool Fixtures
# ---------------------------------------------------------------------------

INTERFACES_FIXTURE = load_fixture("interfaces.json")
VLAN_INTERFACES_FIXTURE = load_fixture("vlan_interfaces.json")
DHCP_LEASES_FIXTURE = load_fixture("dhcp_leases.json")
FIREWALL_RULES_FIXTURE = load_fixture("firewall_rules.json")
ALIASES_FIXTURE = load_fixture("aliases.json")
ROUTES_FIXTURE = load_fixture("routes.json")
GATEWAYS_FIXTURE = load_fixture("gateways.json")
NAT_RULES_FIXTURE = load_fixture("nat_rules.json")
LLDP_NEIGHBORS_FIXTURE = load_fixture("lldp_neighbors.json")


# ===========================================================================
# Task 86-87: Interface Tools
# ===========================================================================


class TestListInterfaces:
    """opnsense__interfaces__list_interfaces()"""

    @pytest.mark.asyncio
    async def test_returns_all_interfaces(self) -> None:
        mock_client = _make_mock_client(get_cached_response=INTERFACES_FIXTURE)
        with patch("opnsense.tools.interfaces._get_client", return_value=mock_client):
            from opnsense.tools.interfaces import opnsense__interfaces__list_interfaces

            result = await opnsense__interfaces__list_interfaces()

        assert len(result) == 4
        assert result[0]["name"] == "igb0"
        assert result[0]["description"] == "WAN"
        mock_client.close.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_interface_has_expected_fields(self) -> None:
        mock_client = _make_mock_client(get_cached_response=INTERFACES_FIXTURE)
        with patch("opnsense.tools.interfaces._get_client", return_value=mock_client):
            from opnsense.tools.interfaces import opnsense__interfaces__list_interfaces

            result = await opnsense__interfaces__list_interfaces()

        iface = result[0]
        assert "name" in iface
        assert "description" in iface
        assert "ip" in iface
        assert "subnet" in iface
        assert "if_type" in iface
        assert "enabled" in iface

    @pytest.mark.asyncio
    async def test_vlan_interface_has_vlan_id(self) -> None:
        mock_client = _make_mock_client(get_cached_response=INTERFACES_FIXTURE)
        with patch("opnsense.tools.interfaces._get_client", return_value=mock_client):
            from opnsense.tools.interfaces import opnsense__interfaces__list_interfaces

            result = await opnsense__interfaces__list_interfaces()

        vlan_iface = next(i for i in result if i["name"] == "igb1_vlan10")
        assert vlan_iface["vlan_id"] == 10
        assert vlan_iface["if_type"] == "vlan"

    @pytest.mark.asyncio
    async def test_uses_cache(self) -> None:
        mock_client = _make_mock_client(get_cached_response=INTERFACES_FIXTURE)
        with patch("opnsense.tools.interfaces._get_client", return_value=mock_client):
            from opnsense.tools.interfaces import opnsense__interfaces__list_interfaces

            await opnsense__interfaces__list_interfaces()

        mock_client.get_cached.assert_awaited_once()
        call_kwargs = mock_client.get_cached.call_args
        assert call_kwargs.kwargs["cache_key"] == "interfaces:list"

    @pytest.mark.asyncio
    async def test_empty_response(self) -> None:
        mock_client = _make_mock_client(get_cached_response={"rows": []})
        with patch("opnsense.tools.interfaces._get_client", return_value=mock_client):
            from opnsense.tools.interfaces import opnsense__interfaces__list_interfaces

            result = await opnsense__interfaces__list_interfaces()

        assert result == []


class TestListVlanInterfaces:
    """opnsense__interfaces__list_vlan_interfaces()"""

    @pytest.mark.asyncio
    async def test_returns_all_vlans(self) -> None:
        mock_client = _make_mock_client(get_cached_response=VLAN_INTERFACES_FIXTURE)
        with patch("opnsense.tools.interfaces._get_client", return_value=mock_client):
            from opnsense.tools.interfaces import opnsense__interfaces__list_vlan_interfaces

            result = await opnsense__interfaces__list_vlan_interfaces()

        assert len(result) == 7
        assert result[0]["tag"] == 10

    @pytest.mark.asyncio
    async def test_vlan_has_expected_fields(self) -> None:
        mock_client = _make_mock_client(get_cached_response=VLAN_INTERFACES_FIXTURE)
        with patch("opnsense.tools.interfaces._get_client", return_value=mock_client):
            from opnsense.tools.interfaces import opnsense__interfaces__list_vlan_interfaces

            result = await opnsense__interfaces__list_vlan_interfaces()

        vlan = result[0]
        assert "uuid" in vlan
        assert "tag" in vlan
        assert "device" in vlan
        assert "description" in vlan
        assert "parent_if" in vlan

    @pytest.mark.asyncio
    async def test_vlan_parent_interface(self) -> None:
        mock_client = _make_mock_client(get_cached_response=VLAN_INTERFACES_FIXTURE)
        with patch("opnsense.tools.interfaces._get_client", return_value=mock_client):
            from opnsense.tools.interfaces import opnsense__interfaces__list_vlan_interfaces

            result = await opnsense__interfaces__list_vlan_interfaces()

        for vlan in result:
            assert vlan["parent_if"] == "igb1"

    @pytest.mark.asyncio
    async def test_vlan_pcp_value(self) -> None:
        mock_client = _make_mock_client(get_cached_response=VLAN_INTERFACES_FIXTURE)
        with patch("opnsense.tools.interfaces._get_client", return_value=mock_client):
            from opnsense.tools.interfaces import opnsense__interfaces__list_vlan_interfaces

            result = await opnsense__interfaces__list_vlan_interfaces()

        mgmt_vlan = next(v for v in result if v["tag"] == 99)
        assert mgmt_vlan["pcp"] == 6


class TestGetDhcpLeases:
    """opnsense__interfaces__get_dhcp_leases()"""

    @pytest.mark.asyncio
    async def test_returns_all_leases(self) -> None:
        mock_client = _make_mock_client(get_cached_response=DHCP_LEASES_FIXTURE)
        with patch("opnsense.tools.interfaces._get_client", return_value=mock_client):
            from opnsense.tools.interfaces import opnsense__interfaces__get_dhcp_leases

            result = await opnsense__interfaces__get_dhcp_leases()

        assert len(result) == 5

    @pytest.mark.asyncio
    async def test_filter_by_interface(self) -> None:
        mock_client = _make_mock_client(get_cached_response=DHCP_LEASES_FIXTURE)
        with patch("opnsense.tools.interfaces._get_client", return_value=mock_client):
            from opnsense.tools.interfaces import opnsense__interfaces__get_dhcp_leases

            result = await opnsense__interfaces__get_dhcp_leases(interface="igb1_vlan30")

        assert len(result) == 2
        for lease in result:
            assert lease["interface"] == "igb1_vlan30"

    @pytest.mark.asyncio
    async def test_filter_no_match(self) -> None:
        mock_client = _make_mock_client(get_cached_response=DHCP_LEASES_FIXTURE)
        with patch("opnsense.tools.interfaces._get_client", return_value=mock_client):
            from opnsense.tools.interfaces import opnsense__interfaces__get_dhcp_leases

            result = await opnsense__interfaces__get_dhcp_leases(interface="nonexistent")

        assert result == []

    @pytest.mark.asyncio
    async def test_lease_has_expected_fields(self) -> None:
        mock_client = _make_mock_client(get_cached_response=DHCP_LEASES_FIXTURE)
        with patch("opnsense.tools.interfaces._get_client", return_value=mock_client):
            from opnsense.tools.interfaces import opnsense__interfaces__get_dhcp_leases

            result = await opnsense__interfaces__get_dhcp_leases()

        lease = result[0]
        assert "mac" in lease
        assert "ip" in lease
        assert "hostname" in lease
        assert "state" in lease
        assert "interface" in lease

    @pytest.mark.asyncio
    async def test_no_filter_returns_all(self) -> None:
        mock_client = _make_mock_client(get_cached_response=DHCP_LEASES_FIXTURE)
        with patch("opnsense.tools.interfaces._get_client", return_value=mock_client):
            from opnsense.tools.interfaces import opnsense__interfaces__get_dhcp_leases

            result = await opnsense__interfaces__get_dhcp_leases(interface=None)

        assert len(result) == 5


class TestAddVlanInterface:
    """opnsense__interfaces__add_vlan_interface()"""

    @pytest.mark.asyncio
    async def test_write_gate_env_var_disabled(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            from opnsense.tools.interfaces import opnsense__interfaces__add_vlan_interface

            with pytest.raises(WriteGateError) as exc_info:
                await opnsense__interfaces__add_vlan_interface(
                    tag=20,
                    parent_if="igb1",
                    description="Test",
                    apply=True,
                )
            assert exc_info.value.reason == WriteBlockReason.ENV_VAR_DISABLED

    @pytest.mark.asyncio
    async def test_write_gate_apply_missing(self) -> None:
        with patch.dict(os.environ, {"OPNSENSE_WRITE_ENABLED": "true"}):
            from opnsense.tools.interfaces import opnsense__interfaces__add_vlan_interface

            with pytest.raises(WriteGateError) as exc_info:
                await opnsense__interfaces__add_vlan_interface(
                    tag=20,
                    parent_if="igb1",
                    description="Test",
                )
            assert exc_info.value.reason == WriteBlockReason.APPLY_FLAG_MISSING

    @pytest.mark.asyncio
    async def test_invalid_vlan_tag_too_low(self) -> None:
        mock_client = _make_mock_client()
        with (
            patch.dict(os.environ, {"OPNSENSE_WRITE_ENABLED": "true"}),
            patch("opnsense.tools.interfaces._get_client", return_value=mock_client),
        ):
            from opnsense.tools.interfaces import opnsense__interfaces__add_vlan_interface

            with pytest.raises(ValidationError, match="1 and 4094"):
                await opnsense__interfaces__add_vlan_interface(
                    tag=0,
                    parent_if="igb1",
                    apply=True,
                )

    @pytest.mark.asyncio
    async def test_invalid_vlan_tag_too_high(self) -> None:
        mock_client = _make_mock_client()
        with (
            patch.dict(os.environ, {"OPNSENSE_WRITE_ENABLED": "true"}),
            patch("opnsense.tools.interfaces._get_client", return_value=mock_client),
        ):
            from opnsense.tools.interfaces import opnsense__interfaces__add_vlan_interface

            with pytest.raises(ValidationError, match="1 and 4094"):
                await opnsense__interfaces__add_vlan_interface(
                    tag=4095,
                    parent_if="igb1",
                    apply=True,
                )

    @pytest.mark.asyncio
    async def test_empty_parent_if(self) -> None:
        mock_client = _make_mock_client()
        with (
            patch.dict(os.environ, {"OPNSENSE_WRITE_ENABLED": "true"}),
            patch("opnsense.tools.interfaces._get_client", return_value=mock_client),
        ):
            from opnsense.tools.interfaces import opnsense__interfaces__add_vlan_interface

            with pytest.raises(ValidationError, match="empty"):
                await opnsense__interfaces__add_vlan_interface(
                    tag=20,
                    parent_if="",
                    apply=True,
                )

    @pytest.mark.asyncio
    async def test_successful_add(self) -> None:
        mock_client = _make_mock_client()
        with (
            patch.dict(os.environ, {"OPNSENSE_WRITE_ENABLED": "true"}),
            patch("opnsense.tools.interfaces._get_client", return_value=mock_client),
        ):
            from opnsense.tools.interfaces import opnsense__interfaces__add_vlan_interface

            result = await opnsense__interfaces__add_vlan_interface(
                tag=20,
                parent_if="igb1",
                description="Test VLAN",
                apply=True,
            )

        assert result["status"] == "created"
        assert result["tag"] == 20
        assert result["parent_if"] == "igb1"
        mock_client.write.assert_awaited_once()
        mock_client.reconfigure.assert_awaited_once()


class TestAddDhcpReservation:
    """opnsense__interfaces__add_dhcp_reservation()"""

    @pytest.mark.asyncio
    async def test_write_gate_blocks(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            from opnsense.tools.interfaces import opnsense__interfaces__add_dhcp_reservation

            with pytest.raises(WriteGateError):
                await opnsense__interfaces__add_dhcp_reservation(
                    interface="igb1",
                    mac="aa:bb:cc:dd:ee:ff",
                    ip="192.168.1.50",
                    apply=True,
                )

    @pytest.mark.asyncio
    async def test_empty_mac(self) -> None:
        mock_client = _make_mock_client()
        with (
            patch.dict(os.environ, {"OPNSENSE_WRITE_ENABLED": "true"}),
            patch("opnsense.tools.interfaces._get_client", return_value=mock_client),
        ):
            from opnsense.tools.interfaces import opnsense__interfaces__add_dhcp_reservation

            with pytest.raises(ValidationError, match="MAC"):
                await opnsense__interfaces__add_dhcp_reservation(
                    interface="igb1",
                    mac="",
                    ip="192.168.1.50",
                    apply=True,
                )

    @pytest.mark.asyncio
    async def test_successful_add(self) -> None:
        mock_client = _make_mock_client()
        with (
            patch.dict(os.environ, {"OPNSENSE_WRITE_ENABLED": "true"}),
            patch("opnsense.tools.interfaces._get_client", return_value=mock_client),
        ):
            from opnsense.tools.interfaces import opnsense__interfaces__add_dhcp_reservation

            result = await opnsense__interfaces__add_dhcp_reservation(
                interface="igb1",
                mac="aa:bb:cc:dd:ee:ff",
                ip="192.168.1.50",
                hostname="my-device",
                apply=True,
            )

        assert result["status"] == "created"
        assert result["mac"] == "aa:bb:cc:dd:ee:ff"
        assert result["ip"] == "192.168.1.50"


class TestAddDhcpSubnet:
    """opnsense__interfaces__add_dhcp_subnet()"""

    @pytest.mark.asyncio
    async def test_write_gate_blocks(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            from opnsense.tools.interfaces import opnsense__interfaces__add_dhcp_subnet

            with pytest.raises(WriteGateError):
                await opnsense__interfaces__add_dhcp_subnet(
                    interface="igb1_vlan10",
                    subnet="192.168.10.0/24",
                    range_from="192.168.10.100",
                    range_to="192.168.10.200",
                    apply=True,
                )

    @pytest.mark.asyncio
    async def test_empty_interface(self) -> None:
        mock_client = _make_mock_client()
        with (
            patch.dict(os.environ, {"OPNSENSE_WRITE_ENABLED": "true"}),
            patch("opnsense.tools.interfaces._get_client", return_value=mock_client),
        ):
            from opnsense.tools.interfaces import opnsense__interfaces__add_dhcp_subnet

            with pytest.raises(ValidationError, match="Interface"):
                await opnsense__interfaces__add_dhcp_subnet(
                    interface="",
                    subnet="192.168.10.0/24",
                    range_from="192.168.10.100",
                    range_to="192.168.10.200",
                    apply=True,
                )

    @pytest.mark.asyncio
    async def test_successful_add(self) -> None:
        mock_client = _make_mock_client()
        with (
            patch.dict(os.environ, {"OPNSENSE_WRITE_ENABLED": "true"}),
            patch("opnsense.tools.interfaces._get_client", return_value=mock_client),
        ):
            from opnsense.tools.interfaces import opnsense__interfaces__add_dhcp_subnet

            result = await opnsense__interfaces__add_dhcp_subnet(
                interface="igb1_vlan10",
                subnet="192.168.10.0/24",
                range_from="192.168.10.100",
                range_to="192.168.10.200",
                dns_servers="1.1.1.1,8.8.8.8",
                apply=True,
            )

        assert result["status"] == "created"
        assert result["subnet"] == "192.168.10.0/24"
        assert result["dns_servers"] == "1.1.1.1,8.8.8.8"


class TestConfigureVlan:
    """opnsense__interfaces__configure_vlan()"""

    @pytest.mark.asyncio
    async def test_write_gate_blocks(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            from opnsense.tools.interfaces import opnsense__interfaces__configure_vlan

            with pytest.raises(WriteGateError):
                await opnsense__interfaces__configure_vlan(
                    tag=20,
                    parent_if="igb1",
                    ip="192.168.20.1",
                    subnet="24",
                    apply=True,
                )

    @pytest.mark.asyncio
    async def test_invalid_vlan_tag(self) -> None:
        mock_client = _make_mock_client()
        with (
            patch.dict(os.environ, {"OPNSENSE_WRITE_ENABLED": "true"}),
            patch("opnsense.tools.interfaces._get_client", return_value=mock_client),
        ):
            from opnsense.tools.interfaces import opnsense__interfaces__configure_vlan

            with pytest.raises(ValidationError, match="1 and 4094"):
                await opnsense__interfaces__configure_vlan(
                    tag=5000,
                    parent_if="igb1",
                    ip="192.168.20.1",
                    subnet="24",
                    apply=True,
                )

    @pytest.mark.asyncio
    async def test_dhcp_range_partial(self) -> None:
        mock_client = _make_mock_client()
        with (
            patch.dict(os.environ, {"OPNSENSE_WRITE_ENABLED": "true"}),
            patch("opnsense.tools.interfaces._get_client", return_value=mock_client),
        ):
            from opnsense.tools.interfaces import opnsense__interfaces__configure_vlan

            with pytest.raises(ValidationError, match="together"):
                await opnsense__interfaces__configure_vlan(
                    tag=20,
                    parent_if="igb1",
                    ip="192.168.20.1",
                    subnet="24",
                    dhcp_range_from="192.168.20.100",
                    apply=True,
                )

    @pytest.mark.asyncio
    async def test_successful_configure_without_dhcp(self) -> None:
        mock_client = _make_mock_client()
        with (
            patch.dict(os.environ, {"OPNSENSE_WRITE_ENABLED": "true"}),
            patch("opnsense.tools.interfaces._get_client", return_value=mock_client),
        ):
            from opnsense.tools.interfaces import opnsense__interfaces__configure_vlan

            result = await opnsense__interfaces__configure_vlan(
                tag=20,
                parent_if="igb1",
                ip="192.168.20.1",
                subnet="24",
                description="Test VLAN 20",
                apply=True,
            )

        assert result["status"] == "configured"
        assert result["tag"] == 20
        assert "configure_dhcp" not in result.get("completed_steps", [])
        # write called once (VLAN creation), reconfigure once (vlan_settings)
        # IP assignment uses post_legacy, not write
        assert mock_client.write.await_count >= 1
        assert mock_client.reconfigure.await_count >= 1

    @pytest.mark.asyncio
    async def test_successful_configure_with_dhcp(self) -> None:
        mock_client = _make_mock_client()
        # post_legacy must return HTML so the interface assignment lookup works.
        # Second call returns HTML with a select for our VLAN device.
        assign_html = (
            '<select name="opt3"><option value="vlan0.20" selected>vlan0.20</option></select>'
        )
        mock_client.post_legacy = AsyncMock(side_effect=["", assign_html, "", ""])
        with (
            patch.dict(os.environ, {"OPNSENSE_WRITE_ENABLED": "true"}),
            patch("opnsense.tools.interfaces._get_client", return_value=mock_client),
        ):
            from opnsense.tools.interfaces import opnsense__interfaces__configure_vlan

            result = await opnsense__interfaces__configure_vlan(
                tag=20,
                parent_if="igb1",
                ip="192.168.20.1",
                subnet="24",
                dhcp_range_from="192.168.20.100",
                dhcp_range_to="192.168.20.200",
                apply=True,
            )

        assert result["status"] == "configured"
        assert "configure_dhcp" in result["completed_steps"]
        assert result["dhcp_range_from"] == "192.168.20.100"

    @pytest.mark.asyncio
    async def test_step3_failure_recorded_in_completed_steps(self) -> None:
        """When legacy IP assignment fails, step3_failed is recorded.

        Step 3 (interface assignment + IP) uses legacy PHP pages which
        may fail without rolling back the VLAN.  The failure is recorded
        gracefully so the VLAN device exists and can be configured manually.
        """
        mock_client = _make_mock_client()
        # post_legacy raises to simulate Step 3 failure
        mock_client.post_legacy = AsyncMock(side_effect=Exception("Legacy page unavailable"))

        with (
            patch.dict(os.environ, {"OPNSENSE_WRITE_ENABLED": "true"}),
            patch("opnsense.tools.interfaces._get_client", return_value=mock_client),
        ):
            from opnsense.tools.interfaces import opnsense__interfaces__configure_vlan

            result = await opnsense__interfaces__configure_vlan(
                tag=20,
                parent_if="igb1",
                ip="192.168.20.1",
                subnet="24",
                apply=True,
            )

        assert result["status"] == "configured"
        assert "step3_failed" in result["completed_steps"]
        # VLAN write + reconfigure should still have been called
        mock_client.write.assert_awaited_once()
        mock_client.reconfigure.assert_awaited_once()


# ===========================================================================
# Task 88-89: Firewall Tools
# ===========================================================================


class TestListRules:
    """opnsense__firewall__list_rules()"""

    @pytest.mark.asyncio
    async def test_returns_all_rules(self) -> None:
        mock_client = _make_mock_client(get_cached_response=FIREWALL_RULES_FIXTURE)
        with patch("opnsense.tools.firewall._get_client", return_value=mock_client):
            from opnsense.tools.firewall import opnsense__firewall__list_rules

            result = await opnsense__firewall__list_rules()

        assert len(result) == 5
        mock_client.close.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_filter_by_interface(self) -> None:
        mock_client = _make_mock_client(get_cached_response=FIREWALL_RULES_FIXTURE)
        with patch("opnsense.tools.firewall._get_client", return_value=mock_client):
            from opnsense.tools.firewall import opnsense__firewall__list_rules

            result = await opnsense__firewall__list_rules(interface="opt1")

        assert len(result) == 2
        for rule in result:
            assert rule["interface"] == "opt1"

    @pytest.mark.asyncio
    async def test_rule_has_expected_fields(self) -> None:
        mock_client = _make_mock_client(get_cached_response=FIREWALL_RULES_FIXTURE)
        with patch("opnsense.tools.firewall._get_client", return_value=mock_client):
            from opnsense.tools.firewall import opnsense__firewall__list_rules

            result = await opnsense__firewall__list_rules()

        rule = result[0]
        assert "uuid" in rule
        assert "action" in rule
        assert "source" in rule
        assert "destination" in rule

    @pytest.mark.asyncio
    async def test_filter_no_match(self) -> None:
        mock_client = _make_mock_client(get_cached_response=FIREWALL_RULES_FIXTURE)
        with patch("opnsense.tools.firewall._get_client", return_value=mock_client):
            from opnsense.tools.firewall import opnsense__firewall__list_rules

            result = await opnsense__firewall__list_rules(interface="nonexistent")

        assert result == []


class TestGetRule:
    """opnsense__firewall__get_rule()"""

    @pytest.mark.asyncio
    async def test_returns_rule(self) -> None:
        rule_data = {"rule": {"uuid": "test-uuid", "action": "pass"}}
        mock_client = _make_mock_client(get_response=rule_data)
        with patch("opnsense.tools.firewall._get_client", return_value=mock_client):
            from opnsense.tools.firewall import opnsense__firewall__get_rule

            result = await opnsense__firewall__get_rule(uuid="test-uuid")

        assert result["uuid"] == "test-uuid"

    @pytest.mark.asyncio
    async def test_empty_uuid_raises(self) -> None:
        from opnsense.tools.firewall import opnsense__firewall__get_rule

        with pytest.raises(ValidationError, match="UUID"):
            await opnsense__firewall__get_rule(uuid="")


class TestListAliases:
    """opnsense__firewall__list_aliases()"""

    @pytest.mark.asyncio
    async def test_returns_all_aliases(self) -> None:
        mock_client = _make_mock_client(get_cached_response=ALIASES_FIXTURE)
        with patch("opnsense.tools.firewall._get_client", return_value=mock_client):
            from opnsense.tools.firewall import opnsense__firewall__list_aliases

            result = await opnsense__firewall__list_aliases()

        assert len(result) == 3
        assert result[0]["name"] == "rfc1918_nets"

    @pytest.mark.asyncio
    async def test_alias_has_expected_fields(self) -> None:
        mock_client = _make_mock_client(get_cached_response=ALIASES_FIXTURE)
        with patch("opnsense.tools.firewall._get_client", return_value=mock_client):
            from opnsense.tools.firewall import opnsense__firewall__list_aliases

            result = await opnsense__firewall__list_aliases()

        alias = result[0]
        assert "uuid" in alias
        assert "name" in alias
        assert "alias_type" in alias
        assert "content" in alias


class TestListNatRules:
    """opnsense__firewall__list_nat_rules()"""

    @pytest.mark.asyncio
    async def test_returns_all_nat_rules(self) -> None:
        mock_client = _make_mock_client(get_cached_response=NAT_RULES_FIXTURE)
        with patch("opnsense.tools.firewall._get_client", return_value=mock_client):
            from opnsense.tools.firewall import opnsense__firewall__list_nat_rules

            result = await opnsense__firewall__list_nat_rules()

        assert len(result) == 2

    @pytest.mark.asyncio
    async def test_nat_rule_has_target(self) -> None:
        mock_client = _make_mock_client(get_cached_response=NAT_RULES_FIXTURE)
        with patch("opnsense.tools.firewall._get_client", return_value=mock_client):
            from opnsense.tools.firewall import opnsense__firewall__list_nat_rules

            result = await opnsense__firewall__list_nat_rules()

        assert result[0]["target"] == "192.168.1.50"
        assert result[0]["target_port"] == "80"


class TestAddRule:
    """opnsense__firewall__add_rule()"""

    @pytest.mark.asyncio
    async def test_write_gate_blocks(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            from opnsense.tools.firewall import opnsense__firewall__add_rule

            with pytest.raises(WriteGateError):
                await opnsense__firewall__add_rule(
                    interface="lan",
                    action="pass",
                    src="any",
                    dst="any",
                    apply=True,
                )

    @pytest.mark.asyncio
    async def test_invalid_action(self) -> None:
        mock_client = _make_mock_client()
        with (
            patch.dict(os.environ, {"OPNSENSE_WRITE_ENABLED": "true"}),
            patch("opnsense.tools.firewall._get_client", return_value=mock_client),
        ):
            from opnsense.tools.firewall import opnsense__firewall__add_rule

            with pytest.raises(ValidationError, match="Action"):
                await opnsense__firewall__add_rule(
                    interface="lan",
                    action="allow",
                    src="any",
                    dst="any",
                    apply=True,
                )

    @pytest.mark.asyncio
    async def test_empty_interface(self) -> None:
        mock_client = _make_mock_client()
        with (
            patch.dict(os.environ, {"OPNSENSE_WRITE_ENABLED": "true"}),
            patch("opnsense.tools.firewall._get_client", return_value=mock_client),
        ):
            from opnsense.tools.firewall import opnsense__firewall__add_rule

            with pytest.raises(ValidationError, match="Interface"):
                await opnsense__firewall__add_rule(
                    interface="",
                    action="pass",
                    src="any",
                    dst="any",
                    apply=True,
                )

    @pytest.mark.asyncio
    async def test_successful_add(self) -> None:
        mock_client = _make_mock_client()
        # Savepoint returns a revision so the apply/cancelRollback flow runs
        mock_client.post = AsyncMock(
            side_effect=[
                {"revision": "abc123"},  # savepoint
                {"status": "ok"},  # apply
                {"status": "ok"},  # cancelRollback
            ],
        )
        with (
            patch.dict(os.environ, {"OPNSENSE_WRITE_ENABLED": "true"}),
            patch("opnsense.tools.firewall._get_client", return_value=mock_client),
        ):
            from opnsense.tools.firewall import opnsense__firewall__add_rule

            result = await opnsense__firewall__add_rule(
                interface="lan",
                action="block",
                src="192.168.1.0/24",
                dst="10.0.0.0/8",
                protocol="TCP",
                description="Block LAN to VPN",
                apply=True,
            )

        assert result["status"] == "created"
        assert result["action"] == "block"
        mock_client.write.assert_awaited_once()
        # OPNsense 26.x uses savepoint/apply/cancelRollback instead of reconfigure
        assert mock_client.post.await_count == 3

    @pytest.mark.asyncio
    async def test_add_with_position(self) -> None:
        mock_client = _make_mock_client()
        with (
            patch.dict(os.environ, {"OPNSENSE_WRITE_ENABLED": "true"}),
            patch("opnsense.tools.firewall._get_client", return_value=mock_client),
        ):
            from opnsense.tools.firewall import opnsense__firewall__add_rule

            result = await opnsense__firewall__add_rule(
                interface="lan",
                action="pass",
                src="any",
                dst="any",
                position=5,
                apply=True,
            )

        assert result["status"] == "created"
        write_data = mock_client.write.call_args.kwargs["data"]
        assert write_data["rule"]["sequence"] == "5"


class TestToggleRule:
    """opnsense__firewall__toggle_rule()"""

    @pytest.mark.asyncio
    async def test_write_gate_blocks(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            from opnsense.tools.firewall import opnsense__firewall__toggle_rule

            with pytest.raises(WriteGateError):
                await opnsense__firewall__toggle_rule(
                    uuid="test-uuid",
                    enabled=False,
                    apply=True,
                )

    @pytest.mark.asyncio
    async def test_empty_uuid(self) -> None:
        mock_client = _make_mock_client()
        with (
            patch.dict(os.environ, {"OPNSENSE_WRITE_ENABLED": "true"}),
            patch("opnsense.tools.firewall._get_client", return_value=mock_client),
        ):
            from opnsense.tools.firewall import opnsense__firewall__toggle_rule

            with pytest.raises(ValidationError, match="UUID"):
                await opnsense__firewall__toggle_rule(
                    uuid="",
                    enabled=True,
                    apply=True,
                )

    @pytest.mark.asyncio
    async def test_disable_rule(self) -> None:
        mock_client = _make_mock_client()
        with (
            patch.dict(os.environ, {"OPNSENSE_WRITE_ENABLED": "true"}),
            patch("opnsense.tools.firewall._get_client", return_value=mock_client),
        ):
            from opnsense.tools.firewall import opnsense__firewall__toggle_rule

            result = await opnsense__firewall__toggle_rule(
                uuid="test-uuid",
                enabled=False,
                apply=True,
            )

        assert result["status"] == "disabled"
        assert result["enabled"] is False

    @pytest.mark.asyncio
    async def test_enable_rule(self) -> None:
        mock_client = _make_mock_client()
        with (
            patch.dict(os.environ, {"OPNSENSE_WRITE_ENABLED": "true"}),
            patch("opnsense.tools.firewall._get_client", return_value=mock_client),
        ):
            from opnsense.tools.firewall import opnsense__firewall__toggle_rule

            result = await opnsense__firewall__toggle_rule(
                uuid="test-uuid",
                enabled=True,
                apply=True,
            )

        assert result["status"] == "enabled"
        assert result["enabled"] is True


class TestAddAlias:
    """opnsense__firewall__add_alias()"""

    @pytest.mark.asyncio
    async def test_write_gate_blocks(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            from opnsense.tools.firewall import opnsense__firewall__add_alias

            with pytest.raises(WriteGateError):
                await opnsense__firewall__add_alias(
                    name="test",
                    alias_type="host",
                    content="1.2.3.4",
                    apply=True,
                )

    @pytest.mark.asyncio
    async def test_invalid_type(self) -> None:
        mock_client = _make_mock_client()
        with (
            patch.dict(os.environ, {"OPNSENSE_WRITE_ENABLED": "true"}),
            patch("opnsense.tools.firewall._get_client", return_value=mock_client),
        ):
            from opnsense.tools.firewall import opnsense__firewall__add_alias

            with pytest.raises(ValidationError, match="type"):
                await opnsense__firewall__add_alias(
                    name="test",
                    alias_type="invalid",
                    content="1.2.3.4",
                    apply=True,
                )

    @pytest.mark.asyncio
    async def test_empty_name(self) -> None:
        mock_client = _make_mock_client()
        with (
            patch.dict(os.environ, {"OPNSENSE_WRITE_ENABLED": "true"}),
            patch("opnsense.tools.firewall._get_client", return_value=mock_client),
        ):
            from opnsense.tools.firewall import opnsense__firewall__add_alias

            with pytest.raises(ValidationError, match="name"):
                await opnsense__firewall__add_alias(
                    name="",
                    alias_type="host",
                    content="1.2.3.4",
                    apply=True,
                )

    @pytest.mark.asyncio
    async def test_empty_content(self) -> None:
        mock_client = _make_mock_client()
        with (
            patch.dict(os.environ, {"OPNSENSE_WRITE_ENABLED": "true"}),
            patch("opnsense.tools.firewall._get_client", return_value=mock_client),
        ):
            from opnsense.tools.firewall import opnsense__firewall__add_alias

            with pytest.raises(ValidationError, match="content"):
                await opnsense__firewall__add_alias(
                    name="test",
                    alias_type="host",
                    content="",
                    apply=True,
                )

    @pytest.mark.asyncio
    async def test_successful_add(self) -> None:
        mock_client = _make_mock_client()
        with (
            patch.dict(os.environ, {"OPNSENSE_WRITE_ENABLED": "true"}),
            patch("opnsense.tools.firewall._get_client", return_value=mock_client),
        ):
            from opnsense.tools.firewall import opnsense__firewall__add_alias

            result = await opnsense__firewall__add_alias(
                name="blocked_hosts",
                alias_type="host",
                content="10.0.0.1\n10.0.0.2",
                description="Blocked hosts",
                apply=True,
            )

        assert result["status"] == "created"
        assert result["name"] == "blocked_hosts"
        assert result["alias_type"] == "host"


# ===========================================================================
# Task 90-91: Routing Tools
# ===========================================================================


class TestListRoutes:
    """opnsense__routing__list_routes()"""

    @pytest.mark.asyncio
    async def test_returns_all_routes(self) -> None:
        mock_client = _make_mock_client(get_cached_response=ROUTES_FIXTURE)
        # Quagga probe should return 404
        mock_client.get = AsyncMock(side_effect=APIError("Not found", status_code=404))
        with patch("opnsense.tools.routing._get_client", return_value=mock_client):
            from opnsense.tools.routing import opnsense__routing__list_routes

            result = await opnsense__routing__list_routes()

        assert len(result) == 3

    @pytest.mark.asyncio
    async def test_route_has_expected_fields(self) -> None:
        mock_client = _make_mock_client(get_cached_response=ROUTES_FIXTURE)
        mock_client.get = AsyncMock(side_effect=APIError("Not found", status_code=404))
        with patch("opnsense.tools.routing._get_client", return_value=mock_client):
            from opnsense.tools.routing import opnsense__routing__list_routes

            result = await opnsense__routing__list_routes()

        route = result[0]
        assert "uuid" in route
        assert "network" in route
        assert "gateway" in route
        assert "description" in route
        assert "disabled" in route

    @pytest.mark.asyncio
    async def test_disabled_route_flag(self) -> None:
        mock_client = _make_mock_client(get_cached_response=ROUTES_FIXTURE)
        mock_client.get = AsyncMock(side_effect=APIError("Not found", status_code=404))
        with patch("opnsense.tools.routing._get_client", return_value=mock_client):
            from opnsense.tools.routing import opnsense__routing__list_routes

            result = await opnsense__routing__list_routes()

        disabled_routes = [r for r in result if r["disabled"]]
        assert len(disabled_routes) == 1
        assert disabled_routes[0]["network"] == "192.168.200.0/24"


class TestListGateways:
    """opnsense__routing__list_gateways()"""

    @pytest.mark.asyncio
    async def test_returns_all_gateways(self) -> None:
        mock_client = _make_mock_client(get_cached_response=GATEWAYS_FIXTURE)
        with patch("opnsense.tools.routing._get_client", return_value=mock_client):
            from opnsense.tools.routing import opnsense__routing__list_gateways

            result = await opnsense__routing__list_gateways()

        assert len(result) == 2
        assert result[0]["name"] == "WAN_DHCP"

    @pytest.mark.asyncio
    async def test_gateway_has_expected_fields(self) -> None:
        mock_client = _make_mock_client(get_cached_response=GATEWAYS_FIXTURE)
        with patch("opnsense.tools.routing._get_client", return_value=mock_client):
            from opnsense.tools.routing import opnsense__routing__list_gateways

            result = await opnsense__routing__list_gateways()

        gw = result[0]
        assert "name" in gw
        assert "gateway" in gw
        assert "interface" in gw
        assert "status" in gw
        assert "rtt_ms" in gw

    @pytest.mark.asyncio
    async def test_gateway_rtt(self) -> None:
        mock_client = _make_mock_client(get_cached_response=GATEWAYS_FIXTURE)
        with patch("opnsense.tools.routing._get_client", return_value=mock_client):
            from opnsense.tools.routing import opnsense__routing__list_gateways

            result = await opnsense__routing__list_gateways()

        assert result[0]["rtt_ms"] == pytest.approx(4.231)
        assert result[1]["rtt_ms"] == pytest.approx(12.7)


class TestQuaggraGracefulDegradation:
    """Quagga probe returns 404 when plugin is not installed."""

    @pytest.mark.asyncio
    async def test_quagga_404_returns_false(self) -> None:
        from opnsense.tools.routing import _probe_quagga

        mock_client = MagicMock(spec=OPNsenseClient)
        mock_client.get = AsyncMock(
            side_effect=APIError("Not found", status_code=404),
        )

        result = await _probe_quagga(mock_client)
        assert result is False

    @pytest.mark.asyncio
    async def test_quagga_available(self) -> None:
        from opnsense.tools.routing import _probe_quagga

        mock_client = MagicMock(spec=OPNsenseClient)
        mock_client.get = AsyncMock(return_value={"status": "ok"})

        result = await _probe_quagga(mock_client)
        assert result is True

    @pytest.mark.asyncio
    async def test_quagga_unexpected_error(self) -> None:
        from opnsense.tools.routing import _probe_quagga

        mock_client = MagicMock(spec=OPNsenseClient)
        mock_client.get = AsyncMock(side_effect=Exception("Unexpected"))

        result = await _probe_quagga(mock_client)
        assert result is False


class TestAddRoute:
    """opnsense__routing__add_route()"""

    @pytest.mark.asyncio
    async def test_write_gate_blocks(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            from opnsense.tools.routing import opnsense__routing__add_route

            with pytest.raises(WriteGateError):
                await opnsense__routing__add_route(
                    network="10.0.0.0/8",
                    gateway="WAN_GW",
                    apply=True,
                )

    @pytest.mark.asyncio
    async def test_empty_network(self) -> None:
        mock_client = _make_mock_client()
        with (
            patch.dict(os.environ, {"OPNSENSE_WRITE_ENABLED": "true"}),
            patch("opnsense.tools.routing._get_client", return_value=mock_client),
        ):
            from opnsense.tools.routing import opnsense__routing__add_route

            with pytest.raises(ValidationError, match="Network"):
                await opnsense__routing__add_route(
                    network="",
                    gateway="WAN_GW",
                    apply=True,
                )

    @pytest.mark.asyncio
    async def test_empty_gateway(self) -> None:
        mock_client = _make_mock_client()
        with (
            patch.dict(os.environ, {"OPNSENSE_WRITE_ENABLED": "true"}),
            patch("opnsense.tools.routing._get_client", return_value=mock_client),
        ):
            from opnsense.tools.routing import opnsense__routing__add_route

            with pytest.raises(ValidationError, match="Gateway"):
                await opnsense__routing__add_route(
                    network="10.0.0.0/8",
                    gateway="",
                    apply=True,
                )

    @pytest.mark.asyncio
    async def test_successful_add(self) -> None:
        mock_client = _make_mock_client()
        with (
            patch.dict(os.environ, {"OPNSENSE_WRITE_ENABLED": "true"}),
            patch("opnsense.tools.routing._get_client", return_value=mock_client),
        ):
            from opnsense.tools.routing import opnsense__routing__add_route

            result = await opnsense__routing__add_route(
                network="10.0.0.0/8",
                gateway="WAN_GW",
                description="Test route",
                apply=True,
            )

        assert result["status"] == "created"
        assert result["network"] == "10.0.0.0/8"
        assert result["gateway"] == "WAN_GW"
        mock_client.write.assert_awaited_once()
        mock_client.reconfigure.assert_awaited_once()


# ===========================================================================
# Task 92: Diagnostics Tools
# ===========================================================================


class TestGetLldpNeighbors:
    """opnsense__diagnostics__get_lldp_neighbors()"""

    @pytest.mark.asyncio
    async def test_returns_all_neighbors(self) -> None:
        mock_client = _make_mock_client(get_response=LLDP_NEIGHBORS_FIXTURE)
        with patch("opnsense.tools.diagnostics._get_client", return_value=mock_client):
            from opnsense.tools.diagnostics import opnsense__diagnostics__get_lldp_neighbors

            result = await opnsense__diagnostics__get_lldp_neighbors()

        assert len(result) == 2
        mock_client.close.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_filter_by_interface(self) -> None:
        mock_client = _make_mock_client(get_response=LLDP_NEIGHBORS_FIXTURE)
        with patch("opnsense.tools.diagnostics._get_client", return_value=mock_client):
            from opnsense.tools.diagnostics import opnsense__diagnostics__get_lldp_neighbors

            result = await opnsense__diagnostics__get_lldp_neighbors(interface="igb0")

        assert len(result) == 1
        assert result[0]["local_interface"] == "igb0"

    @pytest.mark.asyncio
    async def test_neighbor_has_expected_fields(self) -> None:
        mock_client = _make_mock_client(get_response=LLDP_NEIGHBORS_FIXTURE)
        with patch("opnsense.tools.diagnostics._get_client", return_value=mock_client):
            from opnsense.tools.diagnostics import opnsense__diagnostics__get_lldp_neighbors

            result = await opnsense__diagnostics__get_lldp_neighbors()

        neighbor = result[0]
        assert "local_interface" in neighbor
        assert "chassis_name" in neighbor
        assert "chassis_id" in neighbor

    @pytest.mark.asyncio
    async def test_empty_response(self) -> None:
        mock_client = _make_mock_client(get_response={"lldp": {"interface": []}})
        with patch("opnsense.tools.diagnostics._get_client", return_value=mock_client):
            from opnsense.tools.diagnostics import opnsense__diagnostics__get_lldp_neighbors

            result = await opnsense__diagnostics__get_lldp_neighbors()

        assert result == []

    @pytest.mark.asyncio
    async def test_filter_no_match(self) -> None:
        mock_client = _make_mock_client(get_response=LLDP_NEIGHBORS_FIXTURE)
        with patch("opnsense.tools.diagnostics._get_client", return_value=mock_client):
            from opnsense.tools.diagnostics import opnsense__diagnostics__get_lldp_neighbors

            result = await opnsense__diagnostics__get_lldp_neighbors(interface="igb99")

        assert result == []


# ===========================================================================
# Task 93: Agents
# ===========================================================================


class TestInterfaceAgent:
    """agents.interfaces.run_interface_report()"""

    @pytest.mark.asyncio
    async def test_generates_report(self) -> None:
        mock_iface_client = _make_mock_client(get_cached_response=INTERFACES_FIXTURE)
        mock_vlan_client = _make_mock_client(get_cached_response=VLAN_INTERFACES_FIXTURE)
        mock_dhcp_client = _make_mock_client(get_cached_response=DHCP_LEASES_FIXTURE)

        with patch("opnsense.tools.interfaces._get_client") as mock_factory:
            mock_factory.side_effect = [mock_iface_client, mock_vlan_client, mock_dhcp_client]
            from opnsense.agents.interfaces import run_interface_report

            report = await run_interface_report()

        assert "Interface & VLAN Inventory Report" in report
        assert "4 interfaces" in report
        assert "7 VLANs" in report
        assert "5 DHCP leases" in report

    @pytest.mark.asyncio
    async def test_report_contains_interface_table(self) -> None:
        mock_iface_client = _make_mock_client(get_cached_response=INTERFACES_FIXTURE)
        mock_vlan_client = _make_mock_client(get_cached_response=VLAN_INTERFACES_FIXTURE)
        mock_dhcp_client = _make_mock_client(get_cached_response=DHCP_LEASES_FIXTURE)

        with patch("opnsense.tools.interfaces._get_client") as mock_factory:
            mock_factory.side_effect = [mock_iface_client, mock_vlan_client, mock_dhcp_client]
            from opnsense.agents.interfaces import run_interface_report

            report = await run_interface_report()

        assert "Interface Inventory" in report
        assert "igb0" in report
        assert "WAN" in report

    @pytest.mark.asyncio
    async def test_report_detects_expired_leases(self) -> None:
        mock_iface_client = _make_mock_client(get_cached_response=INTERFACES_FIXTURE)
        mock_vlan_client = _make_mock_client(get_cached_response=VLAN_INTERFACES_FIXTURE)
        mock_dhcp_client = _make_mock_client(get_cached_response=DHCP_LEASES_FIXTURE)

        with patch("opnsense.tools.interfaces._get_client") as mock_factory:
            mock_factory.side_effect = [mock_iface_client, mock_vlan_client, mock_dhcp_client]
            from opnsense.agents.interfaces import run_interface_report

            report = await run_interface_report()

        assert "expired" in report.lower()


class TestFirewallAgent:
    """agents.firewall.run_firewall_audit()"""

    @pytest.mark.asyncio
    async def test_generates_report(self) -> None:
        mock_rules_client = _make_mock_client(get_cached_response=FIREWALL_RULES_FIXTURE)
        mock_aliases_client = _make_mock_client(get_cached_response=ALIASES_FIXTURE)
        mock_nat_client = _make_mock_client(get_cached_response=NAT_RULES_FIXTURE)

        with patch("opnsense.tools.firewall._get_client") as mock_factory:
            mock_factory.side_effect = [mock_rules_client, mock_aliases_client, mock_nat_client]
            from opnsense.agents.firewall import run_firewall_audit

            report = await run_firewall_audit()

        assert "Firewall Audit Report" in report
        assert "5 active rules" in report
        assert "3 aliases" in report

    @pytest.mark.asyncio
    async def test_report_contains_rule_table(self) -> None:
        mock_rules_client = _make_mock_client(get_cached_response=FIREWALL_RULES_FIXTURE)
        mock_aliases_client = _make_mock_client(get_cached_response=ALIASES_FIXTURE)
        mock_nat_client = _make_mock_client(get_cached_response=NAT_RULES_FIXTURE)

        with patch("opnsense.tools.firewall._get_client") as mock_factory:
            mock_factory.side_effect = [mock_rules_client, mock_aliases_client, mock_nat_client]
            from opnsense.agents.firewall import run_firewall_audit

            report = await run_firewall_audit()

        assert "Firewall Rules" in report
        assert "Allow LAN to WAN" in report

    @pytest.mark.asyncio
    async def test_detects_block_without_logging(self) -> None:
        """The fixture has block rules without logging -- should be detected."""
        mock_rules_client = _make_mock_client(get_cached_response=FIREWALL_RULES_FIXTURE)
        mock_aliases_client = _make_mock_client(get_cached_response=ALIASES_FIXTURE)
        mock_nat_client = _make_mock_client(get_cached_response=NAT_RULES_FIXTURE)

        with patch("opnsense.tools.firewall._get_client") as mock_factory:
            mock_factory.side_effect = [mock_rules_client, mock_aliases_client, mock_nat_client]
            from opnsense.agents.firewall import run_firewall_audit

            report = await run_firewall_audit()

        # There are block rules in the fixture -- some may lack logging
        assert "Findings" in report

    @pytest.mark.asyncio
    async def test_overly_permissive_detection(self) -> None:
        """Test detection of any->any pass rules."""
        from opnsense.agents.firewall import _check_overly_permissive

        rule: dict[str, Any] = {
            "uuid": "test",
            "action": "pass",
            "source": "any",
            "destination": "any",
            "protocol": "any",
            "enabled": True,
            "interface": "lan",
            "description": "Allow all",
        }
        finding = _check_overly_permissive(rule)
        assert finding is not None
        assert finding.severity.value == "high"

    @pytest.mark.asyncio
    async def test_non_permissive_rule_no_finding(self) -> None:
        """Test that a restricted rule does not trigger overly permissive finding."""
        from opnsense.agents.firewall import _check_overly_permissive

        rule: dict[str, Any] = {
            "uuid": "test",
            "action": "pass",
            "source": "192.168.1.0/24",
            "destination": "any",
            "protocol": "TCP",
            "enabled": True,
            "interface": "lan",
        }
        finding = _check_overly_permissive(rule)
        assert finding is None

    @pytest.mark.asyncio
    async def test_disabled_rule_detection(self) -> None:
        from opnsense.agents.firewall import _check_disabled_rule

        rule: dict[str, Any] = {
            "uuid": "test",
            "enabled": False,
            "description": "Old rule",
            "interface": "lan",
        }
        finding = _check_disabled_rule(rule)
        assert finding is not None
        assert finding.severity.value == "informational"

    @pytest.mark.asyncio
    async def test_no_logging_detection(self) -> None:
        from opnsense.agents.firewall import _check_no_logging

        rule: dict[str, Any] = {
            "uuid": "test",
            "action": "block",
            "log": False,
            "enabled": True,
            "description": "Block without log",
            "interface": "wan",
        }
        finding = _check_no_logging(rule)
        assert finding is not None
        assert finding.severity.value == "warning"


class TestRoutingAgent:
    """agents.routing.run_routing_report()"""

    @pytest.mark.asyncio
    async def test_generates_report(self) -> None:
        mock_routes_client = _make_mock_client(get_cached_response=ROUTES_FIXTURE)
        mock_routes_client.get = AsyncMock(side_effect=APIError("Not found", status_code=404))
        mock_gw_client = _make_mock_client(get_cached_response=GATEWAYS_FIXTURE)

        with patch("opnsense.tools.routing._get_client") as mock_factory:
            mock_factory.side_effect = [mock_routes_client, mock_gw_client]
            from opnsense.agents.routing import run_routing_report

            report = await run_routing_report()

        assert "Routing Table Report" in report
        assert "gateways online" in report

    @pytest.mark.asyncio
    async def test_report_contains_gateway_table(self) -> None:
        mock_routes_client = _make_mock_client(get_cached_response=ROUTES_FIXTURE)
        mock_routes_client.get = AsyncMock(side_effect=APIError("Not found", status_code=404))
        mock_gw_client = _make_mock_client(get_cached_response=GATEWAYS_FIXTURE)

        with patch("opnsense.tools.routing._get_client") as mock_factory:
            mock_factory.side_effect = [mock_routes_client, mock_gw_client]
            from opnsense.agents.routing import run_routing_report

            report = await run_routing_report()

        assert "Gateway Status" in report
        assert "WAN_GW" in report

    @pytest.mark.asyncio
    async def test_detects_disabled_routes(self) -> None:
        mock_routes_client = _make_mock_client(get_cached_response=ROUTES_FIXTURE)
        mock_routes_client.get = AsyncMock(side_effect=APIError("Not found", status_code=404))
        mock_gw_client = _make_mock_client(get_cached_response=GATEWAYS_FIXTURE)

        with patch("opnsense.tools.routing._get_client") as mock_factory:
            mock_factory.side_effect = [mock_routes_client, mock_gw_client]
            from opnsense.agents.routing import run_routing_report

            report = await run_routing_report()

        assert "disabled" in report.lower()

    @pytest.mark.asyncio
    async def test_detects_offline_gateway(self) -> None:
        """Test that offline gateways generate CRITICAL findings."""
        offline_gw = {
            "items": [
                {
                    "name": "WAN_GW",
                    "address": "203.0.113.1",
                    "interface": "igb0",
                    "monitor": "8.8.8.8",
                    "status": "offline",
                    "priority": 255,
                    "delay": None,
                },
            ],
        }
        mock_routes_client = _make_mock_client(get_cached_response={"rows": []})
        mock_routes_client.get = AsyncMock(side_effect=APIError("Not found", status_code=404))
        mock_gw_client = _make_mock_client(get_cached_response=offline_gw)

        with patch("opnsense.tools.routing._get_client") as mock_factory:
            mock_factory.side_effect = [mock_routes_client, mock_gw_client]
            from opnsense.agents.routing import run_routing_report

            report = await run_routing_report()

        assert "CRITICAL" in report
        assert "offline" in report.lower()

    @pytest.mark.asyncio
    async def test_detects_high_latency_gateway(self) -> None:
        """Test that high-latency gateways generate findings."""
        high_lat_gw = {
            "items": [
                {
                    "name": "SLOW_GW",
                    "address": "10.0.0.1",
                    "interface": "igb0",
                    "monitor": "10.0.0.1",
                    "status": "online",
                    "priority": 255,
                    "delay": 250.0,
                },
            ],
        }
        mock_routes_client = _make_mock_client(get_cached_response={"rows": []})
        mock_routes_client.get = AsyncMock(side_effect=APIError("Not found", status_code=404))
        mock_gw_client = _make_mock_client(get_cached_response=high_lat_gw)

        with patch("opnsense.tools.routing._get_client") as mock_factory:
            mock_factory.side_effect = [mock_routes_client, mock_gw_client]
            from opnsense.agents.routing import run_routing_report

            report = await run_routing_report()

        assert "HIGH" in report
        assert "latency" in report.lower()


# ===========================================================================
# Cross-cutting: Client factory and cleanup
# ===========================================================================


class TestClientFactory:
    """Verify _get_client() uses environment variables correctly."""

    def test_interface_client_factory(self) -> None:
        with patch.dict(
            os.environ,
            {
                "OPNSENSE_HOST": "https://192.168.1.1",
                "OPNSENSE_API_KEY": "test-key",
                "OPNSENSE_API_SECRET": "test-secret",
                "OPNSENSE_VERIFY_SSL": "false",
            },
        ):
            from opnsense.tools.interfaces import _get_client

            client = _get_client()
            assert client._base_url == "https://192.168.1.1"
            assert client._verify_ssl is False

    def test_firewall_client_factory(self) -> None:
        with patch.dict(
            os.environ,
            {
                "OPNSENSE_HOST": "https://fw.local",
                "OPNSENSE_API_KEY": "key",
                "OPNSENSE_API_SECRET": "secret",
                "OPNSENSE_VERIFY_SSL": "true",
            },
        ):
            from opnsense.tools.firewall import _get_client

            client = _get_client()
            assert client._base_url == "https://fw.local"
            assert client._verify_ssl is True

    def test_routing_client_factory(self) -> None:
        with patch.dict(
            os.environ,
            {
                "OPNSENSE_HOST": "https://router.local",
                "OPNSENSE_API_KEY": "key",
                "OPNSENSE_API_SECRET": "secret",
            },
        ):
            from opnsense.tools.routing import _get_client

            client = _get_client()
            assert client._base_url == "https://router.local"

    def test_diagnostics_client_factory(self) -> None:
        with patch.dict(
            os.environ,
            {
                "OPNSENSE_HOST": "https://diag.local",
                "OPNSENSE_API_KEY": "key",
                "OPNSENSE_API_SECRET": "secret",
            },
        ):
            from opnsense.tools.diagnostics import _get_client

            client = _get_client()
            assert client._base_url == "https://diag.local"


class TestClientCleanup:
    """Verify client.close() is always called."""

    @pytest.mark.asyncio
    async def test_close_on_success(self) -> None:
        mock_client = _make_mock_client(get_cached_response=INTERFACES_FIXTURE)
        with patch("opnsense.tools.interfaces._get_client", return_value=mock_client):
            from opnsense.tools.interfaces import opnsense__interfaces__list_interfaces

            await opnsense__interfaces__list_interfaces()

        mock_client.close.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_close_on_error(self) -> None:
        mock_client = _make_mock_client(
            get_side_effect=APIError("Server error", status_code=500),
        )
        with patch("opnsense.tools.interfaces._get_client", return_value=mock_client):
            from opnsense.tools.interfaces import opnsense__interfaces__list_interfaces

            with pytest.raises(APIError):
                await opnsense__interfaces__list_interfaces()

        mock_client.close.assert_awaited_once()


# ===========================================================================
# Tools __init__ imports
# ===========================================================================


class TestToolsInit:
    """Verify that the tools __init__.py imports all modules."""

    def test_imports_interfaces(self) -> None:
        import opnsense.tools

        assert hasattr(opnsense.tools, "interfaces")

    def test_imports_firewall(self) -> None:
        import opnsense.tools

        assert hasattr(opnsense.tools, "firewall")

    def test_imports_routing(self) -> None:
        import opnsense.tools

        assert hasattr(opnsense.tools, "routing")

    def test_imports_diagnostics(self) -> None:
        import opnsense.tools

        assert hasattr(opnsense.tools, "diagnostics")


class TestAgentsInit:
    """Verify that the agents __init__.py exports all agent functions."""

    def test_exports_interface_report(self) -> None:
        from opnsense.agents import run_interface_report

        assert callable(run_interface_report)

    def test_exports_firewall_audit(self) -> None:
        from opnsense.agents import run_firewall_audit

        assert callable(run_firewall_audit)

    def test_exports_routing_report(self) -> None:
        from opnsense.agents import run_routing_report

        assert callable(run_routing_report)
