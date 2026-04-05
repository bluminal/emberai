"""Tests for the Cisco SG-300 SNMP client.

CRITICAL: All pysnmp calls are fully mocked — nothing runs against a real
SNMP agent.

Covers:
- Client construction with host, community, port
- CommunityData uses SNMPv2c (mpModel=1)
- get() returns a single value and maps errors
- get_bulk() returns list of (oid, value) pairs
- walk() iterates subtree and stops at subtree boundary
- _check_error() raises NetworkError on transport or protocol errors
- get() / get_bulk() / walk() re-raise NetworkError and wrap generic exceptions
- get_snmp_client() factory reads from env vars
- get_snmp_client() returns singleton
- get_snmp_client() raises AuthenticationError when CISCO_HOST is missing
"""

from __future__ import annotations

import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from cisco.errors import AuthenticationError, NetworkError
from cisco.snmp.client import CiscoSNMPClient, get_snmp_client

# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------


class TestConstruction:
    """CiscoSNMPClient construction and defaults."""

    def test_default_community_is_public(self) -> None:
        client = CiscoSNMPClient(host="10.0.0.1")
        assert client._community == "public"

    def test_custom_community(self) -> None:
        client = CiscoSNMPClient(host="10.0.0.1", community="private")
        assert client._community == "private"

    def test_default_port_is_161(self) -> None:
        client = CiscoSNMPClient(host="10.0.0.1")
        assert client._port == 161

    def test_custom_port(self) -> None:
        client = CiscoSNMPClient(host="10.0.0.1", port=1161)
        assert client._port == 1161

    def test_host_stored(self) -> None:
        client = CiscoSNMPClient(host="192.168.1.2")
        assert client._host == "192.168.1.2"

    def test_engine_created(self) -> None:
        client = CiscoSNMPClient(host="10.0.0.1")
        assert client._engine is not None


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


class TestCommunityData:
    """_community_data() builds SNMPv2c community."""

    def test_community_data_uses_snmpv2c(self) -> None:
        """mpModel=1 means SNMPv2c."""
        client = CiscoSNMPClient(host="10.0.0.1", community="mycomm")
        cd = client._community_data()
        # Verify it's SNMPv2c (mpModel=1)
        assert "mpModel=1" in str(cd)


class TestTransportTarget:
    """_transport_target() builds UDP transport."""

    def test_transport_target_host_and_port(self) -> None:
        client = CiscoSNMPClient(host="192.168.1.2", port=161)
        # Verify the transport target can be created without error
        target = client._transport_target()
        assert target is not None


class TestContextData:
    """_context_data() returns a default context."""

    def test_context_data_returns_context(self) -> None:
        cd = CiscoSNMPClient._context_data()
        assert cd is not None


# ---------------------------------------------------------------------------
# _check_error
# ---------------------------------------------------------------------------


class TestCheckError:
    """_check_error() raises appropriate errors."""

    def test_no_error_does_nothing(self) -> None:
        """No exception when all indicators are falsy."""
        CiscoSNMPClient._check_error(None, None, None)

    def test_error_indication_raises_network_error(self) -> None:
        with pytest.raises(NetworkError, match="SNMP transport error"):
            CiscoSNMPClient._check_error("requestTimedOut", None, None)

    def test_error_indication_includes_message(self) -> None:
        with pytest.raises(NetworkError) as exc_info:
            CiscoSNMPClient._check_error("requestTimedOut", None, None)
        assert "requestTimedOut" in exc_info.value.message

    def test_error_status_raises_network_error(self) -> None:
        mock_status = MagicMock()
        mock_status.prettyPrint.return_value = "noSuchName"
        mock_status.__bool__ = lambda self: True

        with pytest.raises(NetworkError, match="SNMP error"):
            CiscoSNMPClient._check_error(None, mock_status, 1)

    def test_error_status_includes_index(self) -> None:
        mock_status = MagicMock()
        mock_status.prettyPrint.return_value = "noSuchName"
        mock_status.__bool__ = lambda self: True

        with pytest.raises(NetworkError) as exc_info:
            CiscoSNMPClient._check_error(None, mock_status, 3)
        assert "3" in exc_info.value.message

    def test_error_indication_takes_priority(self) -> None:
        """When both error_indication and error_status are set, indication wins."""
        mock_status = MagicMock()
        mock_status.prettyPrint.return_value = "noSuchName"
        mock_status.__bool__ = lambda self: True

        with pytest.raises(NetworkError, match="transport error"):
            CiscoSNMPClient._check_error("timeout", mock_status, 1)


# ---------------------------------------------------------------------------
# get()
# ---------------------------------------------------------------------------


