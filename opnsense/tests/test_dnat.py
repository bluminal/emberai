# SPDX-License-Identifier: MIT
"""Tests for DNAT port forward tools (Task 193).

Covers:
- list_port_forwards: success, empty, boolean coercion
- add_port_forward: success, invalid protocol, empty target, empty port,
  write gate, apply called, cache flushed
- delete_port_forward: success, write gate, apply called, cache flushed

Test strategy:
- Mock OPNsenseClient at the _get_client factory level
- Verify payloads sent to client.write / client.post
- Verify write gate enforcement (env var + apply flag)
- Verify d_nat/apply called after every write
- Verify cache flush called after every write
"""

from __future__ import annotations

import os
from typing import Any
from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest

from opnsense.errors import APIError, ValidationError, WriteGateError, WriteGateReason


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_mock_client(**kwargs: Any) -> MagicMock:
    """Create a mocked OPNsenseClient with sensible defaults."""
    from opnsense.api.opnsense_client import OPNsenseClient

    client = MagicMock(spec=OPNsenseClient)
    client.close = AsyncMock()
    client.get = AsyncMock(return_value=kwargs.get("get_response", {}))
    client.get_cached = AsyncMock(return_value=kwargs.get("get_cached_response", {}))
    client.write = AsyncMock(
        return_value=kwargs.get(
            "write_response", {"result": "saved", "uuid": "dnat-uuid-1234"}
        )
    )
    client.post = AsyncMock(return_value=kwargs.get("post_response", {}))
    client.reconfigure = AsyncMock(return_value={"status": "ok"})
    client.cache = MagicMock()
    client.cache.flush_by_prefix = AsyncMock()
    return client


@pytest.fixture()
def mock_client() -> MagicMock:
    return _make_mock_client()


@pytest.fixture(autouse=True)
def _enable_writes():
    """Enable writes by default -- individual tests can override."""
    with patch.dict(os.environ, {"OPNSENSE_WRITE_ENABLED": "true"}):
        yield


# ===========================================================================
# list_port_forwards tests
# ===========================================================================


class TestListPortForwards:
    """opnsense__firewall__list_port_forwards -- read DNAT rules."""

    async def test_list_port_forwards_success(self) -> None:
        """List returns mapped fields from two DNAT rules."""
        api_response = {
            "rows": [
                {
                    "uuid": "pf-uuid-1",
                    "interface": "wan",
                    "protocol": "TCP",
                    "src_network": "any",
                    "src_port": "",
                    "dst_network": "wanip",
                    "dst_port": "443",
                    "target": "192.168.1.10",
                    "local_port": "8443",
                    "descr": "HTTPS forward",
                    "enabled": "1",
                    "log": "0",
                },
                {
                    "uuid": "pf-uuid-2",
                    "interface": "wan",
                    "protocol": "UDP",
                    "src_network": "any",
                    "src_port": "",
                    "dst_network": "wanip",
                    "dst_port": "51820",
                    "target": "192.168.1.20",
                    "local_port": "51820",
                    "descr": "WireGuard",
                    "enabled": "0",
                    "log": "1",
                },
            ],
            "rowCount": 2,
            "total": 2,
            "current": 1,
        }
        mock_client = _make_mock_client(get_cached_response=api_response)
        with patch("opnsense.tools.firewall._get_client", return_value=mock_client):
            from opnsense.tools.firewall import opnsense__firewall__list_port_forwards

            result = await opnsense__firewall__list_port_forwards()

        assert len(result) == 2

        # First rule
        assert result[0]["uuid"] == "pf-uuid-1"
        assert result[0]["interface"] == "wan"
        assert result[0]["protocol"] == "TCP"
        assert result[0]["source_net"] == "any"
        assert result[0]["destination_net"] == "wanip"
        assert result[0]["destination_port"] == "443"
        assert result[0]["target"] == "192.168.1.10"
        assert result[0]["local_port"] == "8443"
        assert result[0]["description"] == "HTTPS forward"

        # Second rule
        assert result[1]["uuid"] == "pf-uuid-2"
        assert result[1]["protocol"] == "UDP"
        assert result[1]["target"] == "192.168.1.20"
        assert result[1]["description"] == "WireGuard"

    async def test_list_port_forwards_empty(self) -> None:
        """Empty response returns empty list."""
        api_response = {"rows": [], "rowCount": 0, "total": 0, "current": 1}
        mock_client = _make_mock_client(get_cached_response=api_response)
        with patch("opnsense.tools.firewall._get_client", return_value=mock_client):
            from opnsense.tools.firewall import opnsense__firewall__list_port_forwards

            result = await opnsense__firewall__list_port_forwards()

        assert result == []

    async def test_list_port_forwards_boolean_coercion(self) -> None:
        """String booleans '1' and '0' are coerced to True and False."""
        api_response = {
            "rows": [
                {
                    "uuid": "pf-uuid-1",
                    "interface": "wan",
                    "protocol": "TCP",
                    "src_network": "any",
                    "src_port": "",
                    "dst_network": "wanip",
                    "dst_port": "80",
                    "target": "192.168.1.10",
                    "local_port": "80",
                    "descr": "HTTP",
                    "enabled": "1",
                    "log": "0",
                },
                {
                    "uuid": "pf-uuid-2",
                    "interface": "wan",
                    "protocol": "TCP",
                    "src_network": "any",
                    "src_port": "",
                    "dst_network": "wanip",
                    "dst_port": "22",
                    "target": "192.168.1.20",
                    "local_port": "22",
                    "descr": "SSH disabled",
                    "enabled": "0",
                    "log": "1",
                },
            ],
            "rowCount": 2,
            "total": 2,
            "current": 1,
        }
        mock_client = _make_mock_client(get_cached_response=api_response)
        with patch("opnsense.tools.firewall._get_client", return_value=mock_client):
            from opnsense.tools.firewall import opnsense__firewall__list_port_forwards

            result = await opnsense__firewall__list_port_forwards()

        # "1" -> True, "0" -> False
        assert result[0]["enabled"] is True
        assert result[0]["log"] is False
        assert result[1]["enabled"] is False
        assert result[1]["log"] is True

    async def test_list_port_forwards_client_closed(self) -> None:
        """Client is always closed after list."""
        api_response = {"rows": [], "rowCount": 0, "total": 0, "current": 1}
        mock_client = _make_mock_client(get_cached_response=api_response)
        with patch("opnsense.tools.firewall._get_client", return_value=mock_client):
            from opnsense.tools.firewall import opnsense__firewall__list_port_forwards

            await opnsense__firewall__list_port_forwards()

        mock_client.close.assert_awaited_once()


