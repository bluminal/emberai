"""Tests for gateway group tools and policy-based routing (gateway on firewall rules).

Covers:
- Gateway group listing (opnsense__routing__list_gateway_groups)
- Gateway group creation (opnsense__routing__add_gateway_group)
- Firewall rule creation with gateway assignment
- GatewayGroup/GatewayGroupMember model parsing
- Write gate enforcement for gateway group creation

Test strategy:
- Mock the OPNsenseClient at the _get_client() level
- Use inline fixtures for gateway group API responses
- Verify write gate enforcement for write tools
- Verify validation errors for invalid input
"""

from __future__ import annotations

import json
import os
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from opnsense.api.opnsense_client import OPNsenseClient
from opnsense.errors import ValidationError, WriteGateError
from opnsense.models.routing import GatewayGroup, GatewayGroupMember

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_mock_client(
    get_response: dict[str, Any] | None = None,
    get_cached_response: dict[str, Any] | None = None,
    write_response: dict[str, Any] | None = None,
    reconfigure_response: dict[str, Any] | None = None,
) -> MagicMock:
    """Create a mock OPNsenseClient with configured responses."""
    client = MagicMock(spec=OPNsenseClient)
    client.close = AsyncMock()
    client.get = AsyncMock(return_value=get_response or {})
    client.get_cached = AsyncMock(return_value=get_cached_response or get_response or {})
    client.write = AsyncMock(
        return_value=write_response or {"result": "saved", "uuid": "new-uuid-123"},
    )
    client.reconfigure = AsyncMock(return_value=reconfigure_response or {"status": "ok"})
    return client


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

GATEWAY_GROUPS_RESPONSE: dict[str, Any] = {
    "rows": [
        {
            "uuid": "gw-group-001",
            "name": "WAN1_Failover",
            "trigger": "down",
            "members": [
                {"gateway": "WAN_DHCP", "tier": 1, "weight": 1},
                {"gateway": "WAN2_DHCP", "tier": 2, "weight": 1},
            ],
        },
        {
            "uuid": "gw-group-002",
            "name": "WAN2_Failover",
            "trigger": "down",
            "members": [
                {"gateway": "WAN2_DHCP", "tier": 1, "weight": 1},
                {"gateway": "WAN_DHCP", "tier": 2, "weight": 1},
            ],
        },
    ],
    "rowCount": 2,
    "total": 2,
    "current": 1,
}

GATEWAY_GROUPS_SEMICOLON_FORMAT: dict[str, Any] = {
    "rows": [
        {
            "uuid": "gw-group-003",
            "name": "LoadBalance",
            "trigger": "packet_loss",
            "members": "WAN_DHCP|1|3;WAN2_DHCP|1|1",
        },
    ],
    "rowCount": 1,
    "total": 1,
    "current": 1,
}

FIREWALL_RULES_WITH_GATEWAY: dict[str, Any] = {
    "rows": [
        {
            "uuid": "rule-gw-001",
            "description": "IoT internet via WAN2",
            "action": "pass",
            "enabled": "1",
            "direction": "in",
            "ipprotocol": "inet",
            "source_net": "opt7",
            "destination_net": "any",
            "log": "0",
            "sequence": "1600",
            "interface": "opt7",
            "gateway": "WAN2_Failover",
        },
        {
            "uuid": "rule-gw-002",
            "description": "Trusted internet via WAN1",
            "action": "pass",
            "enabled": "1",
            "direction": "in",
            "ipprotocol": "inet",
            "source_net": "opt4",
            "destination_net": "any",
            "log": "0",
            "sequence": "900",
            "interface": "opt4",
            "gateway": "",
        },
    ],
    "rowCount": 2,
    "total": 2,
    "current": 1,
}


# ===========================================================================
# Model tests
# ===========================================================================


