"""Tests for VPN skill tools.

Covers:
- list_ipsec_sessions: fixture parsing, model normalization
- list_openvpn_instances: fixture parsing
- list_wireguard_peers: fixture parsing, active/inactive detection
- get_vpn_status: aggregation, summary counts, edge cases
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from tests.fixtures import load_fixture


# ---------------------------------------------------------------------------
# Helpers -- mock client
# ---------------------------------------------------------------------------


def _make_client(get_returns: dict[str, Any] | None = None) -> AsyncMock:
    """Create a mock OPNsenseClient with configurable GET responses."""
    client = AsyncMock()
    if get_returns is not None:
        client.get = AsyncMock(return_value=get_returns)
    return client


def _make_client_multi(responses: dict[tuple[str, str, str], dict[str, Any]]) -> AsyncMock:
    """Create a mock client with per-endpoint responses."""
    client = AsyncMock()

    async def _get(module: str, controller: str, command: str, **kwargs: Any) -> dict[str, Any]:
        key = (module, controller, command)
        if key in responses:
            return responses[key]
        return {"rows": []}

    client.get = AsyncMock(side_effect=_get)
    return client


# ---------------------------------------------------------------------------
# list_ipsec_sessions
# ---------------------------------------------------------------------------


class TestListIPSecSessions:
    @pytest.mark.asyncio
    async def test_returns_parsed_sessions(self) -> None:
        from opnsense.tools.vpn import opnsense__vpn__list_ipsec_sessions

        fixture = load_fixture("ipsec_sessions.json")
        client = _make_client(fixture)

        sessions = await opnsense__vpn__list_ipsec_sessions(client)

        assert len(sessions) == 2
        client.get.assert_called_once_with("ipsec", "sessions", "search")

    @pytest.mark.asyncio
    async def test_normalizes_field_names(self) -> None:
        from opnsense.tools.vpn import opnsense__vpn__list_ipsec_sessions

        fixture = load_fixture("ipsec_sessions.json")
        client = _make_client(fixture)

        sessions = await opnsense__vpn__list_ipsec_sessions(client)

        connected = sessions[0]
        assert connected["session_id"] == "con-branch01"
        assert connected["status"] == "connected"
        assert connected["local_ts"] == "192.168.1.0/24"
        assert connected["remote_ts"] == "10.10.0.0/24"
        assert connected["rx_bytes"] == 154832640
        assert connected["tx_bytes"] == 87293440

    @pytest.mark.asyncio
    async def test_handles_disconnected_session(self) -> None:
        from opnsense.tools.vpn import opnsense__vpn__list_ipsec_sessions

        fixture = load_fixture("ipsec_sessions.json")
        client = _make_client(fixture)

        sessions = await opnsense__vpn__list_ipsec_sessions(client)

        disconnected = sessions[1]
        assert disconnected["status"] == "disconnected"
        assert disconnected["rx_bytes"] == 0
        assert disconnected["established_at"] is None

    @pytest.mark.asyncio
    async def test_empty_response(self) -> None:
        from opnsense.tools.vpn import opnsense__vpn__list_ipsec_sessions

        client = _make_client({"rows": []})
        sessions = await opnsense__vpn__list_ipsec_sessions(client)
        assert sessions == []


# ---------------------------------------------------------------------------
# list_openvpn_instances
# ---------------------------------------------------------------------------


class TestListOpenVPNInstances:
    @pytest.mark.asyncio
    async def test_returns_parsed_instances(self) -> None:
        from opnsense.tools.vpn import opnsense__vpn__list_openvpn_instances

        data = {
            "rows": [
                {
                    "uuid": "ovpn-1",
                    "description": "Road Warrior",
                    "role": "server",
                    "proto": "udp",
                    "port": 1194,
                    "enabled": True,
                    "clients": 3,
                    "dev_type": "tun",
                },
            ],
        }
        client = _make_client(data)
        instances = await opnsense__vpn__list_openvpn_instances(client)

        assert len(instances) == 1
        assert instances[0]["role"] == "server"
        assert instances[0]["protocol"] == "udp"
        assert instances[0]["connected_clients"] == 3

    @pytest.mark.asyncio
    async def test_empty_response(self) -> None:
        from opnsense.tools.vpn import opnsense__vpn__list_openvpn_instances

        client = _make_client({"rows": []})
        instances = await opnsense__vpn__list_openvpn_instances(client)
        assert instances == []


# ---------------------------------------------------------------------------
# list_wireguard_peers
# ---------------------------------------------------------------------------


class TestListWireGuardPeers:
    @pytest.mark.asyncio
    async def test_returns_parsed_peers(self) -> None:
        from opnsense.tools.vpn import opnsense__vpn__list_wireguard_peers

        fixture = load_fixture("wireguard_peers.json")
        client = _make_client(fixture)

        peers = await opnsense__vpn__list_wireguard_peers(client)

        assert len(peers) == 3
        client.get.assert_called_once_with("wireguard", "client", "search")

    @pytest.mark.asyncio
    async def test_normalizes_field_names(self) -> None:
        from opnsense.tools.vpn import opnsense__vpn__list_wireguard_peers

        fixture = load_fixture("wireguard_peers.json")
        client = _make_client(fixture)

        peers = await opnsense__vpn__list_wireguard_peers(client)

        active_peer = peers[0]
        assert active_peer["name"] == "mobile-laptop"
        assert active_peer["public_key"] == "xTIB+aR2WyIMAoPXhGfmPmU7cHNMf7j+9h7Kpvsgv2o="
        assert active_peer["allowed_ips"] == "10.99.0.2/32"
        assert active_peer["last_handshake"] == "2026-03-19T14:32:10Z"

    @pytest.mark.asyncio
    async def test_inactive_peer_has_null_fields(self) -> None:
        from opnsense.tools.vpn import opnsense__vpn__list_wireguard_peers

        fixture = load_fixture("wireguard_peers.json")
        client = _make_client(fixture)

        peers = await opnsense__vpn__list_wireguard_peers(client)

        inactive = peers[1]
        assert inactive["name"] == "remote-office"
        assert inactive["endpoint"] is None
        assert inactive["last_handshake"] is None
        assert inactive["rx_bytes"] == 0


# ---------------------------------------------------------------------------
# get_vpn_status (aggregation)
# ---------------------------------------------------------------------------


class TestGetVPNStatus:
    @pytest.mark.asyncio
    async def test_aggregates_all_vpn_types(self) -> None:
        from opnsense.tools.vpn import opnsense__vpn__get_vpn_status

        ipsec_fixture = load_fixture("ipsec_sessions.json")
        wg_fixture = load_fixture("wireguard_peers.json")
        ovpn_data = {"rows": [
            {
                "uuid": "ovpn-1",
                "role": "server",
                "proto": "udp",
                "port": 1194,
                "enabled": True,
                "clients": 2,
                "dev_type": "tun",
                "description": "VPN Server",
            },
        ]}

        client = _make_client_multi({
            ("ipsec", "sessions", "search"): ipsec_fixture,
            ("openvpn", "instances", "search"): ovpn_data,
            ("wireguard", "client", "search"): wg_fixture,
        })

        status = await opnsense__vpn__get_vpn_status(client)

        # Structure check
        assert "ipsec" in status
        assert "openvpn" in status
        assert "wireguard" in status
        assert "totals" in status

    @pytest.mark.asyncio
    async def test_ipsec_summary_counts(self) -> None:
        from opnsense.tools.vpn import opnsense__vpn__get_vpn_status

        ipsec_fixture = load_fixture("ipsec_sessions.json")
        client = _make_client_multi({
            ("ipsec", "sessions", "search"): ipsec_fixture,
            ("openvpn", "instances", "search"): {"rows": []},
            ("wireguard", "client", "search"): {"rows": []},
        })

        status = await opnsense__vpn__get_vpn_status(client)

        ipsec_summary = status["ipsec"]["summary"]
        assert ipsec_summary["total"] == 2
        assert ipsec_summary["connected"] == 1
        assert ipsec_summary["disconnected"] == 1

    @pytest.mark.asyncio
    async def test_wireguard_summary_counts(self) -> None:
        from opnsense.tools.vpn import opnsense__vpn__get_vpn_status

        wg_fixture = load_fixture("wireguard_peers.json")
        client = _make_client_multi({
            ("ipsec", "sessions", "search"): {"rows": []},
            ("openvpn", "instances", "search"): {"rows": []},
            ("wireguard", "client", "search"): wg_fixture,
        })

        status = await opnsense__vpn__get_vpn_status(client)

        wg_summary = status["wireguard"]["summary"]
        assert wg_summary["total"] == 3
        assert wg_summary["active"] == 2  # Two peers with last_handshake
        assert wg_summary["inactive"] == 1

    @pytest.mark.asyncio
    async def test_totals_aggregation(self) -> None:
        from opnsense.tools.vpn import opnsense__vpn__get_vpn_status

        ipsec_fixture = load_fixture("ipsec_sessions.json")
        wg_fixture = load_fixture("wireguard_peers.json")
        client = _make_client_multi({
            ("ipsec", "sessions", "search"): ipsec_fixture,
            ("openvpn", "instances", "search"): {"rows": []},
            ("wireguard", "client", "search"): wg_fixture,
        })

        status = await opnsense__vpn__get_vpn_status(client)

        totals = status["totals"]
        assert totals["total_tunnels"] == 5  # 2 ipsec + 3 wg
        assert totals["total_active"] == 3  # 1 ipsec + 2 wg

    @pytest.mark.asyncio
    async def test_all_empty(self) -> None:
        from opnsense.tools.vpn import opnsense__vpn__get_vpn_status

        client = _make_client_multi({
            ("ipsec", "sessions", "search"): {"rows": []},
            ("openvpn", "instances", "search"): {"rows": []},
            ("wireguard", "client", "search"): {"rows": []},
        })

        status = await opnsense__vpn__get_vpn_status(client)

        assert status["totals"]["total_tunnels"] == 0
        assert status["totals"]["total_active"] == 0