# ===========================================================================
# add_port_forward tests
# ===========================================================================


class TestAddPortForward:
    """opnsense__firewall__add_port_forward -- DNAT rule creation."""

    async def test_add_port_forward_success(self, mock_client: MagicMock) -> None:
        """Successful creation returns UUID and applies."""
        with patch("opnsense.tools.firewall._get_client", return_value=mock_client):
            from opnsense.tools.firewall import opnsense__firewall__add_port_forward

            result = await opnsense__firewall__add_port_forward(
                interface="wan",
                protocol="TCP",
                destination_port="443",
                target="192.168.1.10",
                local_port="8443",
                description="HTTPS forward",
                apply=True,
            )

        assert result["status"] == "created"
        assert result["uuid"] == "dnat-uuid-1234"
        assert result["interface"] == "wan"
        assert result["protocol"] == "TCP"
        assert result["external_port"] == "443"
        assert result["target"] == "192.168.1.10"
        assert result["internal_port"] == "8443"
        assert result["applied"] is True

        # Verify the write payload
        write_call = mock_client.write.call_args
        rule_payload = write_call.kwargs["data"]["rule"]
        assert rule_payload["interface"] == "wan"
        assert rule_payload["protocol"] == "TCP"
        assert rule_payload["dst_port"] == "443"
        assert rule_payload["target"] == "192.168.1.10"
        assert rule_payload["local_port"] == "8443"
        assert rule_payload["descr"] == "HTTPS forward"
        assert rule_payload["dst_network"] == "wanip"  # default
        assert rule_payload["src_network"] == "any"  # default
        assert rule_payload["enabled"] == "1"

    async def test_add_port_forward_invalid_protocol(self) -> None:
        """Invalid protocol raises ValidationError."""
        from opnsense.tools.firewall import opnsense__firewall__add_port_forward

        with pytest.raises(ValidationError, match="Protocol must be one of"):
            await opnsense__firewall__add_port_forward(
                interface="wan",
                protocol="ICMP",
                destination_port="80",
                target="192.168.1.10",
                local_port="80",
                apply=True,
            )

    async def test_add_port_forward_empty_target(self) -> None:
        """Empty target raises ValidationError."""
        from opnsense.tools.firewall import opnsense__firewall__add_port_forward

        with pytest.raises(ValidationError, match="Target.*must not be empty"):
            await opnsense__firewall__add_port_forward(
                interface="wan",
                protocol="TCP",
                destination_port="80",
                target="",
                local_port="80",
                apply=True,
            )

    async def test_add_port_forward_empty_destination_port(self) -> None:
        """Empty destination port raises ValidationError."""
        from opnsense.tools.firewall import opnsense__firewall__add_port_forward

        with pytest.raises(ValidationError, match="Destination port must not be empty"):
            await opnsense__firewall__add_port_forward(
                interface="wan",
                protocol="TCP",
                destination_port="",
                target="192.168.1.10",
                local_port="80",
                apply=True,
            )

    async def test_add_port_forward_empty_local_port(self) -> None:
        """Empty local port raises ValidationError."""
        from opnsense.tools.firewall import opnsense__firewall__add_port_forward

        with pytest.raises(ValidationError, match="Local port must not be empty"):
            await opnsense__firewall__add_port_forward(
                interface="wan",
                protocol="TCP",
                destination_port="80",
                target="192.168.1.10",
                local_port="",
                apply=True,
            )

    async def test_add_port_forward_empty_interface(self) -> None:
        """Empty interface raises ValidationError."""
        from opnsense.tools.firewall import opnsense__firewall__add_port_forward

        with pytest.raises(ValidationError, match="Interface must not be empty"):
            await opnsense__firewall__add_port_forward(
                interface="",
                protocol="TCP",
                destination_port="80",
                target="192.168.1.10",
                local_port="80",
                apply=True,
            )

    async def test_add_port_forward_write_gate_env_disabled(self) -> None:
        """Write gate blocks when env var is disabled."""
        with patch.dict(os.environ, {"OPNSENSE_WRITE_ENABLED": "false"}):
            from opnsense.tools.firewall import opnsense__firewall__add_port_forward

            with pytest.raises(WriteGateError) as exc_info:
                await opnsense__firewall__add_port_forward(
                    interface="wan",
                    protocol="TCP",
                    destination_port="80",
                    target="192.168.1.10",
                    local_port="80",
                    apply=True,
                )
            assert exc_info.value.reason == WriteGateReason.ENV_VAR_DISABLED

    async def test_add_port_forward_write_gate_apply_missing(self) -> None:
        """Write gate blocks when apply=False."""
        from opnsense.tools.firewall import opnsense__firewall__add_port_forward

        with pytest.raises(WriteGateError) as exc_info:
            await opnsense__firewall__add_port_forward(
                interface="wan",
                protocol="TCP",
                destination_port="80",
                target="192.168.1.10",
                local_port="80",
                apply=False,
            )
        assert exc_info.value.reason == WriteGateReason.APPLY_FLAG_MISSING

    async def test_add_port_forward_apply_called(
        self, mock_client: MagicMock
    ) -> None:
        """d_nat/apply is called after successful add."""
        with patch("opnsense.tools.firewall._get_client", return_value=mock_client):
            from opnsense.tools.firewall import opnsense__firewall__add_port_forward

            await opnsense__firewall__add_port_forward(
                interface="wan",
                protocol="UDP",
                destination_port="51820",
                target="192.168.1.20",
                local_port="51820",
                apply=True,
            )

        # Verify d_nat/apply was called
        mock_client.post.assert_any_call("firewall", "d_nat", "apply")

    async def test_add_port_forward_cache_flushed(
        self, mock_client: MagicMock
    ) -> None:
        """Cache is flushed after successful add."""
        with patch("opnsense.tools.firewall._get_client", return_value=mock_client):
            from opnsense.tools.firewall import opnsense__firewall__add_port_forward

            await opnsense__firewall__add_port_forward(
                interface="wan",
                protocol="TCP",
                destination_port="80",
                target="192.168.1.10",
                local_port="80",
                apply=True,
            )

        mock_client.cache.flush_by_prefix.assert_awaited_once_with("firewall:")

    async def test_add_port_forward_tcp_udp_protocol(
        self, mock_client: MagicMock
    ) -> None:
        """TCP/UDP protocol is accepted and uppercased."""
        with patch("opnsense.tools.firewall._get_client", return_value=mock_client):
            from opnsense.tools.firewall import opnsense__firewall__add_port_forward

            result = await opnsense__firewall__add_port_forward(
                interface="wan",
                protocol="tcp/udp",
                destination_port="53",
                target="192.168.1.1",
                local_port="53",
                apply=True,
            )

        assert result["protocol"] == "TCP/UDP"
        rule_payload = mock_client.write.call_args.kwargs["data"]["rule"]
        assert rule_payload["protocol"] == "TCP/UDP"

    async def test_add_port_forward_api_error_on_failure(
        self, mock_client: MagicMock
    ) -> None:
        """APIError raised when addRule response indicates failure."""
        mock_client.write = AsyncMock(
            return_value={"result": "failed", "validations": {"dst_port": "invalid"}}
        )
        with patch("opnsense.tools.firewall._get_client", return_value=mock_client):
            from opnsense.tools.firewall import opnsense__firewall__add_port_forward

            with pytest.raises(APIError, match="Failed to add DNAT port forward"):
                await opnsense__firewall__add_port_forward(
                    interface="wan",
                    protocol="TCP",
                    destination_port="80",
                    target="192.168.1.10",
                    local_port="80",
                    apply=True,
                )

    async def test_add_port_forward_client_always_closed(
        self, mock_client: MagicMock
    ) -> None:
        """Client is closed even when add fails."""
        mock_client.write = AsyncMock(side_effect=Exception("Timeout"))
        with patch("opnsense.tools.firewall._get_client", return_value=mock_client):
            from opnsense.tools.firewall import opnsense__firewall__add_port_forward

            with pytest.raises(Exception, match="Timeout"):
                await opnsense__firewall__add_port_forward(
                    interface="wan",
                    protocol="TCP",
                    destination_port="80",
                    target="192.168.1.10",
                    local_port="80",
                    apply=True,
                )

        mock_client.close.assert_awaited_once()