class TestGet:
    """SNMP GET operation."""

    @pytest.mark.asyncio
    async def test_get_returns_value(self) -> None:
        client = CiscoSNMPClient(host="10.0.0.1")

        mock_value = MagicMock()
        mock_value.__str__ = lambda self: "Cisco SG300-28 28-Port Gigabit"

        mock_var_bind = (MagicMock(), mock_value)

        with patch(
            "cisco.snmp.client.getCmd",
            new_callable=AsyncMock,
            return_value=(None, None, None, [mock_var_bind]),
        ):
            result = await client.get("1.3.6.1.2.1.1.1.0")
            assert result is mock_value

    @pytest.mark.asyncio
    async def test_get_raises_on_transport_error(self) -> None:
        client = CiscoSNMPClient(host="10.0.0.1")

        with patch(
            "cisco.snmp.client.getCmd",
            new_callable=AsyncMock,
            return_value=("requestTimedOut", None, None, []),
        ), pytest.raises(NetworkError, match="transport error"):
            await client.get("1.3.6.1.2.1.1.1.0")

    @pytest.mark.asyncio
    async def test_get_raises_on_protocol_error(self) -> None:
        client = CiscoSNMPClient(host="10.0.0.1")

        mock_status = MagicMock()
        mock_status.prettyPrint.return_value = "noSuchName"
        mock_status.__bool__ = lambda self: True

        with patch(
            "cisco.snmp.client.getCmd",
            new_callable=AsyncMock,
            return_value=(None, mock_status, 1, []),
        ), pytest.raises(NetworkError, match="SNMP error"):
            await client.get("1.3.6.1.2.1.1.1.0")

    @pytest.mark.asyncio
    async def test_get_wraps_generic_exception(self) -> None:
        """Non-SNMP exceptions are wrapped in NetworkError."""
        client = CiscoSNMPClient(host="10.0.0.1")

        with patch(
            "cisco.snmp.client.getCmd",
            new_callable=AsyncMock,
            side_effect=OSError("socket error"),
        ), pytest.raises(NetworkError, match="SNMP GET failed"):
            await client.get("1.3.6.1.2.1.1.1.0")

    @pytest.mark.asyncio
    async def test_get_reraises_network_error(self) -> None:
        """NetworkError raised internally is re-raised unchanged."""
        client = CiscoSNMPClient(host="10.0.0.1")

        with patch(
            "cisco.snmp.client.getCmd",
            new_callable=AsyncMock,
            side_effect=NetworkError("already a network error"),
        ), pytest.raises(NetworkError, match="already a network error"):
            await client.get("1.3.6.1.2.1.1.1.0")


# ---------------------------------------------------------------------------
# get_bulk()
# ---------------------------------------------------------------------------