class TestGatewayGroupMemberModel:
    """GatewayGroupMember Pydantic model."""

    def test_basic_member(self) -> None:
        member = GatewayGroupMember(gateway="WAN_DHCP", tier=1, weight=1)
        assert member.gateway == "WAN_DHCP"
        assert member.tier == 1
        assert member.weight == 1

    def test_defaults(self) -> None:
        member = GatewayGroupMember(gateway="WAN_DHCP")
        assert member.tier == 1
        assert member.weight == 1

    def test_failover_tier(self) -> None:
        member = GatewayGroupMember(gateway="WAN2_DHCP", tier=2, weight=1)
        assert member.tier == 2


class TestGatewayGroupModel:
    """GatewayGroup Pydantic model."""

    def test_basic_group(self) -> None:
        group = GatewayGroup(
            uuid="test-uuid",
            name="WAN1_Failover",
            trigger="down",
            members=[
                GatewayGroupMember(gateway="WAN_DHCP", tier=1, weight=1),
                GatewayGroupMember(gateway="WAN2_DHCP", tier=2, weight=1),
            ],
        )
        assert group.name == "WAN1_Failover"
        assert group.trigger == "down"
        assert len(group.members) == 2
        assert group.members[0].gateway == "WAN_DHCP"
        assert group.members[1].tier == 2

    def test_defaults(self) -> None:
        group = GatewayGroup(uuid="test", name="TestGroup")
        assert group.trigger == "down"
        assert group.members == []


# ===========================================================================
# Gateway group read tool tests
# ===========================================================================


class TestListGatewayGroups:
    """opnsense__routing__list_gateway_groups()"""

    @pytest.mark.asyncio
    async def test_returns_all_groups(self) -> None:
        mock_client = _make_mock_client(get_cached_response=GATEWAY_GROUPS_RESPONSE)
        with patch("opnsense.tools.routing._get_client", return_value=mock_client):
            from opnsense.tools.routing import opnsense__routing__list_gateway_groups

            result = await opnsense__routing__list_gateway_groups()

        assert len(result) == 2
        assert result[0]["name"] == "WAN1_Failover"
        assert result[1]["name"] == "WAN2_Failover"

    @pytest.mark.asyncio
    async def test_group_has_members(self) -> None:
        mock_client = _make_mock_client(get_cached_response=GATEWAY_GROUPS_RESPONSE)
        with patch("opnsense.tools.routing._get_client", return_value=mock_client):
            from opnsense.tools.routing import opnsense__routing__list_gateway_groups

            result = await opnsense__routing__list_gateway_groups()

        group = result[0]
        assert len(group["members"]) == 2
        assert group["members"][0]["gateway"] == "WAN_DHCP"
        assert group["members"][0]["tier"] == 1
        assert group["members"][1]["gateway"] == "WAN2_DHCP"
        assert group["members"][1]["tier"] == 2

    @pytest.mark.asyncio
    async def test_semicolon_format_members(self) -> None:
        mock_client = _make_mock_client(get_cached_response=GATEWAY_GROUPS_SEMICOLON_FORMAT)
        with patch("opnsense.tools.routing._get_client", return_value=mock_client):
            from opnsense.tools.routing import opnsense__routing__list_gateway_groups

            result = await opnsense__routing__list_gateway_groups()

        assert len(result) == 1
        group = result[0]
        assert group["name"] == "LoadBalance"
        assert group["trigger"] == "packet_loss"
        assert len(group["members"]) == 2
        assert group["members"][0]["gateway"] == "WAN_DHCP"
        assert group["members"][0]["weight"] == 3
        assert group["members"][1]["gateway"] == "WAN2_DHCP"

    @pytest.mark.asyncio
    async def test_empty_response(self) -> None:
        mock_client = _make_mock_client(
            get_cached_response={"rows": [], "rowCount": 0, "total": 0, "current": 1},
        )
        with patch("opnsense.tools.routing._get_client", return_value=mock_client):
            from opnsense.tools.routing import opnsense__routing__list_gateway_groups

            result = await opnsense__routing__list_gateway_groups()

        assert result == []


# ===========================================================================
# Gateway group write tool tests
# ===========================================================================


