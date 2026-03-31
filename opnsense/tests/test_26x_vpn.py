"""Tests for OPNsense 26.x VPN endpoint compatibility and graceful degradation.

Covers:
- 404 graceful degradation when VPN plugins are not installed
- Endpoint fallback chains (primary -> 26.x alternatives)
- Mixed availability scenarios (some VPN types available, others not)
- Non-404 error propagation (500, 403 are still raised)
- VPNResult metadata structure
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

import pytest

from opnsense.errors import APIError
from opnsense.tools.vpn import VPNResult
from tests.fixtures import load_fixture

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_404_error(endpoint: str) -> APIError:
    """Create a realistic 404 APIError matching OPNsenseClient behavior."""
    return APIError(
        f"Not found (404): {endpoint}",
        status_code=404,
        endpoint=endpoint,
        response_body="",
    )


def _make_500_error(endpoint: str) -> APIError:
    """Create a realistic 500 APIError."""
    return APIError(
        f"Server error (500) for {endpoint}",
        status_code=500,
        endpoint=endpoint,
        response_body="Internal Server Error",
    )


def _make_fallback_client(
    primary_endpoints: list[tuple[str, str, str]],
    fallback_response: dict[str, Any] | None = None,
    fallback_endpoint: tuple[str, str, str] | None = None,
) -> AsyncMock:
    """Create a client where primary endpoints 404 but a fallback succeeds.

    Parameters
    ----------
    primary_endpoints:
        Endpoints that should return 404.
    fallback_response:
        Response to return from the fallback endpoint.
    fallback_endpoint:
        The endpoint that should succeed. If None, all endpoints 404.
    """
    client = AsyncMock()

    async def _get(module: str, controller: str, command: str, **kwargs: Any) -> dict[str, Any]:
        key = (module, controller, command)
        if key in primary_endpoints:
            endpoint_path = f"/api/{module}/{controller}/{command}"
            raise _make_404_error(endpoint_path)
        if fallback_endpoint is not None and key == fallback_endpoint:
            return fallback_response or {"rows": []}
        # Default: return empty rows for any unmatched endpoint
        return {"rows": []}

    client.get = AsyncMock(side_effect=_get)
    return client


def _make_all_404_client() -> AsyncMock:
    """Create a client where every GET returns 404."""
    client = AsyncMock()

    async def _get(module: str, controller: str, command: str, **kwargs: Any) -> dict[str, Any]:
        endpoint_path = f"/api/{module}/{controller}/{command}"
        raise _make_404_error(endpoint_path)

    client.get = AsyncMock(side_effect=_get)
    return client


def _make_mixed_client(
    available: dict[str, dict[str, Any]],
    unavailable_prefixes: list[str],
) -> AsyncMock:
    """Create a client where some VPN modules are available and others 404.

    Parameters
    ----------
    available:
        Map of ``(module, controller, command)`` -> response for available services.
    unavailable_prefixes:
        Module prefixes (e.g. ``"wireguard"``) where all endpoints 404.
    """
    client = AsyncMock()

    async def _get(module: str, controller: str, command: str, **kwargs: Any) -> dict[str, Any]:
        key = (module, controller, command)
        if key in available:
            return available[key]
        if module in unavailable_prefixes:
            endpoint_path = f"/api/{module}/{controller}/{command}"
            raise _make_404_error(endpoint_path)
        return {"rows": []}

    client.get = AsyncMock(side_effect=_get)
    return client


# ---------------------------------------------------------------------------
# VPNResult unit tests
# ---------------------------------------------------------------------------


class TestVPNResult:
    def test_to_dict_available(self) -> None:
        result = VPNResult(
            [{"id": "1"}],
            available=True,
            endpoint_used="/api/ipsec/sessions/search",
        )
        d = result.to_dict()
        assert d["items"] == [{"id": "1"}]
        assert d["_meta"]["available"] is True
        assert d["_meta"]["endpoint_used"] == "/api/ipsec/sessions/search"
        assert d["_meta"]["note"] == ""

    def test_to_dict_unavailable(self) -> None:
        result = VPNResult(
            [],
            available=False,
            note="Service not installed",
        )
        d = result.to_dict()
        assert d["items"] == []
        assert d["_meta"]["available"] is False
        assert d["_meta"]["endpoint_used"] is None
        assert d["_meta"]["note"] == "Service not installed"


# ---------------------------------------------------------------------------
# IPSec 404 graceful degradation
# ---------------------------------------------------------------------------


class TestIPSec404Degradation:
    @pytest.mark.asyncio
    async def test_all_endpoints_404_returns_empty_unavailable(self) -> None:
        """When all IPSec endpoints 404, return empty with available=False."""
        from opnsense.tools.vpn import opnsense__vpn__list_ipsec_sessions

        client = _make_all_404_client()
        result = await opnsense__vpn__list_ipsec_sessions(client)

        assert result["items"] == []
        assert result["_meta"]["available"] is False
        assert result["_meta"]["endpoint_used"] is None
        assert "not installed" in result["_meta"]["note"].lower()

    @pytest.mark.asyncio
    async def test_primary_404_fallback_succeeds(self) -> None:
        """When primary IPSec endpoint 404s, try fallback endpoints."""
        from opnsense.tools.vpn import opnsense__vpn__list_ipsec_sessions

        fixture = load_fixture("ipsec_sessions.json")
        client = _make_fallback_client(
            primary_endpoints=[("ipsec", "sessions", "search")],
            fallback_response=fixture,
            fallback_endpoint=("ipsec", "tunnel", "searchPhase1"),
        )

        result = await opnsense__vpn__list_ipsec_sessions(client)

        assert len(result["items"]) == 2
        assert result["_meta"]["available"] is True
        assert result["_meta"]["endpoint_used"] == "/api/ipsec/tunnel/searchPhase1"

    @pytest.mark.asyncio
    async def test_primary_and_first_fallback_404_second_fallback_succeeds(self) -> None:
        """When primary and first fallback 404, try the second fallback."""
        from opnsense.tools.vpn import opnsense__vpn__list_ipsec_sessions

        fixture = load_fixture("ipsec_sessions.json")
        client = _make_fallback_client(
            primary_endpoints=[
                ("ipsec", "sessions", "search"),
                ("ipsec", "tunnel", "searchPhase1"),
            ],
            fallback_response=fixture,
            fallback_endpoint=("ipsec", "sad", "search"),
        )

        result = await opnsense__vpn__list_ipsec_sessions(client)

        assert len(result["items"]) == 2
        assert result["_meta"]["available"] is True
        assert result["_meta"]["endpoint_used"] == "/api/ipsec/sad/search"

    @pytest.mark.asyncio
    async def test_500_error_propagates(self) -> None:
        """Non-404 errors (e.g. 500) should still raise."""
        from opnsense.tools.vpn import opnsense__vpn__list_ipsec_sessions

        client = AsyncMock()

        async def _get(module: str, controller: str, command: str, **kwargs: Any) -> dict[str, Any]:
            raise _make_500_error(f"/api/{module}/{controller}/{command}")

        client.get = AsyncMock(side_effect=_get)

        with pytest.raises(APIError) as exc_info:
            await opnsense__vpn__list_ipsec_sessions(client)
        assert exc_info.value.status_code == 500


# ---------------------------------------------------------------------------
# OpenVPN 404 graceful degradation
# ---------------------------------------------------------------------------


class TestOpenVPN404Degradation:
    @pytest.mark.asyncio
    async def test_all_endpoints_404_returns_empty_unavailable(self) -> None:
        from opnsense.tools.vpn import opnsense__vpn__list_openvpn_instances

        client = _make_all_404_client()
        result = await opnsense__vpn__list_openvpn_instances(client)

        assert result["items"] == []
        assert result["_meta"]["available"] is False
        assert "not installed" in result["_meta"]["note"].lower()

    @pytest.mark.asyncio
    async def test_primary_404_fallback_succeeds(self) -> None:
        from opnsense.tools.vpn import opnsense__vpn__list_openvpn_instances

        ovpn_data = {
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
        client = _make_fallback_client(
            primary_endpoints=[("openvpn", "instances", "search")],
            fallback_response=ovpn_data,
            fallback_endpoint=("openvpn", "service", "searchServer"),
        )

        result = await opnsense__vpn__list_openvpn_instances(client)

        assert len(result["items"]) == 1
        assert result["_meta"]["available"] is True
        assert result["_meta"]["endpoint_used"] == "/api/openvpn/service/searchServer"

    @pytest.mark.asyncio
    async def test_500_error_propagates(self) -> None:
        from opnsense.tools.vpn import opnsense__vpn__list_openvpn_instances

        client = AsyncMock()

        async def _get(module: str, controller: str, command: str, **kwargs: Any) -> dict[str, Any]:
            raise _make_500_error(f"/api/{module}/{controller}/{command}")

        client.get = AsyncMock(side_effect=_get)

        with pytest.raises(APIError) as exc_info:
            await opnsense__vpn__list_openvpn_instances(client)
        assert exc_info.value.status_code == 500


# ---------------------------------------------------------------------------
# WireGuard 404 graceful degradation
# ---------------------------------------------------------------------------


class TestWireGuard404Degradation:
    @pytest.mark.asyncio
    async def test_all_endpoints_404_returns_empty_unavailable(self) -> None:
        from opnsense.tools.vpn import opnsense__vpn__list_wireguard_peers

        client = _make_all_404_client()
        result = await opnsense__vpn__list_wireguard_peers(client)

        assert result["items"] == []
        assert result["_meta"]["available"] is False
        assert "not installed" in result["_meta"]["note"].lower()

    @pytest.mark.asyncio
    async def test_primary_404_fallback_succeeds(self) -> None:
        from opnsense.tools.vpn import opnsense__vpn__list_wireguard_peers

        fixture = load_fixture("wireguard_peers.json")
        client = _make_fallback_client(
            primary_endpoints=[("wireguard", "client", "search")],
            fallback_response=fixture,
            fallback_endpoint=("wireguard", "server", "searchServer"),
        )

        result = await opnsense__vpn__list_wireguard_peers(client)

        assert len(result["items"]) == 3
        assert result["_meta"]["available"] is True
        assert result["_meta"]["endpoint_used"] == "/api/wireguard/server/searchServer"

    @pytest.mark.asyncio
    async def test_second_fallback_succeeds(self) -> None:
        from opnsense.tools.vpn import opnsense__vpn__list_wireguard_peers

        fixture = load_fixture("wireguard_peers.json")
        client = _make_fallback_client(
            primary_endpoints=[
                ("wireguard", "client", "search"),
                ("wireguard", "server", "searchServer"),
            ],
            fallback_response=fixture,
            fallback_endpoint=("wireguard", "general", "get"),
        )

        result = await opnsense__vpn__list_wireguard_peers(client)

        assert len(result["items"]) == 3
        assert result["_meta"]["available"] is True
        assert result["_meta"]["endpoint_used"] == "/api/wireguard/general/get"

    @pytest.mark.asyncio
    async def test_500_error_propagates(self) -> None:
        from opnsense.tools.vpn import opnsense__vpn__list_wireguard_peers

        client = AsyncMock()

        async def _get(module: str, controller: str, command: str, **kwargs: Any) -> dict[str, Any]:
            raise _make_500_error(f"/api/{module}/{controller}/{command}")

        client.get = AsyncMock(side_effect=_get)

        with pytest.raises(APIError) as exc_info:
            await opnsense__vpn__list_wireguard_peers(client)
        assert exc_info.value.status_code == 500


# ---------------------------------------------------------------------------
# get_vpn_status -- mixed availability scenarios
# ---------------------------------------------------------------------------


class TestVPNStatusMixedAvailability:
    @pytest.mark.asyncio
    async def test_all_services_unavailable(self) -> None:
        """When all VPN plugins are uninstalled, get_vpn_status still works."""
        from opnsense.tools.vpn import opnsense__vpn__get_vpn_status

        client = _make_all_404_client()
        status = await opnsense__vpn__get_vpn_status(client)

        # All services unavailable
        assert status["_meta"]["services_available"]["ipsec"] is False
        assert status["_meta"]["services_available"]["openvpn"] is False
        assert status["_meta"]["services_available"]["wireguard"] is False
        assert len(status["_meta"]["unavailable_services"]) == 3

        # Totals should be zero
        assert status["totals"]["total_tunnels"] == 0
        assert status["totals"]["total_active"] == 0

        # Each section should have empty items and correct metadata
        assert status["ipsec"]["sessions"] == []
        assert status["ipsec"]["_meta"]["available"] is False
        assert status["openvpn"]["instances"] == []
        assert status["openvpn"]["_meta"]["available"] is False
        assert status["wireguard"]["peers"] == []
        assert status["wireguard"]["_meta"]["available"] is False

    @pytest.mark.asyncio
    async def test_only_ipsec_available(self) -> None:
        """IPSec installed, OpenVPN and WireGuard not installed."""
        from opnsense.tools.vpn import opnsense__vpn__get_vpn_status

        ipsec_fixture = load_fixture("ipsec_sessions.json")
        client = _make_mixed_client(
            available={("ipsec", "sessions", "search"): ipsec_fixture},
            unavailable_prefixes=["openvpn", "wireguard"],
        )

        status = await opnsense__vpn__get_vpn_status(client)

        assert status["_meta"]["services_available"]["ipsec"] is True
        assert status["_meta"]["services_available"]["openvpn"] is False
        assert status["_meta"]["services_available"]["wireguard"] is False
        assert status["_meta"]["unavailable_services"] == ["openvpn", "wireguard"]

        # IPSec data is present
        assert len(status["ipsec"]["sessions"]) == 2
        assert status["ipsec"]["summary"]["total"] == 2

        # Other services empty
        assert status["openvpn"]["instances"] == []
        assert status["wireguard"]["peers"] == []

        # Totals only count available services
        assert status["totals"]["total_tunnels"] == 2
        assert status["totals"]["total_active"] == 1  # 1 connected IPSec

    @pytest.mark.asyncio
    async def test_only_wireguard_available(self) -> None:
        """WireGuard installed, IPSec and OpenVPN not installed."""
        from opnsense.tools.vpn import opnsense__vpn__get_vpn_status

        wg_fixture = load_fixture("wireguard_peers.json")
        client = _make_mixed_client(
            available={("wireguard", "client", "search"): wg_fixture},
            unavailable_prefixes=["ipsec", "openvpn"],
        )

        status = await opnsense__vpn__get_vpn_status(client)

        assert status["_meta"]["services_available"]["wireguard"] is True
        assert status["_meta"]["services_available"]["ipsec"] is False
        assert status["_meta"]["services_available"]["openvpn"] is False

        assert len(status["wireguard"]["peers"]) == 3
        assert status["wireguard"]["summary"]["active"] == 2

        assert status["totals"]["total_tunnels"] == 3
        assert status["totals"]["total_active"] == 2

    @pytest.mark.asyncio
    async def test_ipsec_and_wireguard_available_openvpn_not(self) -> None:
        """IPSec and WireGuard installed, OpenVPN not installed."""
        from opnsense.tools.vpn import opnsense__vpn__get_vpn_status

        ipsec_fixture = load_fixture("ipsec_sessions.json")
        wg_fixture = load_fixture("wireguard_peers.json")
        client = _make_mixed_client(
            available={
                ("ipsec", "sessions", "search"): ipsec_fixture,
                ("wireguard", "client", "search"): wg_fixture,
            },
            unavailable_prefixes=["openvpn"],
        )

        status = await opnsense__vpn__get_vpn_status(client)

        assert status["_meta"]["services_available"]["ipsec"] is True
        assert status["_meta"]["services_available"]["openvpn"] is False
        assert status["_meta"]["services_available"]["wireguard"] is True
        assert status["_meta"]["unavailable_services"] == ["openvpn"]

        # Summaries are correct
        assert status["ipsec"]["summary"]["total"] == 2
        assert status["openvpn"]["summary"]["total"] == 0
        assert status["wireguard"]["summary"]["total"] == 3

        assert status["totals"]["total_tunnels"] == 5
        assert status["totals"]["total_active"] == 3

    @pytest.mark.asyncio
    async def test_non_404_error_still_propagates_in_status(self) -> None:
        """A 500 error from one VPN service should propagate, not be swallowed."""
        from opnsense.tools.vpn import opnsense__vpn__get_vpn_status

        client = AsyncMock()

        async def _get(module: str, controller: str, command: str, **kwargs: Any) -> dict[str, Any]:
            if module == "ipsec":
                raise _make_500_error(f"/api/{module}/{controller}/{command}")
            return {"rows": []}

        client.get = AsyncMock(side_effect=_get)

        with pytest.raises(APIError) as exc_info:
            await opnsense__vpn__get_vpn_status(client)
        assert exc_info.value.status_code == 500

    @pytest.mark.asyncio
    async def test_all_services_available_with_data(self) -> None:
        """All three VPN services available with data -- verify full metadata."""
        from opnsense.tools.vpn import opnsense__vpn__get_vpn_status

        ipsec_fixture = load_fixture("ipsec_sessions.json")
        wg_fixture = load_fixture("wireguard_peers.json")
        ovpn_data = {
            "rows": [
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
            ]
        }

        client = _make_mixed_client(
            available={
                ("ipsec", "sessions", "search"): ipsec_fixture,
                ("openvpn", "instances", "search"): ovpn_data,
                ("wireguard", "client", "search"): wg_fixture,
            },
            unavailable_prefixes=[],
        )

        status = await opnsense__vpn__get_vpn_status(client)

        assert status["_meta"]["services_available"]["ipsec"] is True
        assert status["_meta"]["services_available"]["openvpn"] is True
        assert status["_meta"]["services_available"]["wireguard"] is True
        assert status["_meta"]["unavailable_services"] == []

        assert status["totals"]["total_tunnels"] == 6  # 2 ipsec + 1 ovpn + 3 wg
        assert status["totals"]["total_active"] == 4  # 1 ipsec + 1 ovpn + 2 wg