class TestGetBulk:
    """SNMP GETBULK operation."""

    @pytest.mark.asyncio
    async def test_get_bulk_returns_oid_value_pairs(self) -> None:
        client = CiscoSNMPClient(host="10.0.0.1")

        oid1 = MagicMock()
        oid1.__str__ = lambda self: "1.3.6.1.2.1.2.2.1.2.1"
        val1 = MagicMock()

        oid2 = MagicMock()
        oid2.__str__ = lambda self: "1.3.6.1.2.1.2.2.1.2.2"
        val2 = MagicMock()

        var_bind_table = [(oid1, val1), (oid2, val2)]

        with patch(
            "cisco.snmp.client.bulkCmd",
            new_callable=AsyncMock,
            return_value=(None, None, None, var_bind_table),
        ):
            results = await client.get_bulk("1.3.6.1.2.1.2.2.1.2")
            assert len(results) == 2
            assert results[0] == ("1.3.6.1.2.1.2.2.1.2.1", val1)
            assert results[1] == ("1.3.6.1.2.1.2.2.1.2.2", val2)

    @pytest.mark.asyncio
    async def test_get_bulk_default_max_repetitions(self) -> None:
        """Default max_repetitions is 25."""
        client = CiscoSNMPClient(host="10.0.0.1")

        with patch(
            "cisco.snmp.client.bulkCmd",
            new_callable=AsyncMock,
            return_value=(None, None, None, []),
        ) as mock_bulk:
            await client.get_bulk("1.3.6.1.2.1.2.2.1.2")

            # The 5th positional arg (after engine, community, transport, context)
            # is nonRepeaters=0, 6th is max_repetitions=25
            call_args = mock_bulk.call_args
            assert call_args[0][4] == 0  # nonRepeaters
            assert call_args[0][5] == 25  # max_repetitions

    @pytest.mark.asyncio
    async def test_get_bulk_custom_max_repetitions(self) -> None:
        client = CiscoSNMPClient(host="10.0.0.1")

        with patch(
            "cisco.snmp.client.bulkCmd",
            new_callable=AsyncMock,
            return_value=(None, None, None, []),
        ) as mock_bulk:
            await client.get_bulk("1.3.6.1.2.1.2.2.1.2", max_repetitions=50)
            call_args = mock_bulk.call_args
            assert call_args[0][5] == 50

    @pytest.mark.asyncio
    async def test_get_bulk_raises_on_transport_error(self) -> None:
        client = CiscoSNMPClient(host="10.0.0.1")

        with patch(
            "cisco.snmp.client.bulkCmd",
            new_callable=AsyncMock,
            return_value=("requestTimedOut", None, None, []),
        ), pytest.raises(NetworkError, match="transport error"):
            await client.get_bulk("1.3.6.1.2.1.2.2.1.2")

    @pytest.mark.asyncio
    async def test_get_bulk_wraps_generic_exception(self) -> None:
        client = CiscoSNMPClient(host="10.0.0.1")

        with patch(
            "cisco.snmp.client.bulkCmd",
            new_callable=AsyncMock,
            side_effect=OSError("socket error"),
        ), pytest.raises(NetworkError, match="SNMP GETBULK failed"):
            await client.get_bulk("1.3.6.1.2.1.2.2.1.2")

    @pytest.mark.asyncio
    async def test_get_bulk_reraises_network_error(self) -> None:
        client = CiscoSNMPClient(host="10.0.0.1")

        with patch(
            "cisco.snmp.client.bulkCmd",
            new_callable=AsyncMock,
            side_effect=NetworkError("already a network error"),
        ), pytest.raises(NetworkError, match="already a network error"):
            await client.get_bulk("1.3.6.1.2.1.2.2.1.2")

    @pytest.mark.asyncio
    async def test_get_bulk_empty_result(self) -> None:
        client = CiscoSNMPClient(host="10.0.0.1")

        with patch(
            "cisco.snmp.client.bulkCmd",
            new_callable=AsyncMock,
            return_value=(None, None, None, []),
        ):
            results = await client.get_bulk("1.3.6.1.2.1.2.2.1.2")
            assert results == []


# ---------------------------------------------------------------------------
# walk()
# ---------------------------------------------------------------------------


