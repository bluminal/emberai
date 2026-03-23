# SPDX-License-Identifier: MIT
"""Integration tests for the full API client stack.

Tests the end-to-end flow: LocalGatewayClient -> response normalization ->
Pydantic model parsing, as well as the cached client wrapping the full stack.

These tests use the realistic mock fixtures from ``tests/fixtures/`` and mock
httpx at the transport level to verify that all layers work together correctly.
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any
from unittest.mock import AsyncMock

import httpx
import pytest

from tests.fixtures import load_fixture
from unifi.api.cached_client import CachedGatewayClient
from unifi.api.local_gateway_client import LocalGatewayClient
from unifi.api.response import NormalizedResponse, normalize_response
from unifi.cache import TTLCache
from unifi.errors import APIError, AuthenticationError, NetworkError
from unifi.models import VLAN, Client, Device, Event, FirmwareStatus, HealthStatus

if TYPE_CHECKING:
    from collections.abc import Iterator


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

_FAKE_REQUEST = httpx.Request("GET", "https://fake")


def _mock_response(
    status_code: int = 200,
    json_data: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    text: str = "",
) -> httpx.Response:
    """Build a fake httpx.Response for testing."""
    content = json.dumps(json_data).encode() if json_data is not None else text.encode()
    return httpx.Response(
        status_code=status_code,
        content=content,
        headers=headers or {},
        request=_FAKE_REQUEST,
    )


def _make_gateway_client() -> LocalGatewayClient:
    """Create a LocalGatewayClient with test credentials."""
    return LocalGatewayClient(host="192.168.1.1", api_key="test-key-integration")


def _make_cached_client(
    raw_client: LocalGatewayClient,
    max_size: int = 500,
    default_ttl: float = 300.0,
) -> tuple[CachedGatewayClient, TTLCache]:
    """Wrap a LocalGatewayClient with a CachedGatewayClient."""
    cache = TTLCache(max_size=max_size, default_ttl=default_ttl)
    cached = CachedGatewayClient(raw_client, cache)
    return cached, cache


@pytest.fixture(autouse=True)
def _enable_log_propagation() -> Iterator[None]:
    """Ensure the ``unifi`` logger propagates during tests for caplog."""
    unifi_logger = logging.getLogger("unifi")
    original_propagate = unifi_logger.propagate
    unifi_logger.propagate = True
    yield
    unifi_logger.propagate = original_propagate


# ===========================================================================
# 1. Full flow: client -> normalize -> model parse
# ===========================================================================


class TestFullFlowDevices:
    """Integration: LocalGatewayClient -> normalize -> Device model."""

    @pytest.mark.asyncio
    async def test_get_normalized_devices_from_fixture(self) -> None:
        """Full stack: mock httpx -> get_normalized -> parse Device models."""
        fixture = load_fixture("device_list.json")
        mock_resp = _mock_response(200, json_data=fixture)

        async with _make_gateway_client() as client:
            client._client.request = AsyncMock(return_value=mock_resp)
            normalized = await client.get_normalized("/api/s/default/stat/device")

        assert isinstance(normalized, NormalizedResponse)
        assert normalized.count == 3

        # Parse each item into a Device model. The fixture uses integer
        # ``state`` values (1) but the model declares ``status: str``.
        # Pydantic strict mode rejects int->str coercion, so we convert
        # the state field to a string to mirror what a real adapter layer
        # would do. This validates the integration seam.
        for item in normalized.data:
            item["state"] = str(item["state"])
            device = Device.model_validate(item)
            assert device.device_id
            assert device.mac
            assert device.model

    @pytest.mark.asyncio
    async def test_device_field_values_from_fixture(self) -> None:
        """Verify specific field mappings against known fixture data."""
        fixture = load_fixture("device_list.json")
        mock_resp = _mock_response(200, json_data=fixture)

        async with _make_gateway_client() as client:
            client._client.request = AsyncMock(return_value=mock_resp)
            normalized = await client.get_normalized("/api/s/default/stat/device")

        # First device: USG-Gateway
        gateway_data = normalized.data[0]
        gateway_data["state"] = str(gateway_data["state"])
        gateway = Device.model_validate(gateway_data)
        assert gateway.device_id == "64a1b2c3d4e5f6a7b8c9d0e1"
        assert gateway.name == "USG-Gateway"
        assert gateway.mac == "f0:9f:c2:aa:11:22"
        assert gateway.model == "UXG-Max"
        assert gateway.ip == "192.168.1.1"
        assert gateway.firmware == "4.0.6.6754"
        assert gateway.uptime == 1728432

        # Second device: Office-Switch-16
        switch_data = normalized.data[1]
        switch_data["state"] = str(switch_data["state"])
        switch = Device.model_validate(switch_data)
        assert switch.device_id == "64b2c3d4e5f6a7b8c9d0e1f2"
        assert switch.name == "Office-Switch-16"
        assert switch.port_table is not None
        assert len(switch.port_table) == 3

        # Third device: Office-AP-Main
        ap_data = normalized.data[2]
        ap_data["state"] = str(ap_data["state"])
        ap = Device.model_validate(ap_data)
        assert ap.device_id == "64c3d4e5f6a7b8c9d0e1f2a3"
        assert ap.name == "Office-AP-Main"
        assert ap.model == "U6-Pro"
        assert ap.radio_table is not None
        assert len(ap.radio_table) == 2

    @pytest.mark.asyncio
    async def test_get_single_device_from_fixture(self) -> None:
        """Full stack: get_single returns a single device dict."""
        fixture = load_fixture("device_single.json")
        mock_resp = _mock_response(200, json_data=fixture)

        async with _make_gateway_client() as client:
            client._client.request = AsyncMock(return_value=mock_resp)
            single = await client.get_single("/api/s/default/stat/device/74:ac:b9:bb:33:44")

        assert single["_id"] == "64b2c3d4e5f6a7b8c9d0e1f2"
        assert single["name"] == "Office-Switch-16"
        assert len(single["port_table"]) == 6

        # Parse into Device model
        single["state"] = str(single["state"])
        device = Device.model_validate(single)
        assert device.device_id == "64b2c3d4e5f6a7b8c9d0e1f2"
        assert device.config_network is not None
        assert device.config_network["type"] == "dhcp"


class TestFullFlowClients:
    """Integration: LocalGatewayClient -> normalize -> Client model."""

    @pytest.mark.asyncio
    async def test_get_normalized_clients_from_fixture(self) -> None:
        """Full stack: fixture data -> normalize -> Client models."""
        fixture = load_fixture("client_list.json")
        mock_resp = _mock_response(200, json_data=fixture)

        async with _make_gateway_client() as client:
            client._client.request = AsyncMock(return_value=mock_resp)
            normalized = await client.get_normalized("/api/s/default/stat/sta")

        assert normalized.count == 6

        for item in normalized.data:
            model = Client.model_validate(item)
            assert model.client_mac
            assert model.ip

    @pytest.mark.asyncio
    async def test_client_field_values_from_fixture(self) -> None:
        """Verify specific field mappings for clients."""
        fixture = load_fixture("client_list.json")
        mock_resp = _mock_response(200, json_data=fixture)

        async with _make_gateway_client() as client:
            client._client.request = AsyncMock(return_value=mock_resp)
            normalized = await client.get_normalized("/api/s/default/stat/sta")

        # First client: wireless MacBook
        macbook = Client.model_validate(normalized.data[0])
        assert macbook.client_mac == "a4:83:e7:11:22:33"
        assert macbook.hostname == "macbook-pro-jdoe"
        assert macbook.ip == "192.168.1.101"
        assert macbook.is_wired is False
        assert macbook.is_guest is False
        assert macbook.vlan_id == "5f9a8b7c6d5e4f3a2b1c0001"
        assert macbook.ap_id == "e0:63:da:cc:55:66"
        assert macbook.device_vendor == "Apple"
        assert macbook.rssi == 56

        # Third client: wired NAS
        nas = Client.model_validate(normalized.data[2])
        assert nas.client_mac == "b0:be:76:33:44:55"
        assert nas.is_wired is True
        assert nas.port_id == 4
        assert nas.uptime == 1728432

        # Fourth client: guest iPhone
        guest = Client.model_validate(normalized.data[3])
        assert guest.is_guest is True
        assert guest.ip == "192.168.10.102"


class TestFullFlowVLANs:
    """Integration: LocalGatewayClient -> normalize -> VLAN model."""

    @pytest.mark.asyncio
    async def test_get_normalized_vlans_from_fixture(self) -> None:
        """Full stack: fixture data -> normalize -> VLAN models."""
        fixture = load_fixture("vlan_config.json")
        mock_resp = _mock_response(200, json_data=fixture)

        async with _make_gateway_client() as client:
            client._client.request = AsyncMock(return_value=mock_resp)
            normalized = await client.get_normalized("/api/s/default/rest/networkconf")

        assert normalized.count == 4

        for item in normalized.data:
            vlan = VLAN.model_validate(item)
            assert vlan.vlan_id
            assert vlan.name

    @pytest.mark.asyncio
    async def test_vlan_field_values_from_fixture(self) -> None:
        """Verify specific VLAN field mappings."""
        fixture = load_fixture("vlan_config.json")
        mock_resp = _mock_response(200, json_data=fixture)

        async with _make_gateway_client() as client:
            client._client.request = AsyncMock(return_value=mock_resp)
            normalized = await client.get_normalized("/api/s/default/rest/networkconf")

        # Default network
        default = VLAN.model_validate(normalized.data[0])
        assert default.name == "Default"
        assert default.subnet == "192.168.1.0/24"
        assert default.purpose == "corporate"
        assert default.dhcp_enabled is True
        assert default.domain_name == "localdomain"

        # Guest network
        guest = VLAN.model_validate(normalized.data[1])
        assert guest.name == "Guest"
        assert guest.purpose == "guest"
        assert guest.subnet == "192.168.10.0/24"

        # IoT network
        iot = VLAN.model_validate(normalized.data[2])
        assert iot.name == "IoT"
        assert iot.subnet == "192.168.30.0/24"

        # Management network
        mgmt = VLAN.model_validate(normalized.data[3])
        assert mgmt.name == "Management"
        assert mgmt.subnet == "192.168.99.0/24"


class TestFullFlowHealth:
    """Integration: LocalGatewayClient -> normalize -> HealthStatus model."""

    @pytest.mark.asyncio
    async def test_get_normalized_health_from_fixture(self) -> None:
        """Full stack: fixture data -> normalize -> HealthStatus from subsystems."""
        fixture = load_fixture("health.json")
        mock_resp = _mock_response(200, json_data=fixture)

        async with _make_gateway_client() as client:
            client._client.request = AsyncMock(return_value=mock_resp)
            normalized = await client.get_normalized("/api/s/default/stat/health")

        assert normalized.count == 5  # wan, wlan, lan, vpn, www subsystems

        # The health fixture returns an array of subsystem dicts.
        # HealthStatus represents the merged view. Build it from subsystem data.
        subsystems = {item["subsystem"]: item for item in normalized.data}
        assert "wan" in subsystems
        assert "lan" in subsystems
        assert "wlan" in subsystems
        assert "www" in subsystems

        wan = subsystems["wan"]
        assert wan["status"] == "ok"
        assert wan["wan_ip"] == "203.0.113.42"

        # Construct HealthStatus from merged subsystem data (as the tool
        # layer would do).
        health = HealthStatus(
            wan_status=subsystems["wan"]["status"],
            lan_status=subsystems["lan"]["status"],
            wlan_status=subsystems["wlan"]["status"],
            www_status=subsystems["www"]["status"],
        )
        assert health.wan_status == "ok"
        assert health.lan_status == "ok"
        assert health.wlan_status == "ok"
        assert health.www_status == "ok"


class TestFullFlowEvents:
    """Integration: LocalGatewayClient -> normalize -> Event model."""

    @pytest.mark.asyncio
    async def test_get_normalized_events_from_fixture(self) -> None:
        """Full stack: fixture data -> normalize -> Event models."""
        fixture = load_fixture("event_list.json")
        mock_resp = _mock_response(200, json_data=fixture)

        async with _make_gateway_client() as client:
            client._client.request = AsyncMock(return_value=mock_resp)
            normalized = await client.get_normalized("/api/s/default/stat/event")

        assert normalized.count == 6

        for item in normalized.data:
            event = Event.model_validate(item)
            assert event.type  # aliased from "key"
            assert event.message  # aliased from "msg"
            assert event.timestamp  # aliased from "datetime"

    @pytest.mark.asyncio
    async def test_event_field_values_from_fixture(self) -> None:
        """Verify specific event field mappings."""
        fixture = load_fixture("event_list.json")
        mock_resp = _mock_response(200, json_data=fixture)

        async with _make_gateway_client() as client:
            client._client.request = AsyncMock(return_value=mock_resp)
            normalized = await client.get_normalized("/api/s/default/stat/event")

        # First event: Wi-Fi client connected
        connect_evt = Event.model_validate(normalized.data[0])
        assert connect_evt.type == "EVT_WU_Connected"
        assert connect_evt.subsystem == "wlan"
        assert connect_evt.client_mac == "a4:83:e7:11:22:33"
        assert "HomeNet" in connect_evt.message

        # Second event: PoE overload (has sw alias for device_id)
        poe_evt = Event.model_validate(normalized.data[1])
        assert poe_evt.type == "EVT_SW_PoeOverload"
        assert poe_evt.subsystem == "lan"
        assert poe_evt.device_id == "74:ac:b9:bb:33:44"

        # Fifth event: IPS alert
        ips_evt = Event.model_validate(normalized.data[4])
        assert ips_evt.type == "EVT_IPS_IpsAlert"
        assert "SSH Scan" in ips_evt.message


class TestFullFlowFirmware:
    """Integration: LocalGatewayClient -> normalize -> FirmwareStatus model."""

    @pytest.mark.asyncio
    async def test_get_normalized_firmware_from_fixture(self) -> None:
        """Full stack: fixture data -> normalize -> FirmwareStatus models."""
        fixture = load_fixture("firmware_status.json")
        mock_resp = _mock_response(200, json_data=fixture)

        async with _make_gateway_client() as client:
            client._client.request = AsyncMock(return_value=mock_resp)
            normalized = await client.get_normalized("/api/s/default/stat/device")

        assert normalized.count == 3

        for item in normalized.data:
            fw = FirmwareStatus.model_validate(item)
            assert fw.device_id
            assert fw.model
            assert fw.current_version

    @pytest.mark.asyncio
    async def test_firmware_upgrade_available(self) -> None:
        """Verify firmware upgrade detection for switch with available update."""
        fixture = load_fixture("firmware_status.json")
        mock_resp = _mock_response(200, json_data=fixture)

        async with _make_gateway_client() as client:
            client._client.request = AsyncMock(return_value=mock_resp)
            normalized = await client.get_normalized("/api/s/default/stat/device")

        # Gateway: no upgrade
        gateway = FirmwareStatus.model_validate(normalized.data[0])
        assert gateway.upgrade_available is False
        assert gateway.current_version == "4.0.6.6754"

        # Switch: upgrade available
        switch = FirmwareStatus.model_validate(normalized.data[1])
        assert switch.upgrade_available is True
        assert switch.current_version == "7.0.50.15116"
        assert switch.latest_version == "7.0.72.15290"

        # AP: no upgrade
        ap = FirmwareStatus.model_validate(normalized.data[2])
        assert ap.upgrade_available is False


# ===========================================================================
# 2. Cached flow: cached_client -> client -> normalize
# ===========================================================================


class TestCachedFlowIntegration:
    """Integration tests for the full cached client stack."""

    @pytest.mark.asyncio
    async def test_cached_get_first_call_fetches_from_api(self) -> None:
        """First call through cached client should hit the underlying API."""
        fixture = load_fixture("device_list.json")
        mock_resp = _mock_response(200, json_data=fixture)

        async with _make_gateway_client() as raw_client:
            raw_client._client.request = AsyncMock(return_value=mock_resp)
            cached_client, _cache = _make_cached_client(raw_client)

            result = await cached_client.get("/api/s/default/stat/device")

        assert result == fixture
        raw_client._client.request.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_cached_get_second_call_returns_cached(self) -> None:
        """Second identical call should return cached data without httpx call."""
        fixture = load_fixture("client_list.json")
        mock_resp = _mock_response(200, json_data=fixture)

        async with _make_gateway_client() as raw_client:
            raw_client._client.request = AsyncMock(return_value=mock_resp)
            cached_client, _cache = _make_cached_client(raw_client)

            result1 = await cached_client.get("/api/s/default/stat/sta")
            result2 = await cached_client.get("/api/s/default/stat/sta")

        assert result1 == result2
        assert raw_client._client.request.await_count == 1

    @pytest.mark.asyncio
    async def test_cached_then_normalize_then_parse(self) -> None:
        """Full integration: cached client -> normalize -> model parse."""
        fixture = load_fixture("vlan_config.json")
        mock_resp = _mock_response(200, json_data=fixture)

        async with _make_gateway_client() as raw_client:
            raw_client._client.request = AsyncMock(return_value=mock_resp)
            cached_client, _ = _make_cached_client(raw_client)

            # First call: fetches from API
            raw_result = await cached_client.get("/api/s/default/rest/networkconf")
            normalized = normalize_response(raw_result)
            vlans = [VLAN.model_validate(item) for item in normalized.data]
            assert len(vlans) == 4
            assert vlans[0].name == "Default"

            # Second call: cached, same result
            raw_result2 = await cached_client.get("/api/s/default/rest/networkconf")
            normalized2 = normalize_response(raw_result2)
            vlans2 = [VLAN.model_validate(item) for item in normalized2.data]
            assert len(vlans2) == 4
            assert vlans2[0].name == "Default"

        # Only one httpx call
        assert raw_client._client.request.await_count == 1

    @pytest.mark.asyncio
    async def test_post_flushes_cache_then_refetches(self) -> None:
        """POST flushes cache; next GET fetches fresh data from API."""
        fixture_v1 = load_fixture("vlan_config.json")
        # Simulate a modified response for the second fetch
        fixture_v2 = load_fixture("vlan_config.json")
        fixture_v2["data"][0]["name"] = "Default-Updated"

        mock_resp_v1 = _mock_response(200, json_data=fixture_v1)
        mock_resp_post = _mock_response(200, json_data={"data": [], "meta": {"rc": "ok"}})
        mock_resp_v2 = _mock_response(200, json_data=fixture_v2)

        async with _make_gateway_client() as raw_client:
            raw_client._client.request = AsyncMock(
                side_effect=[mock_resp_v1, mock_resp_post, mock_resp_v2]
            )
            cached_client, _ = _make_cached_client(raw_client)

            # GET -> cache miss, fetches v1
            result1 = await cached_client.get("/api/s/default/rest/networkconf")
            assert result1["data"][0]["name"] == "Default"

            # POST -> flushes cache
            await cached_client.post(
                "/api/s/default/rest/networkconf",
                data={"name": "Default-Updated"},
            )

            # GET -> cache miss (flushed), fetches v2
            result2 = await cached_client.get("/api/s/default/rest/networkconf")
            assert result2["data"][0]["name"] == "Default-Updated"

        assert raw_client._client.request.await_count == 3

    @pytest.mark.asyncio
    async def test_manual_flush_forces_refetch(self) -> None:
        """Manual cache flush causes next GET to fetch from API again."""
        fixture = load_fixture("device_list.json")
        mock_resp1 = _mock_response(200, json_data=fixture)
        mock_resp2 = _mock_response(200, json_data=fixture)

        async with _make_gateway_client() as raw_client:
            raw_client._client.request = AsyncMock(side_effect=[mock_resp1, mock_resp2])
            cached_client, _ = _make_cached_client(raw_client)

            # First GET populates cache
            await cached_client.get("/api/s/default/stat/device")
            assert raw_client._client.request.await_count == 1

            # Flush and re-fetch
            await cached_client.flush("/api/s/default/stat/device")
            await cached_client.get("/api/s/default/stat/device")
            assert raw_client._client.request.await_count == 2

    @pytest.mark.asyncio
    async def test_events_bypass_cache_in_full_stack(self) -> None:
        """stat/event has TTL=0; every call should hit the API."""
        fixture = load_fixture("event_list.json")
        mock_resp1 = _mock_response(200, json_data=fixture)
        mock_resp2 = _mock_response(200, json_data=fixture)

        async with _make_gateway_client() as raw_client:
            raw_client._client.request = AsyncMock(side_effect=[mock_resp1, mock_resp2])
            cached_client, _ = _make_cached_client(raw_client)

            await cached_client.get("/api/s/default/stat/event")
            await cached_client.get("/api/s/default/stat/event")

        assert raw_client._client.request.await_count == 2


# ===========================================================================
# 3. Error flow integration
# ===========================================================================


class TestErrorFlowIntegration:
    """Integration tests for error propagation through the full stack."""

    @pytest.mark.asyncio
    async def test_401_raises_authentication_error(self) -> None:
        """401 from API propagates as AuthenticationError through all layers."""
        mock_resp = _mock_response(401, text="Unauthorized")

        async with _make_gateway_client() as raw_client:
            raw_client._client.request = AsyncMock(return_value=mock_resp)

            with pytest.raises(AuthenticationError) as exc_info:
                await raw_client.get("/api/s/default/stat/device")

        assert exc_info.value.status_code == 401
        assert "UNIFI_LOCAL_KEY" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_401_propagates_through_cached_client(self) -> None:
        """AuthenticationError propagates through the cached client wrapper."""
        mock_resp = _mock_response(401, text="Unauthorized")

        async with _make_gateway_client() as raw_client:
            raw_client._client.request = AsyncMock(return_value=mock_resp)
            cached_client, cache = _make_cached_client(raw_client)

            with pytest.raises(AuthenticationError):
                await cached_client.get("/api/s/default/stat/device")

        # Error should not be cached
        assert cache.stats["size"] == 0

    @pytest.mark.asyncio
    async def test_403_raises_authentication_error(self) -> None:
        """403 from API propagates as AuthenticationError."""
        mock_resp = _mock_response(403, text="Forbidden")

        async with _make_gateway_client() as raw_client:
            raw_client._client.request = AsyncMock(return_value=mock_resp)

            with pytest.raises(AuthenticationError) as exc_info:
                await raw_client.get("/api/s/default/stat/device")

        assert exc_info.value.status_code == 401  # AuthenticationError always uses 401
        assert "permissions" in str(exc_info.value).lower() or "Forbidden" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_500_raises_api_error(self) -> None:
        """500 from API propagates as APIError through all layers."""
        mock_resp = _mock_response(500, text="Internal Server Error")

        async with _make_gateway_client() as raw_client:
            raw_client._client.request = AsyncMock(return_value=mock_resp)

            with pytest.raises(APIError) as exc_info:
                await raw_client.get("/api/s/default/stat/device")

        assert exc_info.value.status_code == 500

    @pytest.mark.asyncio
    async def test_502_raises_api_error(self) -> None:
        """502 Bad Gateway propagates as APIError."""
        mock_resp = _mock_response(502, text="Bad Gateway")

        async with _make_gateway_client() as raw_client:
            raw_client._client.request = AsyncMock(return_value=mock_resp)

            with pytest.raises(APIError) as exc_info:
                await raw_client.get("/api/s/default/stat/device")

        assert exc_info.value.status_code == 502

    @pytest.mark.asyncio
    async def test_5xx_propagates_through_cached_client(self) -> None:
        """APIError from 5xx propagates through cached client."""
        mock_resp = _mock_response(503, text="Service Unavailable")

        async with _make_gateway_client() as raw_client:
            raw_client._client.request = AsyncMock(return_value=mock_resp)
            cached_client, cache = _make_cached_client(raw_client)

            with pytest.raises(APIError) as exc_info:
                await cached_client.get("/api/s/default/stat/device")

        assert exc_info.value.status_code == 503
        assert cache.stats["size"] == 0

    @pytest.mark.asyncio
    async def test_api_error_envelope_raises_api_error(self) -> None:
        """API error envelope (meta.rc == 'error') raises APIError via normalization."""
        error_envelope: dict[str, Any] = {
            "data": [],
            "meta": {"rc": "error", "msg": "api.err.Invalid"},
        }
        mock_resp = _mock_response(200, json_data=error_envelope)

        async with _make_gateway_client() as raw_client:
            raw_client._client.request = AsyncMock(return_value=mock_resp)

            # get() returns raw envelope -- no error
            raw = await raw_client.get("/api/s/default/stat/device")
            assert raw["meta"]["rc"] == "error"

            # get_normalized() detects the error envelope and raises
            raw_client._client.request = AsyncMock(return_value=mock_resp)
            with pytest.raises(APIError, match=r"api.err.Invalid"):
                await raw_client.get_normalized("/api/s/default/stat/device")

    @pytest.mark.asyncio
    async def test_api_error_envelope_through_cached_client(self) -> None:
        """Error envelope through cached client: raw envelope is cached but
        normalization raises when applied."""
        error_envelope: dict[str, Any] = {
            "data": [],
            "meta": {"rc": "error", "msg": "api.err.NoSite"},
        }
        mock_resp = _mock_response(200, json_data=error_envelope)

        async with _make_gateway_client() as raw_client:
            raw_client._client.request = AsyncMock(return_value=mock_resp)
            cached_client, _ = _make_cached_client(raw_client)

            # Cached GET returns the raw envelope (200 OK at HTTP level)
            result = await cached_client.get("/api/s/default/stat/device")
            assert result["meta"]["rc"] == "error"

            # But normalization catches the error
            with pytest.raises(APIError, match=r"api.err.NoSite"):
                normalize_response(result)

    @pytest.mark.asyncio
    async def test_connection_timeout_raises_network_error(self) -> None:
        """Connection timeout propagates as NetworkError."""
        async with _make_gateway_client() as raw_client:
            raw_client._client.request = AsyncMock(
                side_effect=httpx.ConnectTimeout("Connection timed out")
            )

            with pytest.raises(NetworkError) as exc_info:
                await raw_client.get("/api/s/default/stat/device")

        assert "timed out" in exc_info.value.message.lower()

    @pytest.mark.asyncio
    async def test_timeout_propagates_through_cached_client(self) -> None:
        """NetworkError from timeout propagates through cached client."""
        async with _make_gateway_client() as raw_client:
            raw_client._client.request = AsyncMock(
                side_effect=httpx.ConnectTimeout("Connection timed out")
            )
            cached_client, cache = _make_cached_client(raw_client)

            with pytest.raises(NetworkError):
                await cached_client.get("/api/s/default/stat/device")

        assert cache.stats["size"] == 0

    @pytest.mark.asyncio
    async def test_connection_refused_raises_network_error(self) -> None:
        """Connection refused propagates as NetworkError."""
        async with _make_gateway_client() as raw_client:
            raw_client._client.request = AsyncMock(
                side_effect=httpx.ConnectError("Connection refused")
            )

            with pytest.raises(NetworkError) as exc_info:
                await raw_client.get("/api/s/default/stat/device")

        assert "refused" in exc_info.value.message.lower()

    @pytest.mark.asyncio
    async def test_read_timeout_raises_network_error(self) -> None:
        """Read timeout raises NetworkError."""
        async with _make_gateway_client() as raw_client:
            raw_client._client.request = AsyncMock(side_effect=httpx.ReadTimeout("Read timed out"))

            with pytest.raises(NetworkError):
                await raw_client.get("/api/s/default/stat/device")

    @pytest.mark.asyncio
    async def test_error_after_cached_success_refetches(self) -> None:
        """If API errors after a cached success + flush, error propagates."""
        fixture = load_fixture("device_list.json")
        mock_resp_ok = _mock_response(200, json_data=fixture)
        mock_resp_err = _mock_response(500, text="Internal Server Error")

        async with _make_gateway_client() as raw_client:
            raw_client._client.request = AsyncMock(side_effect=[mock_resp_ok, mock_resp_err])
            cached_client, _ = _make_cached_client(raw_client)

            # First call succeeds and gets cached
            result = await cached_client.get("/api/s/default/stat/device")
            assert result["meta"]["rc"] == "ok"

            # Flush and try again -- API now returns 500
            await cached_client.flush()
            with pytest.raises(APIError) as exc_info:
                await cached_client.get("/api/s/default/stat/device")
            assert exc_info.value.status_code == 500


# ===========================================================================
# 4. Pagination integration
# ===========================================================================


class TestPaginationIntegration:
    """Integration tests for get_all() with multi-page responses."""

    @pytest.mark.asyncio
    async def test_get_all_single_page_no_pagination(self) -> None:
        """Endpoint without totalCount returns single page as-is."""
        fixture = load_fixture("device_list.json")
        mock_resp = _mock_response(200, json_data=fixture)

        async with _make_gateway_client() as client:
            client._client.request = AsyncMock(return_value=mock_resp)
            result = await client.get_all("/api/s/default/stat/device")

        assert isinstance(result, NormalizedResponse)
        assert result.count == 3
        assert result.total_count is None  # No pagination

    @pytest.mark.asyncio
    async def test_get_all_multi_page(self) -> None:
        """get_all() fetches multiple pages and combines results."""
        # Simulate 5 total items across 2 pages of size 3
        page1: dict[str, Any] = {
            "data": [
                {"_id": "1", "mac": "aa:aa:aa:aa:aa:01", "name": "D1"},
                {"_id": "2", "mac": "aa:aa:aa:aa:aa:02", "name": "D2"},
                {"_id": "3", "mac": "aa:aa:aa:aa:aa:03", "name": "D3"},
            ],
            "meta": {"rc": "ok"},
            "count": 3,
            "totalCount": 5,
        }
        page2: dict[str, Any] = {
            "data": [
                {"_id": "4", "mac": "aa:aa:aa:aa:aa:04", "name": "D4"},
                {"_id": "5", "mac": "aa:aa:aa:aa:aa:05", "name": "D5"},
            ],
            "meta": {"rc": "ok"},
            "count": 2,
            "totalCount": 5,
        }

        mock_resp1 = _mock_response(200, json_data=page1)
        mock_resp2 = _mock_response(200, json_data=page2)

        async with _make_gateway_client() as client:
            client._client.request = AsyncMock(side_effect=[mock_resp1, mock_resp2])
            result = await client.get_all("/api/s/default/stat/device", page_size=3)

        assert isinstance(result, NormalizedResponse)
        assert result.count == 5
        assert result.total_count == 5
        assert len(result.data) == 5
        ids = [d["_id"] for d in result.data]
        assert ids == ["1", "2", "3", "4", "5"]

    @pytest.mark.asyncio
    async def test_get_all_preserves_query_params(self) -> None:
        """get_all() forwards base query params and adds pagination params."""
        page: dict[str, Any] = {
            "data": [{"_id": "1"}],
            "meta": {"rc": "ok"},
        }
        mock_resp = _mock_response(200, json_data=page)

        async with _make_gateway_client() as client:
            client._client.request = AsyncMock(return_value=mock_resp)
            await client.get_all(
                "/api/s/default/stat/sta",
                params={"type": "all"},
                page_size=50,
            )

        call_kwargs = client._client.request.call_args
        params = call_kwargs.kwargs["params"]
        assert params["type"] == "all"
        assert params["offset"] == 0
        assert params["limit"] == 50

    @pytest.mark.asyncio
    async def test_get_all_stops_on_empty_page(self) -> None:
        """get_all() stops when an empty data page is received."""
        page1: dict[str, Any] = {
            "data": [{"_id": "1"}],
            "meta": {"rc": "ok"},
            "count": 1,
            "totalCount": 10,  # Claims 10, but next page is empty
        }
        page2: dict[str, Any] = {
            "data": [],
            "meta": {"rc": "ok"},
            "count": 0,
            "totalCount": 10,
        }

        mock_resp1 = _mock_response(200, json_data=page1)
        mock_resp2 = _mock_response(200, json_data=page2)

        async with _make_gateway_client() as client:
            client._client.request = AsyncMock(side_effect=[mock_resp1, mock_resp2])
            result = await client.get_all("/api/s/default/stat/device", page_size=5)

        assert result.count == 1
        assert result.total_count == 10

    @pytest.mark.asyncio
    async def test_get_all_error_on_second_page_propagates(self) -> None:
        """Error during pagination propagates correctly."""
        page1: dict[str, Any] = {
            "data": [{"_id": "1"}],
            "meta": {"rc": "ok"},
            "count": 1,
            "totalCount": 5,
        }
        mock_resp1 = _mock_response(200, json_data=page1)
        mock_resp_err = _mock_response(500, text="Internal Server Error")

        async with _make_gateway_client() as client:
            client._client.request = AsyncMock(side_effect=[mock_resp1, mock_resp_err])
            with pytest.raises(APIError) as exc_info:
                await client.get_all("/api/s/default/stat/device", page_size=1)
            assert exc_info.value.status_code == 500


# ===========================================================================
# 5. Fixture validation
# ===========================================================================


class TestFixtureValidation:
    """Validate that all fixture files load correctly and parse into models."""

    def test_device_list_fixture_structure(self) -> None:
        """device_list.json has expected envelope and data structure."""
        data = load_fixture("device_list.json")
        assert data["meta"]["rc"] == "ok"
        assert isinstance(data["data"], list)
        assert len(data["data"]) == 3

        for device in data["data"]:
            assert "_id" in device
            assert "mac" in device
            assert "model" in device
            assert "state" in device

    def test_device_single_fixture_structure(self) -> None:
        """device_single.json has expected envelope and single-item data."""
        data = load_fixture("device_single.json")
        assert data["meta"]["rc"] == "ok"
        assert len(data["data"]) == 1
        device = data["data"][0]
        assert "port_table" in device
        assert len(device["port_table"]) == 6

    def test_client_list_fixture_structure(self) -> None:
        """client_list.json has expected envelope and client data."""
        data = load_fixture("client_list.json")
        assert data["meta"]["rc"] == "ok"
        assert len(data["data"]) == 6

        for client in data["data"]:
            assert "mac" in client
            assert "ip" in client
            assert "network_id" in client

    def test_client_list_fixture_parses_into_models(self) -> None:
        """All clients in fixture can be parsed into Client models."""
        data = load_fixture("client_list.json")
        for item in data["data"]:
            client = Client.model_validate(item)
            assert client.client_mac
            assert client.ip

    def test_vlan_config_fixture_structure(self) -> None:
        """vlan_config.json has expected envelope and VLAN data."""
        data = load_fixture("vlan_config.json")
        assert data["meta"]["rc"] == "ok"
        assert len(data["data"]) == 4

        for vlan in data["data"]:
            assert "_id" in vlan
            assert "name" in vlan

    def test_vlan_config_fixture_parses_into_models(self) -> None:
        """All VLANs in fixture can be parsed into VLAN models."""
        data = load_fixture("vlan_config.json")
        for item in data["data"]:
            vlan = VLAN.model_validate(item)
            assert vlan.vlan_id
            assert vlan.name

    def test_health_fixture_structure(self) -> None:
        """health.json has expected envelope and subsystem data."""
        data = load_fixture("health.json")
        assert data["meta"]["rc"] == "ok"
        assert isinstance(data["data"], list)

        subsystems = {item["subsystem"] for item in data["data"]}
        assert "wan" in subsystems
        assert "lan" in subsystems
        assert "wlan" in subsystems
        assert "www" in subsystems

    def test_event_list_fixture_structure(self) -> None:
        """event_list.json has expected envelope and event data."""
        data = load_fixture("event_list.json")
        assert data["meta"]["rc"] == "ok"
        assert len(data["data"]) == 6

        for event in data["data"]:
            assert "key" in event
            assert "msg" in event
            assert "datetime" in event

    def test_event_list_fixture_parses_into_models(self) -> None:
        """All events in fixture can be parsed into Event models."""
        data = load_fixture("event_list.json")
        for item in data["data"]:
            event = Event.model_validate(item)
            assert event.type
            assert event.message

    def test_firmware_status_fixture_structure(self) -> None:
        """firmware_status.json has expected envelope and firmware data."""
        data = load_fixture("firmware_status.json")
        assert data["meta"]["rc"] == "ok"
        assert len(data["data"]) == 3

        for device in data["data"]:
            assert "_id" in device
            assert "model" in device
            assert "version" in device

    def test_firmware_status_fixture_parses_into_models(self) -> None:
        """All devices in firmware fixture can be parsed into FirmwareStatus."""
        data = load_fixture("firmware_status.json")
        for item in data["data"]:
            fw = FirmwareStatus.model_validate(item)
            assert fw.device_id
            assert fw.current_version

    def test_all_fixtures_have_ok_meta(self) -> None:
        """Every fixture file has meta.rc == 'ok'."""
        fixture_files = [
            "device_list.json",
            "device_single.json",
            "client_list.json",
            "event_list.json",
            "vlan_config.json",
            "health.json",
            "firmware_status.json",
        ]
        for name in fixture_files:
            data = load_fixture(name)
            assert data["meta"]["rc"] == "ok", f"{name} does not have meta.rc == 'ok'"

    def test_all_fixtures_normalize_without_error(self) -> None:
        """Every fixture file can be normalized without raising."""
        fixture_files = [
            "device_list.json",
            "device_single.json",
            "client_list.json",
            "event_list.json",
            "vlan_config.json",
            "health.json",
            "firmware_status.json",
        ]
        for name in fixture_files:
            data = load_fixture(name)
            normalized = normalize_response(data)
            assert isinstance(normalized, NormalizedResponse)
            assert normalized.count > 0, f"{name} normalized to empty data"