# ===========================================================================
# delete_port_forward tests
# ===========================================================================


class TestDeletePortForward:
    """opnsense__firewall__delete_port_forward -- DNAT rule deletion."""

    async def test_delete_port_forward_success(
        self, mock_client: MagicMock
    ) -> None:
        """Successful deletion returns UUID and applied status."""
        mock_client.write = AsyncMock(return_value={"result": "saved"})
        with patch("opnsense.tools.firewall._get_client", return_value=mock_client):
            from opnsense.tools.firewall import opnsense__firewall__delete_port_forward

            result = await opnsense__firewall__delete_port_forward(
                uuid="dnat-del-uuid",
                apply=True,
            )

        assert result["status"] == "deleted"
        assert result["uuid"] == "dnat-del-uuid"
        assert result["applied"] is True

        # Verify delRule endpoint
        mock_client.write.assert_awaited_once_with(
            "firewall", "d_nat", "delRule/dnat-del-uuid"
        )

    async def test_delete_port_forward_write_gate_env_disabled(self) -> None:
        """Write gate blocks when env var is disabled."""
        with patch.dict(os.environ, {"OPNSENSE_WRITE_ENABLED": "false"}):
            from opnsense.tools.firewall import opnsense__firewall__delete_port_forward

            with pytest.raises(WriteGateError) as exc_info:
                await opnsense__firewall__delete_port_forward(
                    uuid="abc-123",
                    apply=True,
                )
            assert exc_info.value.reason == WriteGateReason.ENV_VAR_DISABLED

    async def test_delete_port_forward_write_gate_apply_missing(self) -> None:
        """Write gate blocks when apply=False."""
        from opnsense.tools.firewall import opnsense__firewall__delete_port_forward

        with pytest.raises(WriteGateError) as exc_info:
            await opnsense__firewall__delete_port_forward(
                uuid="abc-123",
                apply=False,
            )
        assert exc_info.value.reason == WriteGateReason.APPLY_FLAG_MISSING

    async def test_delete_port_forward_apply_called(
        self, mock_client: MagicMock
    ) -> None:
        """d_nat/apply is called after successful delete."""
        mock_client.write = AsyncMock(return_value={"result": "saved"})
        with patch("opnsense.tools.firewall._get_client", return_value=mock_client):
            from opnsense.tools.firewall import opnsense__firewall__delete_port_forward

            await opnsense__firewall__delete_port_forward(
                uuid="dnat-del-uuid",
                apply=True,
            )

        mock_client.post.assert_any_call("firewall", "d_nat", "apply")

    async def test_delete_port_forward_cache_flushed(
        self, mock_client: MagicMock
    ) -> None:
        """Cache is flushed after successful delete."""
        mock_client.write = AsyncMock(return_value={"result": "saved"})
        with patch("opnsense.tools.firewall._get_client", return_value=mock_client):
            from opnsense.tools.firewall import opnsense__firewall__delete_port_forward

            await opnsense__firewall__delete_port_forward(
                uuid="dnat-del-uuid",
                apply=True,
            )

        mock_client.cache.flush_by_prefix.assert_awaited_once_with("firewall:")

    async def test_delete_port_forward_api_error_on_failure(
        self, mock_client: MagicMock
    ) -> None:
        """APIError raised when delRule response indicates failure."""
        mock_client.write = AsyncMock(return_value={"result": "failed"})
        with patch("opnsense.tools.firewall._get_client", return_value=mock_client):
            from opnsense.tools.firewall import opnsense__firewall__delete_port_forward

            with pytest.raises(APIError, match="Failed to delete DNAT"):
                await opnsense__firewall__delete_port_forward(
                    uuid="bad-uuid",
                    apply=True,
                )

    async def test_delete_port_forward_client_always_closed(
        self, mock_client: MagicMock
    ) -> None:
        """Client is closed even when delete fails."""
        mock_client.write = AsyncMock(side_effect=Exception("Connection refused"))
        with patch("opnsense.tools.firewall._get_client", return_value=mock_client):
            from opnsense.tools.firewall import opnsense__firewall__delete_port_forward

            with pytest.raises(Exception, match="Connection refused"):
                await opnsense__firewall__delete_port_forward(
                    uuid="abc-123",
                    apply=True,
                )

        mock_client.close.assert_awaited_once()
