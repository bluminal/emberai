"""Tests for OPNsense 26.x DNS endpoint compatibility.

Validates that DNS tools use the correct 26.x Unbound settings controller
endpoints and handle edge cases including:

- Correct 26.x endpoint paths (settings controller, not host/forward controllers)
- Pagination parameters on all search calls
- Graceful 404 degradation when Unbound is not installed
- Non-404 API errors propagate correctly
- Write operations use the 26.x payload format (host key)
- Model validation with the 26.x 'enabled' field
- Multiple overrides, disabled entries, missing optional fields
"""

from __future__ import annotations

import os
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from opnsense.errors import APIError
from opnsense.models.services import DNSOverride


def _make_client(get_returns: dict[str, Any] | None = None) -> AsyncMock:
    """Create a mock OPNsenseClient with configurable GET response."""
    client = AsyncMock()
    if get_returns is not None:
        client.get = AsyncMock(return_value=get_returns)
    client.write = AsyncMock(return_value={"result": "saved", "uuid": "new-uuid"})
    client.reconfigure = AsyncMock(return_value={"status": "ok"})
    return client


def _make_404_client() -> AsyncMock:
    """Create a mock client that returns 404 on GET (Unbound not installed)."""
    client = AsyncMock()
    client.get = AsyncMock(
        side_effect=APIError(
            "Not found (404)",
            status_code=404,
            endpoint="/api/unbound/settings/searchHostOverride",
        )
    )
    client.write = AsyncMock(return_value={"result": "saved", "uuid": "new-uuid"})
    client.reconfigure = AsyncMock(return_value={"status": "ok"})
    return client


def _make_500_client() -> AsyncMock:
    """Create a mock client that returns 500 on GET."""
    client = AsyncMock()
    client.get = AsyncMock(
        side_effect=APIError(
            "Server error (500)",
            status_code=500,
            endpoint="/api/unbound/settings/searchHostOverride",
        )
    )
    return client


# ---------------------------------------------------------------------------
# 26.x endpoint verification
# ---------------------------------------------------------------------------


class TestDNSEndpoint26x:
    """Verify all DNS tools use the correct OPNsense 26.x endpoints."""

    @pytest.mark.asyncio
    async def test_get_overrides_uses_settings_controller(self) -> None:
        from opnsense.tools.services import opnsense__services__get_dns_overrides

        client = _make_client({"rows": []})
        await opnsense__services__get_dns_overrides(client)

        client.get.assert_called_once_with(
            "unbound",
            "settings",
            "searchHostOverride",
            params={"rowCount": -1, "current": 1},
        )

    @pytest.mark.asyncio
    async def test_get_forwarders_uses_settings_controller(self) -> None:
        from opnsense.tools.services import opnsense__services__get_dns_forwarders

        client = _make_client({"rows": []})
        await opnsense__services__get_dns_forwarders(client)

        client.get.assert_called_once_with(
            "unbound",
            "settings",
            "searchDomainOverride",
            params={"rowCount": -1, "current": 1},
        )

    @pytest.mark.asyncio
    async def test_add_override_uses_settings_controller(self) -> None:
        from opnsense.tools.services import opnsense__services__add_dns_override

        client = _make_client()

        with patch.dict(os.environ, {"OPNSENSE_WRITE_ENABLED": "true"}):
            await opnsense__services__add_dns_override(
                client,
                "test",
                "home.local",
                "10.0.0.1",
                apply=True,
            )

        client.write.assert_called_once_with(
            "unbound",
            "settings",
            "addHostOverride",
            data={
                "host": {
                    "enabled": "1",
                    "hostname": "test",
                    "domain": "home.local",
                    "rr": "A",
                    "server": "10.0.0.1",
                    "description": "",
                }
            },
        )

    @pytest.mark.asyncio
    async def test_reconfigure_uses_service_controller(self) -> None:
        """Reconfigure should still use /api/unbound/service/reconfigure."""
        from opnsense.tools.services import opnsense__services__add_dns_override

        client = _make_client()

        with patch.dict(os.environ, {"OPNSENSE_WRITE_ENABLED": "true"}):
            await opnsense__services__add_dns_override(
                client,
                "test",
                "home.local",
                "10.0.0.1",
                apply=True,
            )

        client.reconfigure.assert_called_once_with("unbound", "service")


# ---------------------------------------------------------------------------
# Graceful 404 degradation
# ---------------------------------------------------------------------------


