"""Tests for Services skill tools.

Covers:
- get_dns_overrides: fixture parsing
- get_dns_forwarders: basic retrieval
- resolve_hostname: parameter passing
- add_dns_override: write gate enforcement (env var + apply flag)
- get_dhcp_leases4: fixture parsing, interface filtering
- get_traffic_shaper: basic retrieval
"""

from __future__ import annotations

import os
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from opnsense.errors import WriteGateError
from opnsense.safety import WriteBlockReason
from tests.fixtures import load_fixture


def _make_client(get_returns: dict[str, Any] | None = None) -> AsyncMock:
    client = AsyncMock()
    if get_returns is not None:
        client.get = AsyncMock(return_value=get_returns)
    client.write = AsyncMock(return_value={"result": "saved", "uuid": "new-uuid"})
    client.reconfigure = AsyncMock(return_value={"status": "ok"})
    return client


# ---------------------------------------------------------------------------
# get_dns_overrides
# ---------------------------------------------------------------------------


class TestGetDNSOverrides:
    @pytest.mark.asyncio
    async def test_returns_parsed_overrides(self) -> None:
        from opnsense.tools.services import opnsense__services__get_dns_overrides

        data = {
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
        client = _make_client(data)

        overrides = await opnsense__services__get_dns_overrides(client)

        assert len(overrides) == 1
        assert overrides[0]["hostname"] == "nas"
        assert overrides[0]["ip"] == "192.168.1.200"
        assert overrides[0]["domain"] == "home.local"

    @pytest.mark.asyncio
    async def test_empty_response(self) -> None:
        from opnsense.tools.services import opnsense__services__get_dns_overrides

        client = _make_client({"rows": []})
        overrides = await opnsense__services__get_dns_overrides(client)
        assert overrides == []


# ---------------------------------------------------------------------------
# get_dns_forwarders
# ---------------------------------------------------------------------------


class TestGetDNSForwarders:
    @pytest.mark.asyncio
    async def test_returns_forwarders(self) -> None:
        from opnsense.tools.services import opnsense__services__get_dns_forwarders

        data = {
            "rows": [
                {"domain": ".", "server": "1.1.1.1", "port": "53"},
            ],
        }
        client = _make_client(data)

        forwarders = await opnsense__services__get_dns_forwarders(client)

        assert len(forwarders) == 1
        assert forwarders[0]["server"] == "1.1.1.1"
        client.get.assert_called_once_with("unbound", "forward", "searchForward")


# ---------------------------------------------------------------------------
# resolve_hostname
# ---------------------------------------------------------------------------


class TestResolveHostname:
    @pytest.mark.asyncio
    async def test_passes_hostname_to_api(self) -> None:
        from opnsense.tools.services import opnsense__services__resolve_hostname

        result_data = {"address": "192.168.1.200"}
        client = _make_client(result_data)

        result = await opnsense__services__resolve_hostname(client, "nas.home.local")

        assert result == result_data
        client.get.assert_called_once_with(
            "unbound", "diagnostics", "lookup/nas.home.local",
        )


# ---------------------------------------------------------------------------
# add_dns_override -- WRITE GATE TESTS
# ---------------------------------------------------------------------------


class TestAddDNSOverrideWriteGate:
    """Write gate enforcement on the DNS override write tool."""

    @pytest.mark.asyncio
    async def test_blocked_when_env_var_disabled(self) -> None:
        from opnsense.tools.services import opnsense__services__add_dns_override

        client = _make_client()

        with patch.dict(os.environ, {}, clear=True):
            with pytest.raises(WriteGateError) as exc_info:
                await opnsense__services__add_dns_override(
                    client, "test", "home.local", "1.2.3.4", apply=True,
                )
            assert exc_info.value.reason == WriteBlockReason.ENV_VAR_DISABLED

    @pytest.mark.asyncio
    async def test_blocked_when_apply_false(self) -> None:
        from opnsense.tools.services import opnsense__services__add_dns_override

        client = _make_client()

        with patch.dict(os.environ, {"OPNSENSE_WRITE_ENABLED": "true"}):
            with pytest.raises(WriteGateError) as exc_info:
                await opnsense__services__add_dns_override(
                    client, "test", "home.local", "1.2.3.4", apply=False,
                )
            assert exc_info.value.reason == WriteBlockReason.APPLY_FLAG_MISSING

    @pytest.mark.asyncio
    async def test_blocked_when_apply_not_provided(self) -> None:
        from opnsense.tools.services import opnsense__services__add_dns_override

        client = _make_client()

        with patch.dict(os.environ, {"OPNSENSE_WRITE_ENABLED": "true"}):
            with pytest.raises(WriteGateError) as exc_info:
                await opnsense__services__add_dns_override(
                    client, "test", "home.local", "1.2.3.4",
                )
            assert exc_info.value.reason == WriteBlockReason.APPLY_FLAG_MISSING

    @pytest.mark.asyncio
    async def test_succeeds_when_gates_pass(self) -> None:
        from opnsense.tools.services import opnsense__services__add_dns_override

        client = _make_client()

        with patch.dict(os.environ, {"OPNSENSE_WRITE_ENABLED": "true"}):
            result = await opnsense__services__add_dns_override(
                client, "test", "home.local", "1.2.3.4",
                description="Test entry", apply=True,
            )

        assert result["hostname"] == "test"
        assert result["domain"] == "home.local"
        assert result["ip"] == "1.2.3.4"
        assert result["fqdn"] == "test.home.local"
        assert "write_result" in result
        assert "reconfigure_result" in result

        # Verify write was called with correct payload
        client.write.assert_called_once()
        call_args = client.write.call_args
        assert call_args[0] == ("unbound", "host", "addHost")
        data = call_args[1]["data"]
        assert data["host"]["hostname"] == "test"
        assert data["host"]["server"] == "1.2.3.4"

    @pytest.mark.asyncio
    async def test_reconfigure_called_after_write(self) -> None:
        from opnsense.tools.services import opnsense__services__add_dns_override

        client = _make_client()

        with patch.dict(os.environ, {"OPNSENSE_WRITE_ENABLED": "true"}):
            await opnsense__services__add_dns_override(
                client, "test", "home.local", "1.2.3.4", apply=True,
            )

        client.reconfigure.assert_called_once_with("unbound", "service")


# ---------------------------------------------------------------------------
# get_dhcp_leases4
# ---------------------------------------------------------------------------


class TestGetDHCPLeases4:
    @pytest.mark.asyncio
    async def test_returns_all_leases(self) -> None:
        from opnsense.tools.services import opnsense__services__get_dhcp_leases4

        fixture = load_fixture("dhcp_leases.json")
        client = _make_client(fixture)

        leases = await opnsense__services__get_dhcp_leases4(client)

        assert len(leases) == 5
        client.get.assert_called_once_with("kea", "leases4", "search")

    @pytest.mark.asyncio
    async def test_normalizes_field_names(self) -> None:
        from opnsense.tools.services import opnsense__services__get_dhcp_leases4

        fixture = load_fixture("dhcp_leases.json")
        client = _make_client(fixture)

        leases = await opnsense__services__get_dhcp_leases4(client)

        first = leases[0]
        assert first["mac"] == "a4:83:e7:11:22:33"
        assert first["ip"] == "192.168.1.101"
        assert first["hostname"] == "macbook-pro-jdoe"
        assert first["state"] == "active"

    @pytest.mark.asyncio
    async def test_filter_by_interface(self) -> None:
        from opnsense.tools.services import opnsense__services__get_dhcp_leases4

        fixture = load_fixture("dhcp_leases.json")
        client = _make_client(fixture)

        leases = await opnsense__services__get_dhcp_leases4(
            client, interface="igb1_vlan30",
        )

        # Only leases on igb1_vlan30
        assert len(leases) == 2
        for lease in leases:
            assert lease["interface"] == "igb1_vlan30"

    @pytest.mark.asyncio
    async def test_filter_by_interface_no_match(self) -> None:
        from opnsense.tools.services import opnsense__services__get_dhcp_leases4

        fixture = load_fixture("dhcp_leases.json")
        client = _make_client(fixture)

        leases = await opnsense__services__get_dhcp_leases4(
            client, interface="nonexistent",
        )

        assert leases == []

    @pytest.mark.asyncio
    async def test_includes_expired_leases(self) -> None:
        from opnsense.tools.services import opnsense__services__get_dhcp_leases4

        fixture = load_fixture("dhcp_leases.json")
        client = _make_client(fixture)

        leases = await opnsense__services__get_dhcp_leases4(client)

        expired = [l for l in leases if l["state"] == "expired"]
        assert len(expired) >= 1


# ---------------------------------------------------------------------------
# get_traffic_shaper
# ---------------------------------------------------------------------------


class TestGetTrafficShaper:
    @pytest.mark.asyncio
    async def test_returns_settings(self) -> None:
        from opnsense.tools.services import opnsense__services__get_traffic_shaper

        settings = {"pipes": [], "queues": [], "rules": []}
        client = _make_client(settings)

        result = await opnsense__services__get_traffic_shaper(client)

        assert result == settings
        client.get.assert_called_once_with(
            "trafficshaper", "settings", "getSettings",
        )
