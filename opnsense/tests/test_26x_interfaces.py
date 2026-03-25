"""Tests for OPNsense 26.x interface listing via interfacesInfo endpoint.

Covers:
- Task 170: Fix list_interfaces to return logical interface names
- Parsing of the 26.x /api/interfaces/overview/interfacesInfo flat dict format
- Logical name, device name, description, IP, subnet, type, enabled, status
- Pseudo-interface filtering (config, nd6, etc.)
- VLAN tag extraction
- Interface model from_interfaces_info classmethod
- Edge cases: empty response, missing fields, disabled interfaces
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from opnsense.api.opnsense_client import OPNsenseClient
from opnsense.models.interface import interface_from_info
from tests.fixtures import load_fixture

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_mock_client(
    get_cached_response: dict[str, Any] | None = None,
) -> MagicMock:
    """Create a mock OPNsenseClient with configured responses."""
    client = MagicMock(spec=OPNsenseClient)
    client.close = AsyncMock()
    client.get_cached = AsyncMock(return_value=get_cached_response or {})
    return client


INTERFACES_INFO_26X = load_fixture("interfaces_info_26x.json")


# ===========================================================================
# Interface Model Tests
# ===========================================================================


class TestInterfaceModel:
    """interface_from_info() classmethod."""

    def test_from_interfaces_info_basic(self) -> None:
        data = {
            "device": "igb0",
            "description": "WAN",
            "identifier": "wan",
            "addr4": "203.0.113.42",
            "subnet4": "24",
            "type": "dhcp",
            "enabled": True,
            "status": "up",
            "vlan_tag": None,
        }
        iface = interface_from_info("wan", data)

        assert iface.name == "wan"
        assert iface.device == "igb0"
        assert iface.description == "WAN"
        assert iface.identifier == "wan"
        assert iface.ip == "203.0.113.42"
        assert iface.subnet == "24"
        assert iface.if_type == "dhcp"
        assert iface.enabled is True
        assert iface.status == "up"
        assert iface.vlan_id is None

    def test_from_interfaces_info_vlan(self) -> None:
        data = {
            "device": "igb1_vlan10",
            "description": "Guest",
            "identifier": "opt1",
            "addr4": "192.168.10.1",
            "subnet4": "24",
            "type": "static",
            "enabled": True,
            "status": "up",
            "vlan_tag": 10,
        }
        iface = interface_from_info("opt1", data)

        assert iface.name == "opt1"
        assert iface.device == "igb1_vlan10"
        assert iface.vlan_id == 10
        assert iface.if_type == "static"

    def test_from_interfaces_info_missing_fields(self) -> None:
        """Missing fields should fall back to defaults."""
        iface = interface_from_info("opt9", {})

        assert iface.name == "opt9"
        assert iface.device == ""
        assert iface.description == ""
        assert iface.identifier == "opt9"  # falls back to logical_name
        assert iface.ip == ""
        assert iface.subnet == ""
        assert iface.if_type == ""
        assert iface.enabled is True
        assert iface.status == ""
        assert iface.vlan_id is None

    def test_from_interfaces_info_disabled(self) -> None:
        data = {
            "device": "igb1_vlan50",
            "description": "Management",
            "identifier": "opt5",
            "addr4": "192.168.50.1",
            "subnet4": "24",
            "type": "static",
            "enabled": False,
            "status": "down",
            "vlan_tag": 50,
        }
        iface = interface_from_info("opt5", data)

        assert iface.enabled is False
        assert iface.status == "down"

    def test_model_dump_uses_python_names(self) -> None:
        """model_dump(by_alias=False) should use Python field names."""
        data = {
            "device": "igb0",
            "description": "WAN",
            "identifier": "wan",
            "addr4": "203.0.113.42",
            "subnet4": "24",
            "type": "dhcp",
            "enabled": True,
            "status": "up",
            "vlan_tag": None,
        }
        iface = interface_from_info("wan", data)
        dumped = iface.model_dump(by_alias=False)

        assert "name" in dumped
        assert "device" in dumped
        assert "ip" in dumped  # not "addr4"
        assert "subnet" in dumped  # not "subnet4"
        assert "if_type" in dumped  # not "type"
        assert "vlan_id" in dumped  # not "vlan_tag"
        assert "addr4" not in dumped
        assert "subnet4" not in dumped
        assert "vlan_tag" not in dumped


# ===========================================================================
# list_interfaces Tool Tests
# ===========================================================================


class TestListInterfaces26x:
    """opnsense__interfaces__list_interfaces() with 26.x interfacesInfo."""

    @pytest.mark.asyncio
    async def test_returns_all_interfaces(self) -> None:
        mock_client = _make_mock_client(get_cached_response=INTERFACES_INFO_26X)
        with patch("opnsense.tools.interfaces._get_client", return_value=mock_client):
            from opnsense.tools.interfaces import opnsense__interfaces__list_interfaces

            result = await opnsense__interfaces__list_interfaces()

        # Fixture has 9 interfaces (wan, lan, opt1-opt6, wan2)
        assert len(result) == 9

    @pytest.mark.asyncio
    async def test_logical_names_not_config(self) -> None:
        """Key fix: interfaces should have logical names, not 'config'."""
        mock_client = _make_mock_client(get_cached_response=INTERFACES_INFO_26X)
        with patch("opnsense.tools.interfaces._get_client", return_value=mock_client):
            from opnsense.tools.interfaces import opnsense__interfaces__list_interfaces

            result = await opnsense__interfaces__list_interfaces()

        names = [i["name"] for i in result]
        assert "config" not in names
        assert "wan" in names
        assert "lan" in names
        assert "opt1" in names

    @pytest.mark.asyncio
    async def test_interface_has_all_expected_fields(self) -> None:
        mock_client = _make_mock_client(get_cached_response=INTERFACES_INFO_26X)
        with patch("opnsense.tools.interfaces._get_client", return_value=mock_client):
            from opnsense.tools.interfaces import opnsense__interfaces__list_interfaces

            result = await opnsense__interfaces__list_interfaces()

        wan = next(i for i in result if i["name"] == "wan")
        assert wan["device"] == "igb0"
        assert wan["description"] == "WAN"
        assert wan["identifier"] == "wan"
        assert wan["ip"] == "203.0.113.42"
        assert wan["subnet"] == "24"
        assert wan["if_type"] == "dhcp"
        assert wan["enabled"] is True
        assert wan["status"] == "up"
        assert wan["vlan_id"] is None

    @pytest.mark.asyncio
    async def test_device_names_are_physical(self) -> None:
        """Device field should contain physical device names."""
        mock_client = _make_mock_client(get_cached_response=INTERFACES_INFO_26X)
        with patch("opnsense.tools.interfaces._get_client", return_value=mock_client):
            from opnsense.tools.interfaces import opnsense__interfaces__list_interfaces

            result = await opnsense__interfaces__list_interfaces()

        wan = next(i for i in result if i["name"] == "wan")
        lan = next(i for i in result if i["name"] == "lan")
        opt1 = next(i for i in result if i["name"] == "opt1")

        assert wan["device"] == "igb0"
        assert lan["device"] == "igb1"
        assert opt1["device"] == "igb1_vlan10"

    @pytest.mark.asyncio
    async def test_vlan_interface_has_vlan_id(self) -> None:
        mock_client = _make_mock_client(get_cached_response=INTERFACES_INFO_26X)
        with patch("opnsense.tools.interfaces._get_client", return_value=mock_client):
            from opnsense.tools.interfaces import opnsense__interfaces__list_interfaces

            result = await opnsense__interfaces__list_interfaces()

        guest = next(i for i in result if i["name"] == "opt1")
        assert guest["vlan_id"] == 10
        assert guest["description"] == "Guest"

        iot = next(i for i in result if i["name"] == "opt2")
        assert iot["vlan_id"] == 30
        assert iot["description"] == "IoT"

    @pytest.mark.asyncio
    async def test_non_vlan_has_no_vlan_id(self) -> None:
        mock_client = _make_mock_client(get_cached_response=INTERFACES_INFO_26X)
        with patch("opnsense.tools.interfaces._get_client", return_value=mock_client):
            from opnsense.tools.interfaces import opnsense__interfaces__list_interfaces

            result = await opnsense__interfaces__list_interfaces()

        wan = next(i for i in result if i["name"] == "wan")
        assert wan["vlan_id"] is None

    @pytest.mark.asyncio
    async def test_disabled_interface_included(self) -> None:
        """Disabled interfaces should still be listed (enabled=False)."""
        mock_client = _make_mock_client(get_cached_response=INTERFACES_INFO_26X)
        with patch("opnsense.tools.interfaces._get_client", return_value=mock_client):
            from opnsense.tools.interfaces import opnsense__interfaces__list_interfaces

            result = await opnsense__interfaces__list_interfaces()

        mgmt = next(i for i in result if i["name"] == "opt5")
        assert mgmt["enabled"] is False
        assert mgmt["status"] == "down"
        assert mgmt["description"] == "Management"

    @pytest.mark.asyncio
    async def test_interface_without_ip(self) -> None:
        """Interfaces with no IP assigned should have empty string for ip/subnet."""
        mock_client = _make_mock_client(get_cached_response=INTERFACES_INFO_26X)
        with patch("opnsense.tools.interfaces._get_client", return_value=mock_client):
            from opnsense.tools.interfaces import opnsense__interfaces__list_interfaces

            result = await opnsense__interfaces__list_interfaces()

        no_ip = next(i for i in result if i["name"] == "opt6")
        assert no_ip["ip"] == ""
        assert no_ip["subnet"] == ""
        assert no_ip["vlan_id"] == 99

    @pytest.mark.asyncio
    async def test_uses_correct_endpoint(self) -> None:
        mock_client = _make_mock_client(get_cached_response=INTERFACES_INFO_26X)
        with patch("opnsense.tools.interfaces._get_client", return_value=mock_client):
            from opnsense.tools.interfaces import opnsense__interfaces__list_interfaces

            await opnsense__interfaces__list_interfaces()

        mock_client.get_cached.assert_awaited_once()
        call_args = mock_client.get_cached.call_args
        assert call_args[0] == ("interfaces", "overview", "interfacesInfo")
        assert call_args[1]["cache_key"] == "interfaces:list"

    @pytest.mark.asyncio
    async def test_empty_response(self) -> None:
        mock_client = _make_mock_client(get_cached_response={})
        with patch("opnsense.tools.interfaces._get_client", return_value=mock_client):
            from opnsense.tools.interfaces import opnsense__interfaces__list_interfaces

            result = await opnsense__interfaces__list_interfaces()

        assert result == []

    @pytest.mark.asyncio
    async def test_pseudo_interfaces_filtered(self) -> None:
        """Pseudo-interfaces like 'config', 'nd6' should be filtered out."""
        data_with_pseudo = {
            "wan": {
                "device": "igb0",
                "description": "WAN",
                "identifier": "wan",
                "addr4": "1.2.3.4",
                "subnet4": "24",
                "type": "dhcp",
                "enabled": True,
                "status": "up",
                "vlan_tag": None,
            },
            "config": {
                "device": "config",
                "description": "",
                "identifier": "",
                "addr4": "",
                "subnet4": "",
                "type": "",
                "enabled": False,
                "status": "",
                "vlan_tag": None,
            },
            "nd6": {
                "device": "nd6",
                "description": "",
                "identifier": "",
                "addr4": "",
                "subnet4": "",
                "type": "",
                "enabled": False,
                "status": "",
                "vlan_tag": None,
            },
            "lo0": {
                "device": "lo0",
                "description": "Loopback",
                "identifier": "",
                "addr4": "127.0.0.1",
                "subnet4": "8",
                "type": "static",
                "enabled": True,
                "status": "up",
                "vlan_tag": None,
            },
            "pflog0": {
                "device": "pflog0",
                "description": "",
                "identifier": "",
                "addr4": "",
                "subnet4": "",
                "type": "",
                "enabled": True,
                "status": "up",
                "vlan_tag": None,
            },
        }

        mock_client = _make_mock_client(get_cached_response=data_with_pseudo)
        with patch("opnsense.tools.interfaces._get_client", return_value=mock_client):
            from opnsense.tools.interfaces import opnsense__interfaces__list_interfaces

            result = await opnsense__interfaces__list_interfaces()

        names = [i["name"] for i in result]
        assert names == ["wan"]
        assert "config" not in names
        assert "nd6" not in names
        assert "lo0" not in names
        assert "pflog0" not in names

    @pytest.mark.asyncio
    async def test_internal_metadata_keys_skipped(self) -> None:
        """Keys starting with '_' (client metadata) should be ignored."""
        data = {
            "_was_array": True,
            "wan": {
                "device": "igb0",
                "description": "WAN",
                "identifier": "wan",
                "addr4": "1.2.3.4",
                "subnet4": "24",
                "type": "dhcp",
                "enabled": True,
                "status": "up",
                "vlan_tag": None,
            },
        }
        mock_client = _make_mock_client(get_cached_response=data)
        with patch("opnsense.tools.interfaces._get_client", return_value=mock_client):
            from opnsense.tools.interfaces import opnsense__interfaces__list_interfaces

            result = await opnsense__interfaces__list_interfaces()

        assert len(result) == 1
        assert result[0]["name"] == "wan"

    @pytest.mark.asyncio
    async def test_unparseable_entry_skipped_gracefully(self) -> None:
        """Entries that fail validation are skipped with a warning."""
        data = {
            "wan": {
                "device": "igb0",
                "description": "WAN",
                "identifier": "wan",
                "addr4": "1.2.3.4",
                "subnet4": "24",
                "type": "dhcp",
                "enabled": True,
                "status": "up",
                "vlan_tag": None,
            },
            "bad_entry": "not a dict",
        }
        mock_client = _make_mock_client(get_cached_response=data)
        with patch("opnsense.tools.interfaces._get_client", return_value=mock_client):
            from opnsense.tools.interfaces import opnsense__interfaces__list_interfaces

            result = await opnsense__interfaces__list_interfaces()

        assert len(result) == 1
        assert result[0]["name"] == "wan"

    @pytest.mark.asyncio
    async def test_client_closed_on_success(self) -> None:
        mock_client = _make_mock_client(get_cached_response=INTERFACES_INFO_26X)
        with patch("opnsense.tools.interfaces._get_client", return_value=mock_client):
            from opnsense.tools.interfaces import opnsense__interfaces__list_interfaces

            await opnsense__interfaces__list_interfaces()

        mock_client.close.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_client_closed_on_error(self) -> None:
        mock_client = _make_mock_client()
        mock_client.get_cached = AsyncMock(side_effect=RuntimeError("connection failed"))
        with patch("opnsense.tools.interfaces._get_client", return_value=mock_client):
            from opnsense.tools.interfaces import opnsense__interfaces__list_interfaces

            with pytest.raises(RuntimeError, match="connection failed"):
                await opnsense__interfaces__list_interfaces()

        mock_client.close.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_wan2_failover_interface(self) -> None:
        """Multi-WAN failover interfaces should be listed correctly."""
        mock_client = _make_mock_client(get_cached_response=INTERFACES_INFO_26X)
        with patch("opnsense.tools.interfaces._get_client", return_value=mock_client):
            from opnsense.tools.interfaces import opnsense__interfaces__list_interfaces

            result = await opnsense__interfaces__list_interfaces()

        wan2 = next(i for i in result if i["name"] == "wan2")
        assert wan2["device"] == "igb3"
        assert wan2["description"] == "WAN2 (Failover)"
        assert wan2["ip"] == "198.51.100.10"
        assert wan2["if_type"] == "dhcp"


# ===========================================================================
# Return Format Backward Compatibility
# ===========================================================================


class TestReturnFormatCompat:
    """Verify the return format has no breaking changes (additive OK)."""

    @pytest.mark.asyncio
    async def test_all_original_fields_present(self) -> None:
        """The original fields (name, description, identifier, ip, subnet,
        if_type, enabled, status, vlan_id) must still be present."""
        mock_client = _make_mock_client(get_cached_response=INTERFACES_INFO_26X)
        with patch("opnsense.tools.interfaces._get_client", return_value=mock_client):
            from opnsense.tools.interfaces import opnsense__interfaces__list_interfaces

            result = await opnsense__interfaces__list_interfaces()

        assert len(result) > 0
        for iface in result:
            # Original fields
            assert "name" in iface
            assert "description" in iface
            assert "identifier" in iface
            assert "ip" in iface
            assert "subnet" in iface
            assert "if_type" in iface
            assert "enabled" in iface
            assert "status" in iface
            assert "vlan_id" in iface
            # New additive field
            assert "device" in iface

    @pytest.mark.asyncio
    async def test_name_is_logical_not_device(self) -> None:
        """The 'name' field should now be the logical name, not the device."""
        mock_client = _make_mock_client(get_cached_response=INTERFACES_INFO_26X)
        with patch("opnsense.tools.interfaces._get_client", return_value=mock_client):
            from opnsense.tools.interfaces import opnsense__interfaces__list_interfaces

            result = await opnsense__interfaces__list_interfaces()

        names = {i["name"] for i in result}
        # Logical names
        assert "wan" in names
        assert "lan" in names
        # Physical device names should NOT be in name field
        devices = {i["device"] for i in result}
        assert "igb0" in devices
        assert "igb0" not in names