class TestDNS404Degradation:
    """When Unbound is not installed, 404s return empty results."""

    @pytest.mark.asyncio
    async def test_get_overrides_404_returns_empty(self) -> None:
        from opnsense.tools.services import opnsense__services__get_dns_overrides

        client = _make_404_client()
        result = await opnsense__services__get_dns_overrides(client)
        assert result == []

    @pytest.mark.asyncio
    async def test_get_forwarders_404_returns_empty(self) -> None:
        from opnsense.tools.services import opnsense__services__get_dns_forwarders

        client = _make_404_client()
        result = await opnsense__services__get_dns_forwarders(client)
        assert result == []

    @pytest.mark.asyncio
    async def test_get_overrides_500_propagates(self) -> None:
        from opnsense.tools.services import opnsense__services__get_dns_overrides

        client = _make_500_client()
        with pytest.raises(APIError) as exc_info:
            await opnsense__services__get_dns_overrides(client)
        assert exc_info.value.status_code == 500

    @pytest.mark.asyncio
    async def test_get_forwarders_500_propagates(self) -> None:
        from opnsense.tools.services import opnsense__services__get_dns_forwarders

        client = _make_500_client()
        with pytest.raises(APIError) as exc_info:
            await opnsense__services__get_dns_forwarders(client)
        assert exc_info.value.status_code == 500

    @pytest.mark.asyncio
    async def test_get_overrides_401_propagates(self) -> None:
        """Auth errors should propagate, not be swallowed."""
        from opnsense.tools.services import opnsense__services__get_dns_overrides

        client = AsyncMock()
        client.get = AsyncMock(
            side_effect=APIError(
                "Auth failed",
                status_code=401,
                endpoint="/api/unbound/settings/searchHostOverride",
            )
        )

        with pytest.raises(APIError) as exc_info:
            await opnsense__services__get_dns_overrides(client)
        assert exc_info.value.status_code == 401


# ---------------------------------------------------------------------------
# 26.x response parsing
# ---------------------------------------------------------------------------


class TestDNS26xResponseParsing:
    """Verify parsing of 26.x style responses with enabled field."""

    @pytest.mark.asyncio
    async def test_multiple_overrides_with_enabled_field(self) -> None:
        from opnsense.tools.services import opnsense__services__get_dns_overrides

        data = {
            "rows": [
                {
                    "uuid": "dns-1",
                    "hostname": "nas",
                    "domain": "home.local",
                    "server": "192.168.1.200",
                    "description": "Network storage",
                    "enabled": "1",
                },
                {
                    "uuid": "dns-2",
                    "hostname": "printer",
                    "domain": "home.local",
                    "server": "192.168.1.201",
                    "description": "HP LaserJet",
                    "enabled": "1",
                },
                {
                    "uuid": "dns-3",
                    "hostname": "old-server",
                    "domain": "home.local",
                    "server": "192.168.1.202",
                    "description": "Decommissioned",
                    "enabled": "0",
                },
            ],
        }
        client = _make_client(data)

        overrides = await opnsense__services__get_dns_overrides(client)

        assert len(overrides) == 3
        assert overrides[0]["hostname"] == "nas"
        assert overrides[0]["enabled"] == "1"
        assert overrides[2]["hostname"] == "old-server"
        assert overrides[2]["enabled"] == "0"

    @pytest.mark.asyncio
    async def test_override_without_enabled_field_defaults(self) -> None:
        """Overrides missing 'enabled' should default to '1'."""
        from opnsense.tools.services import opnsense__services__get_dns_overrides

        data = {
            "rows": [
                {
                    "uuid": "dns-1",
                    "hostname": "nas",
                    "domain": "home.local",
                    "server": "192.168.1.200",
                    "description": "NAS",
                    # no 'enabled' field
                },
            ],
        }
        client = _make_client(data)

        overrides = await opnsense__services__get_dns_overrides(client)

        assert len(overrides) == 1
        assert overrides[0]["enabled"] == "1"  # default

    @pytest.mark.asyncio
    async def test_override_ip_alias_works(self) -> None:
        """The 'server' field in API response should map to 'ip' in model."""
        from opnsense.tools.services import opnsense__services__get_dns_overrides

        data = {
            "rows": [
                {
                    "uuid": "dns-1",
                    "hostname": "test",
                    "domain": "local",
                    "server": "10.0.0.50",
                    "description": "",
                    "enabled": "1",
                },
            ],
        }
        client = _make_client(data)

        overrides = await opnsense__services__get_dns_overrides(client)

        assert overrides[0]["ip"] == "10.0.0.50"
        # 'server' should not appear as a separate key in model_dump()
        assert "server" not in overrides[0]


# ---------------------------------------------------------------------------
# DNSOverride model tests
# ---------------------------------------------------------------------------