class TestWalk:
    """SNMP walk (repeated GET-NEXT) operation."""

    @pytest.mark.asyncio
    async def test_walk_returns_subtree_entries(self) -> None:
        client = CiscoSNMPClient(host="10.0.0.1")

        base_oid = "1.3.6.1.2.1.2.2.1.2"

        oid1 = MagicMock()
        oid1.__str__ = lambda self: f"{base_oid}.1"
        val1 = MagicMock()

        oid2 = MagicMock()
        oid2.__str__ = lambda self: f"{base_oid}.2"
        val2 = MagicMock()

        async def mock_walk_cmd(*args, **kwargs):
            """Simulate walkCmd async generator yielding two rows."""
            yield (None, None, None, [(oid1, val1)])
            yield (None, None, None, [(oid2, val2)])

        with patch("cisco.snmp.client.walkCmd", side_effect=mock_walk_cmd):
            results = await client.walk(base_oid)
            assert len(results) == 2
            assert results[0] == (f"{base_oid}.1", val1)
            assert results[1] == (f"{base_oid}.2", val2)

    @pytest.mark.asyncio
    async def test_walk_stops_at_subtree_boundary(self) -> None:
        """Walk stops when OID leaves the requested subtree."""
        client = CiscoSNMPClient(host="10.0.0.1")

        base_oid = "1.3.6.1.2.1.2.2.1.2"

        oid_in = MagicMock()
        oid_in.__str__ = lambda self: f"{base_oid}.1"
        val_in = MagicMock()

        oid_out = MagicMock()
        oid_out.__str__ = lambda self: "1.3.6.1.2.1.2.2.1.3.1"  # Different column
        val_out = MagicMock()

        async def mock_walk_cmd(*args, **kwargs):
            yield (None, None, None, [(oid_in, val_in)])
            yield (None, None, None, [(oid_out, val_out)])

        with patch("cisco.snmp.client.walkCmd", side_effect=mock_walk_cmd):
            results = await client.walk(base_oid)
            assert len(results) == 1
            assert results[0] == (f"{base_oid}.1", val_in)

    @pytest.mark.asyncio
    async def test_walk_raises_on_transport_error(self) -> None:
        client = CiscoSNMPClient(host="10.0.0.1")

        async def mock_walk_cmd(*args, **kwargs):
            yield ("requestTimedOut", None, None, [])

        with (
            patch("cisco.snmp.client.walkCmd", side_effect=mock_walk_cmd),
            pytest.raises(NetworkError, match="transport error"),
        ):
            await client.walk("1.3.6.1.2.1.2.2.1.2")

    @pytest.mark.asyncio
    async def test_walk_wraps_generic_exception(self) -> None:
        client = CiscoSNMPClient(host="10.0.0.1")

        async def mock_walk_cmd(*args, **kwargs):
            raise OSError("socket error")
            yield  # pragma: no cover - make this an async generator

        with (
            patch("cisco.snmp.client.walkCmd", side_effect=mock_walk_cmd),
            pytest.raises(NetworkError, match="SNMP walk failed"),
        ):
            await client.walk("1.3.6.1.2.1.2.2.1.2")

    @pytest.mark.asyncio
    async def test_walk_reraises_network_error(self) -> None:
        client = CiscoSNMPClient(host="10.0.0.1")

        async def mock_walk_cmd(*args, **kwargs):
            raise NetworkError("already a network error")
            yield  # pragma: no cover

        with (
            patch("cisco.snmp.client.walkCmd", side_effect=mock_walk_cmd),
            pytest.raises(NetworkError, match="already a network error"),
        ):
            await client.walk("1.3.6.1.2.1.2.2.1.2")

    @pytest.mark.asyncio
    async def test_walk_empty_subtree(self) -> None:
        client = CiscoSNMPClient(host="10.0.0.1")

        async def mock_walk_cmd(*args, **kwargs):
            return
            yield  # pragma: no cover - make this an async generator

        with patch("cisco.snmp.client.walkCmd", side_effect=mock_walk_cmd):
            results = await client.walk("1.3.6.1.2.1.2.2.1.2")
            assert results == []

    @pytest.mark.asyncio
    async def test_walk_protocol_error_mid_walk(self) -> None:
        """Protocol error encountered mid-walk raises NetworkError."""
        client = CiscoSNMPClient(host="10.0.0.1")

        base_oid = "1.3.6.1.2.1.2.2.1.2"
        oid1 = MagicMock()
        oid1.__str__ = lambda self: f"{base_oid}.1"
        val1 = MagicMock()

        mock_status = MagicMock()
        mock_status.prettyPrint.return_value = "genErr"
        mock_status.__bool__ = lambda self: True

        async def mock_walk_cmd(*args, **kwargs):
            yield (None, None, None, [(oid1, val1)])
            yield (None, mock_status, 1, [])

        with (
            patch("cisco.snmp.client.walkCmd", side_effect=mock_walk_cmd),
            pytest.raises(NetworkError, match="SNMP error"),
        ):
            await client.walk(base_oid)


# ---------------------------------------------------------------------------
# get_snmp_client() factory
# ---------------------------------------------------------------------------


class TestGetSNMPClientFactory:
    """get_snmp_client() reads from env vars and returns singleton."""

    def setup_method(self) -> None:
        """Reset the module-level singleton before each test."""
        import cisco.snmp.client as mod

        mod._client = None

    def test_get_snmp_client_reads_host(self) -> None:
        env = {"CISCO_HOST": "10.0.0.1"}
        with patch.dict(os.environ, env, clear=True):
            client = get_snmp_client()
            assert client._host == "10.0.0.1"

    def test_get_snmp_client_default_community(self) -> None:
        env = {"CISCO_HOST": "10.0.0.1"}
        with patch.dict(os.environ, env, clear=True):
            client = get_snmp_client()
            assert client._community == "public"

    def test_get_snmp_client_custom_community(self) -> None:
        env = {"CISCO_HOST": "10.0.0.1", "CISCO_SNMP_COMMUNITY": "private"}
        with patch.dict(os.environ, env, clear=True):
            client = get_snmp_client()
            assert client._community == "private"

    def test_get_snmp_client_missing_host_raises(self) -> None:
        with (
            patch.dict(os.environ, {}, clear=True),
            pytest.raises(AuthenticationError, match="CISCO_HOST"),
        ):
            get_snmp_client()

    def test_get_snmp_client_returns_singleton(self) -> None:
        env = {"CISCO_HOST": "10.0.0.1"}
        with patch.dict(os.environ, env, clear=True):
            client1 = get_snmp_client()
            client2 = get_snmp_client()
            assert client1 is client2

    def test_get_snmp_client_singleton_skips_env_on_second_call(self) -> None:
        """Second call returns cached instance without re-reading env."""
        env = {"CISCO_HOST": "10.0.0.1"}
        with patch.dict(os.environ, env, clear=True):
            client1 = get_snmp_client()

        # Even with empty env, the singleton is returned
        import cisco.snmp.client as mod

        assert mod._client is client1
        # Directly verify the singleton is returned
        client2 = get_snmp_client()
        assert client2 is client1