class TestAddGatewayGroup:
    """opnsense__routing__add_gateway_group()"""

    @pytest.mark.asyncio
    async def test_write_gate_blocks_without_env(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            from opnsense.tools.routing import opnsense__routing__add_gateway_group

            with pytest.raises(WriteGateError):
                await opnsense__routing__add_gateway_group(
                    name="Test",
                    members='[{"gateway": "WAN_DHCP", "tier": 1, "weight": 1}]',
                    apply=True,
                )

    @pytest.mark.asyncio
    async def test_empty_name_rejected(self) -> None:
        mock_client = _make_mock_client()
        with (
            patch.dict(os.environ, {"OPNSENSE_WRITE_ENABLED": "true"}),
            patch("opnsense.tools.routing._get_client", return_value=mock_client),
        ):
            from opnsense.tools.routing import opnsense__routing__add_gateway_group

            with pytest.raises(ValidationError, match="name"):
                await opnsense__routing__add_gateway_group(
                    name="",
                    members='[{"gateway": "WAN_DHCP", "tier": 1, "weight": 1}]',
                    apply=True,
                )

    @pytest.mark.asyncio
    async def test_invalid_trigger_rejected(self) -> None:
        mock_client = _make_mock_client()
        with (
            patch.dict(os.environ, {"OPNSENSE_WRITE_ENABLED": "true"}),
            patch("opnsense.tools.routing._get_client", return_value=mock_client),
        ):
            from opnsense.tools.routing import opnsense__routing__add_gateway_group

            with pytest.raises(ValidationError, match="Trigger"):
                await opnsense__routing__add_gateway_group(
                    name="Test",
                    members='[{"gateway": "WAN_DHCP", "tier": 1, "weight": 1}]',
                    trigger="invalid",
                    apply=True,
                )

    @pytest.mark.asyncio
    async def test_invalid_json_members_rejected(self) -> None:
        mock_client = _make_mock_client()
        with (
            patch.dict(os.environ, {"OPNSENSE_WRITE_ENABLED": "true"}),
            patch("opnsense.tools.routing._get_client", return_value=mock_client),
        ):
            from opnsense.tools.routing import opnsense__routing__add_gateway_group

            with pytest.raises(ValidationError, match="JSON"):
                await opnsense__routing__add_gateway_group(
                    name="Test",
                    members="not json",
                    apply=True,
                )

    @pytest.mark.asyncio
    async def test_empty_members_rejected(self) -> None:
        mock_client = _make_mock_client()
        with (
            patch.dict(os.environ, {"OPNSENSE_WRITE_ENABLED": "true"}),
            patch("opnsense.tools.routing._get_client", return_value=mock_client),
        ):
            from opnsense.tools.routing import opnsense__routing__add_gateway_group

            with pytest.raises(ValidationError, match="non-empty"):
                await opnsense__routing__add_gateway_group(
                    name="Test",
                    members="[]",
                    apply=True,
                )

    @pytest.mark.asyncio
    async def test_member_missing_gateway_rejected(self) -> None:
        mock_client = _make_mock_client()
        with (
            patch.dict(os.environ, {"OPNSENSE_WRITE_ENABLED": "true"}),
            patch("opnsense.tools.routing._get_client", return_value=mock_client),
        ):
            from opnsense.tools.routing import opnsense__routing__add_gateway_group

            with pytest.raises(ValidationError, match="gateway"):
                await opnsense__routing__add_gateway_group(
                    name="Test",
                    members='[{"tier": 1, "weight": 1}]',
                    apply=True,
                )

    @pytest.mark.asyncio
    async def test_successful_creation(self) -> None:
        mock_client = _make_mock_client()
        with (
            patch.dict(os.environ, {"OPNSENSE_WRITE_ENABLED": "true"}),
            patch("opnsense.tools.routing._get_client", return_value=mock_client),
        ):
            from opnsense.tools.routing import opnsense__routing__add_gateway_group

            members = json.dumps([
                {"gateway": "WAN_DHCP", "tier": 1, "weight": 1},
                {"gateway": "WAN2_DHCP", "tier": 2, "weight": 1},
            ])
            result = await opnsense__routing__add_gateway_group(
                name="WAN1_Failover",
                members=members,
                trigger="down",
                apply=True,
            )

        assert result["status"] == "created"
        assert result["name"] == "WAN1_Failover"
        assert result["trigger"] == "down"
        assert len(result["members"]) == 2
        mock_client.write.assert_awaited_once()
        mock_client.reconfigure.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_payload_format(self) -> None:
        """Verify the API payload includes gateway members in OPNsense format."""
        mock_client = _make_mock_client()
        with (
            patch.dict(os.environ, {"OPNSENSE_WRITE_ENABLED": "true"}),
            patch("opnsense.tools.routing._get_client", return_value=mock_client),
        ):
            from opnsense.tools.routing import opnsense__routing__add_gateway_group

            members = json.dumps([
                {"gateway": "WAN_DHCP", "tier": 1, "weight": 1},
                {"gateway": "WAN2_DHCP", "tier": 2, "weight": 1},
            ])
            await opnsense__routing__add_gateway_group(
                name="WAN1_Failover",
                members=members,
                apply=True,
            )

        write_data = mock_client.write.call_args.kwargs["data"]
        assert write_data["group"]["name"] == "WAN1_Failover"
        assert write_data["group"]["trigger"] == "down"
        assert write_data["group"]["WAN_DHCP"] == "1|1"
        assert write_data["group"]["WAN2_DHCP"] == "2|1"


# ===========================================================================
# Firewall rule with gateway tests
# ===========================================================================


class TestAddRuleWithGateway:
    """opnsense__firewall__add_rule() with gateway parameter."""

    @pytest.mark.asyncio
    async def test_pass_rule_with_gateway(self) -> None:
        mock_client = _make_mock_client()
        mock_client.post = AsyncMock(
            side_effect=[
                {"revision": "abc123"},
                {"status": "ok"},
                {"status": "ok"},
            ],
        )
        with (
            patch.dict(os.environ, {"OPNSENSE_WRITE_ENABLED": "true"}),
            patch("opnsense.tools.firewall._get_client", return_value=mock_client),
        ):
            from opnsense.tools.firewall import opnsense__firewall__add_rule

            result = await opnsense__firewall__add_rule(
                interface="opt7",
                action="pass",
                src="opt7",
                dst="any",
                description="IoT internet via WAN2",
                gateway="WAN2_Failover",
                apply=True,
            )

        assert result["status"] == "created"
        assert result["gateway"] == "WAN2_Failover"
        write_data = mock_client.write.call_args.kwargs["data"]
        assert write_data["rule"]["gateway"] == "WAN2_Failover"

    @pytest.mark.asyncio
    async def test_block_rule_with_gateway_rejected(self) -> None:
        mock_client = _make_mock_client()
        with (
            patch.dict(os.environ, {"OPNSENSE_WRITE_ENABLED": "true"}),
            patch("opnsense.tools.firewall._get_client", return_value=mock_client),
        ):
            from opnsense.tools.firewall import opnsense__firewall__add_rule

            with pytest.raises(ValidationError, match="pass"):
                await opnsense__firewall__add_rule(
                    interface="opt7",
                    action="block",
                    src="opt7",
                    dst="RFC1918",
                    gateway="WAN2_Failover",
                    apply=True,
                )

    @pytest.mark.asyncio
    async def test_empty_gateway_not_included(self) -> None:
        mock_client = _make_mock_client()
        mock_client.post = AsyncMock(
            side_effect=[
                {"revision": "abc123"},
                {"status": "ok"},
                {"status": "ok"},
            ],
        )
        with (
            patch.dict(os.environ, {"OPNSENSE_WRITE_ENABLED": "true"}),
            patch("opnsense.tools.firewall._get_client", return_value=mock_client),
        ):
            from opnsense.tools.firewall import opnsense__firewall__add_rule

            result = await opnsense__firewall__add_rule(
                interface="opt4",
                action="pass",
                src="opt4",
                dst="any",
                apply=True,
            )

        assert "gateway" not in result
        write_data = mock_client.write.call_args.kwargs["data"]
        assert "gateway" not in write_data["rule"]


class TestAddRuleWithDstPort:
    """opnsense__firewall__add_rule() with dst_port parameter."""

    @pytest.mark.asyncio
    async def test_rule_with_dst_port(self) -> None:
        mock_client = _make_mock_client()
        mock_client.post = AsyncMock(
            side_effect=[
                {"revision": "abc123"},
                {"status": "ok"},
                {"status": "ok"},
            ],
        )
        with (
            patch.dict(os.environ, {"OPNSENSE_WRITE_ENABLED": "true"}),
            patch("opnsense.tools.firewall._get_client", return_value=mock_client),
        ):
            from opnsense.tools.firewall import opnsense__firewall__add_rule

            result = await opnsense__firewall__add_rule(
                interface="opt11",
                action="pass",
                src="opt11",
                dst="any",
                protocol="TCP",
                dst_port="Jailed_Allowed_Ports",
                description="Jailed HTTP/HTTPS only",
                apply=True,
            )

        assert result["status"] == "created"
        assert result["dst_port"] == "Jailed_Allowed_Ports"
        write_data = mock_client.write.call_args.kwargs["data"]
        assert write_data["rule"]["destination_port"] == "Jailed_Allowed_Ports"

    @pytest.mark.asyncio
    async def test_rule_with_numeric_port(self) -> None:
        mock_client = _make_mock_client()
        mock_client.post = AsyncMock(
            side_effect=[
                {"revision": "abc123"},
                {"status": "ok"},
                {"status": "ok"},
            ],
        )
        with (
            patch.dict(os.environ, {"OPNSENSE_WRITE_ENABLED": "true"}),
            patch("opnsense.tools.firewall._get_client", return_value=mock_client),
        ):
            from opnsense.tools.firewall import opnsense__firewall__add_rule

            result = await opnsense__firewall__add_rule(
                interface="lan",
                action="pass",
                src="lan",
                dst="any",
                protocol="TCP",
                dst_port="443",
                apply=True,
            )

        assert result["dst_port"] == "443"
        write_data = mock_client.write.call_args.kwargs["data"]
        assert write_data["rule"]["destination_port"] == "443"

    @pytest.mark.asyncio
    async def test_empty_port_not_included(self) -> None:
        mock_client = _make_mock_client()
        mock_client.post = AsyncMock(
            side_effect=[
                {"revision": "abc123"},
                {"status": "ok"},
                {"status": "ok"},
            ],
        )
        with (
            patch.dict(os.environ, {"OPNSENSE_WRITE_ENABLED": "true"}),
            patch("opnsense.tools.firewall._get_client", return_value=mock_client),
        ):
            from opnsense.tools.firewall import opnsense__firewall__add_rule

            result = await opnsense__firewall__add_rule(
                interface="lan",
                action="pass",
                src="lan",
                dst="any",
                apply=True,
            )

        assert "dst_port" not in result
        write_data = mock_client.write.call_args.kwargs["data"]
        assert "destination_port" not in write_data["rule"]


class TestFirewallRuleGatewayField:
    """FirewallRule model gateway field in list_rules output."""

    @pytest.mark.asyncio
    async def test_rules_include_gateway(self) -> None:
        mock_client = _make_mock_client(
            get_cached_response=FIREWALL_RULES_WITH_GATEWAY,
        )
        with patch("opnsense.tools.firewall._get_client", return_value=mock_client):
            from opnsense.tools.firewall import opnsense__firewall__list_rules

            result = await opnsense__firewall__list_rules()

        assert len(result) == 2
        assert result[0]["gateway"] == "WAN2_Failover"
        assert result[1]["gateway"] == ""