class TestDNSOverrideModel:
    """Unit tests for the DNSOverride Pydantic model."""

    def test_model_validates_full_26x_response(self) -> None:
        data = {
            "uuid": "abc-123",
            "hostname": "nas",
            "domain": "home.local",
            "server": "192.168.1.200",
            "description": "NAS",
            "enabled": "1",
        }
        override = DNSOverride.model_validate(data)
        assert override.uuid == "abc-123"
        assert override.hostname == "nas"
        assert override.domain == "home.local"
        assert override.ip == "192.168.1.200"
        assert override.description == "NAS"
        assert override.enabled == "1"

    def test_model_defaults_enabled_to_1(self) -> None:
        data = {
            "uuid": "abc-123",
            "hostname": "nas",
        }
        override = DNSOverride.model_validate(data)
        assert override.enabled == "1"

    def test_model_dump_uses_ip_not_server(self) -> None:
        data = {
            "uuid": "abc-123",
            "hostname": "nas",
            "server": "10.0.0.1",
        }
        override = DNSOverride.model_validate(data)
        dumped = override.model_dump()
        assert dumped["ip"] == "10.0.0.1"
        assert "server" not in dumped

    def test_model_dump_includes_enabled(self) -> None:
        data = {
            "uuid": "abc-123",
            "hostname": "nas",
            "enabled": "0",
        }
        override = DNSOverride.model_validate(data)
        dumped = override.model_dump()
        assert dumped["enabled"] == "0"


# ---------------------------------------------------------------------------
# Write operation payload format
# ---------------------------------------------------------------------------


class TestDNSWritePayload26x:
    """Verify the write operation uses the 26.x payload format."""

    @pytest.mark.asyncio
    async def test_write_payload_uses_host_key(self) -> None:
        from opnsense.tools.services import opnsense__services__add_dns_override

        client = _make_client()

        with patch.dict(os.environ, {"OPNSENSE_WRITE_ENABLED": "true"}):
            await opnsense__services__add_dns_override(
                client,
                "camera",
                "iot.local",
                "10.10.10.50",
                description="Front door cam",
                apply=True,
            )

        write_call = client.write.call_args
        data = write_call[1]["data"]

        # Must use 'host' key (26.x actual API format)
        assert "host" in data

        payload = data["host"]
        assert payload["hostname"] == "camera"
        assert payload["domain"] == "iot.local"
        assert payload["rr"] == "A"
        assert payload["server"] == "10.10.10.50"
        assert payload["description"] == "Front door cam"
        assert payload["enabled"] == "1"

    @pytest.mark.asyncio
    async def test_write_returns_fqdn(self) -> None:
        from opnsense.tools.services import opnsense__services__add_dns_override

        client = _make_client()

        with patch.dict(os.environ, {"OPNSENSE_WRITE_ENABLED": "true"}):
            result = await opnsense__services__add_dns_override(
                client,
                "camera",
                "iot.local",
                "10.10.10.50",
                apply=True,
            )

        assert result["fqdn"] == "camera.iot.local"
        assert result["hostname"] == "camera"
        assert result["domain"] == "iot.local"
        assert result["ip"] == "10.10.10.50"

    @pytest.mark.asyncio
    async def test_write_empty_description_default(self) -> None:
        from opnsense.tools.services import opnsense__services__add_dns_override

        client = _make_client()

        with patch.dict(os.environ, {"OPNSENSE_WRITE_ENABLED": "true"}):
            await opnsense__services__add_dns_override(
                client,
                "test",
                "local",
                "1.2.3.4",
                apply=True,
            )

        write_call = client.write.call_args
        data = write_call[1]["data"]
        assert data["host"]["description"] == ""

    @pytest.mark.asyncio
    async def test_write_then_reconfigure_sequence(self) -> None:
        """Write must happen before reconfigure."""
        from opnsense.tools.services import opnsense__services__add_dns_override

        call_order: list[str] = []
        client = AsyncMock()

        async def _track_write(*args: Any, **kwargs: Any) -> dict[str, Any]:
            call_order.append("write")
            return {"result": "saved", "uuid": "new-uuid"}

        async def _track_reconfig(*args: Any, **kwargs: Any) -> dict[str, Any]:
            call_order.append("reconfigure")
            return {"status": "ok"}

        client.write = AsyncMock(side_effect=_track_write)
        client.reconfigure = AsyncMock(side_effect=_track_reconfig)

        with patch.dict(os.environ, {"OPNSENSE_WRITE_ENABLED": "true"}):
            await opnsense__services__add_dns_override(
                client,
                "test",
                "local",
                "1.2.3.4",
                apply=True,
            )

        assert call_order == ["write", "reconfigure"]


# ---------------------------------------------------------------------------
# Resolve hostname (unchanged endpoint)
# ---------------------------------------------------------------------------


class TestResolveHostname26x:
    """Verify resolve_hostname still uses the diagnostics endpoint."""

    @pytest.mark.asyncio
    async def test_uses_diagnostics_endpoint(self) -> None:
        from opnsense.tools.services import opnsense__services__resolve_hostname

        result_data = {"address": "192.168.1.200"}
        client = _make_client(result_data)

        await opnsense__services__resolve_hostname(client, "nas.home.local")

        client.get.assert_called_once_with(
            "unbound",
            "diagnostics",
            "lookup/nas.home.local",
        )
