"""Tests for Diagnostics skill tools.

Covers:
- run_ping: parameter passing, response handling
- run_traceroute: parameter passing
- dns_lookup: parameter passing
- get_lldp_neighbors: response format variants, interface filtering
- run_host_discovery: polling success, timeout, partial results, error handling
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, patch

import pytest


def _make_client(
    get_returns: dict[str, Any] | None = None,
    post_returns: dict[str, Any] | None = None,
) -> AsyncMock:
    client = AsyncMock()
    if get_returns is not None:
        client.get = AsyncMock(return_value=get_returns)
    if post_returns is not None:
        client.post = AsyncMock(return_value=post_returns)
    return client


# ---------------------------------------------------------------------------
# run_ping
# ---------------------------------------------------------------------------


class TestRunPing:
    @pytest.mark.asyncio
    async def test_basic_ping(self) -> None:
        from opnsense.tools.diagnostics import opnsense__diagnostics__run_ping

        result = {"loss": "0", "avg": "5.2", "min": "4.1", "max": "6.3"}
        client = _make_client(post_returns=result)

        response = await opnsense__diagnostics__run_ping(client, "8.8.8.8")

        assert response == result
        client.post.assert_called_once_with(
            "diagnostics",
            "interface",
            "getPing",
            data={"address": "8.8.8.8"},
        )

    @pytest.mark.asyncio
    async def test_ping_with_count(self) -> None:
        from opnsense.tools.diagnostics import opnsense__diagnostics__run_ping

        client = _make_client(post_returns={"loss": "0"})

        await opnsense__diagnostics__run_ping(client, "8.8.8.8", count=5)

        call_data = client.post.call_args[1]["data"]
        assert call_data["count"] == "5"

    @pytest.mark.asyncio
    async def test_ping_with_source_ip(self) -> None:
        from opnsense.tools.diagnostics import opnsense__diagnostics__run_ping

        client = _make_client(post_returns={"loss": "0"})

        await opnsense__diagnostics__run_ping(
            client,
            "8.8.8.8",
            source_ip="192.168.1.1",
        )

        call_data = client.post.call_args[1]["data"]
        assert call_data["source_address"] == "192.168.1.1"


# ---------------------------------------------------------------------------
# run_traceroute
# ---------------------------------------------------------------------------


class TestRunTraceroute:
    @pytest.mark.asyncio
    async def test_basic_traceroute(self) -> None:
        from opnsense.tools.diagnostics import opnsense__diagnostics__run_traceroute

        result = {"hops": [{"hop": 1, "addr": "192.168.1.1"}]}
        client = _make_client(post_returns=result)

        response = await opnsense__diagnostics__run_traceroute(client, "8.8.8.8")

        assert response == result
        client.post.assert_called_once_with(
            "diagnostics",
            "interface",
            "getTrace",
            data={"address": "8.8.8.8"},
        )

    @pytest.mark.asyncio
    async def test_traceroute_with_max_hops(self) -> None:
        from opnsense.tools.diagnostics import opnsense__diagnostics__run_traceroute

        client = _make_client(post_returns={})

        await opnsense__diagnostics__run_traceroute(client, "8.8.8.8", max_hops=15)

        call_data = client.post.call_args[1]["data"]
        assert call_data["maxttl"] == "15"


# ---------------------------------------------------------------------------
# dns_lookup
# ---------------------------------------------------------------------------


class TestDNSLookup:
    @pytest.mark.asyncio
    async def test_basic_lookup(self) -> None:
        from opnsense.tools.diagnostics import opnsense__diagnostics__dns_lookup

        result = {"address": "192.168.1.200", "hostname": "nas.home.local"}
        client = _make_client(get_returns=result)

        response = await opnsense__diagnostics__dns_lookup(client, "192.168.1.200")

        assert response == result
        client.get.assert_called_once_with(
            "diagnostics",
            "dns",
            "reverseResolve",
            params={"address": "192.168.1.200"},
        )

    @pytest.mark.asyncio
    async def test_lookup_with_record_type(self) -> None:
        from opnsense.tools.diagnostics import opnsense__diagnostics__dns_lookup

        client = _make_client(get_returns={})

        await opnsense__diagnostics__dns_lookup(
            client,
            "example.com",
            record_type="MX",
        )

        client.get.assert_called_once_with(
            "diagnostics",
            "dns",
            "reverseResolve",
            params={"address": "example.com", "type": "MX"},
        )


# ---------------------------------------------------------------------------
# get_lldp_neighbors
# ---------------------------------------------------------------------------


class TestGetLLDPNeighbors:
    @pytest.mark.asyncio
    async def test_rows_format(self) -> None:
        from opnsense.tools.diagnostics import opnsense__diagnostics__get_lldp_neighbors

        data = {
            "rows": [
                {"interface": "igb0", "chassis_id": "aa:bb:cc:dd:ee:ff"},
                {"interface": "igb1", "chassis_id": "11:22:33:44:55:66"},
            ],
        }
        client = _make_client(get_returns=data)

        with patch("opnsense.tools.diagnostics._get_client", return_value=client):
            neighbors = await opnsense__diagnostics__get_lldp_neighbors()

        assert len(neighbors) == 2
        assert neighbors[0]["interface"] == "igb0"

    @pytest.mark.asyncio
    async def test_neighbors_format(self) -> None:
        from opnsense.tools.diagnostics import opnsense__diagnostics__get_lldp_neighbors

        data = {
            "neighbors": [
                {"local_port": "igb0", "remote_system": "switch-1"},
            ],
        }
        client = _make_client(get_returns=data)

        with patch("opnsense.tools.diagnostics._get_client", return_value=client):
            neighbors = await opnsense__diagnostics__get_lldp_neighbors()

        assert len(neighbors) == 1
        assert neighbors[0]["remote_system"] == "switch-1"

    @pytest.mark.asyncio
    async def test_filter_by_interface(self) -> None:
        from opnsense.tools.diagnostics import opnsense__diagnostics__get_lldp_neighbors

        data = {
            "rows": [
                {"interface": "igb0", "chassis_id": "aa:bb:cc:dd:ee:ff"},
                {"interface": "igb1", "chassis_id": "11:22:33:44:55:66"},
            ],
        }
        client = _make_client(get_returns=data)

        with patch("opnsense.tools.diagnostics._get_client", return_value=client):
            neighbors = await opnsense__diagnostics__get_lldp_neighbors(
                interface="igb0",
            )

        assert len(neighbors) == 1
        assert neighbors[0]["interface"] == "igb0"

    @pytest.mark.asyncio
    async def test_filter_by_local_port(self) -> None:
        from opnsense.tools.diagnostics import opnsense__diagnostics__get_lldp_neighbors

        data = {
            "neighbors": [
                {"local_port": "igb0", "remote_system": "switch-1"},
                {"local_port": "igb1", "remote_system": "switch-2"},
            ],
        }
        client = _make_client(get_returns=data)

        with patch("opnsense.tools.diagnostics._get_client", return_value=client):
            neighbors = await opnsense__diagnostics__get_lldp_neighbors(
                interface="igb1",
            )

        assert len(neighbors) == 1
        assert neighbors[0]["local_port"] == "igb1"

    @pytest.mark.asyncio
    async def test_empty_response(self) -> None:
        from opnsense.tools.diagnostics import opnsense__diagnostics__get_lldp_neighbors

        client = _make_client(get_returns={})

        with patch("opnsense.tools.diagnostics._get_client", return_value=client):
            neighbors = await opnsense__diagnostics__get_lldp_neighbors()

        assert neighbors == []


# ---------------------------------------------------------------------------
# run_host_discovery -- async polling
# ---------------------------------------------------------------------------


class TestRunHostDiscovery:
    @pytest.mark.asyncio
    async def test_successful_scan(self) -> None:
        from opnsense.tools.diagnostics import opnsense__diagnostics__run_host_discovery

        client = AsyncMock()
        client.post = AsyncMock(return_value={"status": "started"})

        # First poll: still running; second poll: done
        poll_responses = [
            {"status": "running", "rows": [{"ip": "192.168.1.10"}]},
            {
                "status": "done",
                "rows": [
                    {"ip": "192.168.1.10"},
                    {"ip": "192.168.1.20"},
                ],
            },
        ]
        client.get = AsyncMock(side_effect=poll_responses)

        with patch("opnsense.tools.diagnostics.asyncio.sleep", new_callable=AsyncMock):
            result = await opnsense__diagnostics__run_host_discovery(client, "igb1")

        assert result["completed"] is True
        assert result["interface"] == "igb1"
        assert len(result["hosts"]) == 2

    @pytest.mark.asyncio
    async def test_timeout_returns_partial_results(self) -> None:
        from opnsense.tools.diagnostics import opnsense__diagnostics__run_host_discovery

        client = AsyncMock()
        client.post = AsyncMock(return_value={"status": "started"})

        # Always return "running" to trigger timeout
        client.get = AsyncMock(
            return_value={
                "status": "running",
                "rows": [{"ip": "192.168.1.10"}],
            }
        )

        with (
            patch("opnsense.tools.diagnostics.asyncio.sleep", new_callable=AsyncMock),
            patch("opnsense.tools.diagnostics._POLL_TIMEOUT_SECONDS", 4.0),
            patch("opnsense.tools.diagnostics._POLL_INTERVAL_SECONDS", 2.0),
        ):
            result = await opnsense__diagnostics__run_host_discovery(client, "igb1")

        assert result["completed"] is False
        assert result["interface"] == "igb1"
        # Should have partial results
        assert len(result["hosts"]) >= 1

    @pytest.mark.asyncio
    async def test_poll_error_continues(self) -> None:
        from opnsense.tools.diagnostics import opnsense__diagnostics__run_host_discovery

        client = AsyncMock()
        client.post = AsyncMock(return_value={"status": "started"})

        # First poll errors, second succeeds with done
        poll_responses = [
            Exception("Connection reset"),
            {"status": "done", "rows": [{"ip": "192.168.1.10"}]},
        ]
        client.get = AsyncMock(side_effect=poll_responses)

        with patch("opnsense.tools.diagnostics.asyncio.sleep", new_callable=AsyncMock):
            result = await opnsense__diagnostics__run_host_discovery(client, "igb1")

        assert result["completed"] is True
        assert len(result["hosts"]) == 1

    @pytest.mark.asyncio
    async def test_start_request_made(self) -> None:
        from opnsense.tools.diagnostics import opnsense__diagnostics__run_host_discovery

        client = AsyncMock()
        client.post = AsyncMock(return_value={"status": "started"})
        client.get = AsyncMock(
            return_value={
                "status": "done",
                "rows": [],
            }
        )

        with patch("opnsense.tools.diagnostics.asyncio.sleep", new_callable=AsyncMock):
            await opnsense__diagnostics__run_host_discovery(client, "igb1")

        client.post.assert_called_once_with(
            "diagnostics",
            "interface",
            "startScan",
            data={"interface": "igb1"},
        )

    @pytest.mark.asyncio
    async def test_hosts_key_format(self) -> None:
        """Test that 'hosts' key in response is handled."""
        from opnsense.tools.diagnostics import opnsense__diagnostics__run_host_discovery

        client = AsyncMock()
        client.post = AsyncMock(return_value={"status": "started"})
        client.get = AsyncMock(
            return_value={
                "status": "done",
                "hosts": [{"ip": "10.0.0.1"}, {"ip": "10.0.0.2"}],
            }
        )

        with patch("opnsense.tools.diagnostics.asyncio.sleep", new_callable=AsyncMock):
            result = await opnsense__diagnostics__run_host_discovery(client, "igb1")

        assert result["completed"] is True
        assert len(result["hosts"]) == 2
