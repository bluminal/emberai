"""Tests for Diagnostics skill tools.

Covers:
- run_ping: 26.x POST-then-poll pattern, parameter passing
- run_traceroute: 26.x POST-then-poll pattern, parameter passing
- dns_lookup: 26.x Unbound endpoint, parameter passing
- get_lldp_neighbors: response format variants, interface filtering
- run_host_discovery: polling success, timeout, partial results, error handling
- _poll_for_result: shared polling helper, completion detection, timeout, errors
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, patch

import pytest


def _make_client(
    get_returns: dict[str, Any] | list[dict[str, Any]] | None = None,
    post_returns: dict[str, Any] | None = None,
) -> AsyncMock:
    client = AsyncMock()
    if get_returns is not None:
        if isinstance(get_returns, list):
            client.get = AsyncMock(side_effect=get_returns)
        else:
            client.get = AsyncMock(return_value=get_returns)
    if post_returns is not None:
        client.post = AsyncMock(return_value=post_returns)
    return client


# ---------------------------------------------------------------------------
# _poll_for_result (shared polling helper)
# ---------------------------------------------------------------------------


class TestPollForResult:
    @pytest.mark.asyncio
    async def test_completes_on_status_done(self) -> None:
        from opnsense.tools.diagnostics import _poll_for_result

        client = AsyncMock()
        client.get = AsyncMock(
            side_effect=[
                {"status": "running", "result": "partial..."},
                {"status": "done", "result": "PING 8.8.8.8: 3 packets..."},
            ]
        )

        with patch("opnsense.tools.diagnostics.asyncio.sleep", new_callable=AsyncMock):
            result = await _poll_for_result(
                client, "diagnostics", "interface", "pingStatus", label="test"
            )

        assert result["completed"] is True
        assert result["result"]["status"] == "done"

    @pytest.mark.asyncio
    async def test_completes_on_status_completed(self) -> None:
        from opnsense.tools.diagnostics import _poll_for_result

        client = AsyncMock()
        client.get = AsyncMock(return_value={"status": "completed", "data": "ok"})

        with patch("opnsense.tools.diagnostics.asyncio.sleep", new_callable=AsyncMock):
            result = await _poll_for_result(
                client, "diagnostics", "interface", "pingStatus", label="test"
            )

        assert result["completed"] is True

    @pytest.mark.asyncio
    async def test_completes_on_output_stabilisation(self) -> None:
        """When there is no explicit status field, completion is detected
        by output length stabilisation between two consecutive polls."""
        from opnsense.tools.diagnostics import _poll_for_result

        client = AsyncMock()
        client.get = AsyncMock(
            side_effect=[
                {"result": "line1\n"},
                {"result": "line1\nline2\n"},
                {"result": "line1\nline2\n"},  # same length = stabilised
            ]
        )

        with patch("opnsense.tools.diagnostics.asyncio.sleep", new_callable=AsyncMock):
            result = await _poll_for_result(
                client, "diagnostics", "interface", "pingStatus", label="test"
            )

        assert result["completed"] is True
        assert result["result"]["result"] == "line1\nline2\n"

    @pytest.mark.asyncio
    async def test_timeout_returns_incomplete(self) -> None:
        from opnsense.tools.diagnostics import _poll_for_result

        client = AsyncMock()
        # Always returns running + growing output
        call_count = 0

        async def growing_output(*args: Any, **kwargs: Any) -> dict[str, Any]:
            nonlocal call_count
            call_count += 1
            return {"status": "running", "result": "x" * call_count}

        client.get = AsyncMock(side_effect=growing_output)

        with (
            patch("opnsense.tools.diagnostics.asyncio.sleep", new_callable=AsyncMock),
            patch("opnsense.tools.diagnostics._POLL_TIMEOUT_SECONDS", 4.0),
            patch("opnsense.tools.diagnostics._POLL_INTERVAL_SECONDS", 2.0),
        ):
            result = await _poll_for_result(
                client, "diagnostics", "interface", "pingStatus", label="test"
            )

        assert result["completed"] is False

    @pytest.mark.asyncio
    async def test_poll_error_continues(self) -> None:
        from opnsense.tools.diagnostics import _poll_for_result

        client = AsyncMock()
        client.get = AsyncMock(
            side_effect=[
                Exception("Connection reset"),
                {"status": "done", "result": "ok"},
            ]
        )

        with patch("opnsense.tools.diagnostics.asyncio.sleep", new_callable=AsyncMock):
            result = await _poll_for_result(
                client, "diagnostics", "interface", "pingStatus", label="test"
            )

        assert result["completed"] is True

    @pytest.mark.asyncio
    async def test_elapsed_seconds_tracked(self) -> None:
        from opnsense.tools.diagnostics import _poll_for_result

        client = AsyncMock()
        client.get = AsyncMock(
            side_effect=[
                {"status": "running"},
                {"status": "done", "result": "ok"},
            ]
        )

        with (
            patch("opnsense.tools.diagnostics.asyncio.sleep", new_callable=AsyncMock),
            patch("opnsense.tools.diagnostics._POLL_INTERVAL_SECONDS", 2.0),
        ):
            result = await _poll_for_result(
                client, "diagnostics", "interface", "pingStatus", label="test"
            )

        assert result["elapsed_seconds"] == 4.0

    @pytest.mark.asyncio
    async def test_empty_output_does_not_trigger_stabilisation(self) -> None:
        """Empty output should not be considered stable."""
        from opnsense.tools.diagnostics import _poll_for_result

        client = AsyncMock()
        client.get = AsyncMock(
            side_effect=[
                {"result": ""},
                {"result": ""},
                {"status": "done", "result": "final"},
            ]
        )

        with patch("opnsense.tools.diagnostics.asyncio.sleep", new_callable=AsyncMock):
            result = await _poll_for_result(
                client, "diagnostics", "interface", "pingStatus", label="test"
            )

        assert result["completed"] is True
        assert result["result"]["result"] == "final"


# ---------------------------------------------------------------------------
# run_ping (26.x POST-then-poll)
# ---------------------------------------------------------------------------


class TestRunPing:
    @pytest.mark.asyncio
    async def test_basic_ping(self) -> None:
        from opnsense.tools.diagnostics import opnsense__diagnostics__run_ping

        client = AsyncMock()
        client.post = AsyncMock(return_value={"status": "started"})
        client.get = AsyncMock(
            side_effect=[
                {"status": "running", "result": "PING 8.8.8.8..."},
                {"status": "done", "result": "PING 8.8.8.8: 3 packets, 0% loss, avg 5.2ms"},
            ]
        )

        with patch("opnsense.tools.diagnostics.asyncio.sleep", new_callable=AsyncMock):
            response = await opnsense__diagnostics__run_ping(client, "8.8.8.8")

        assert response["host"] == "8.8.8.8"
        assert response["completed"] is True
        assert "3 packets" in response["output"]

        # Verify the start POST used the correct 26.x endpoint
        client.post.assert_called_once_with(
            "diagnostics",
            "interface",
            "ping",
            data={"address": "8.8.8.8"},
        )

    @pytest.mark.asyncio
    async def test_ping_with_count(self) -> None:
        from opnsense.tools.diagnostics import opnsense__diagnostics__run_ping

        client = AsyncMock()
        client.post = AsyncMock(return_value={"status": "started"})
        client.get = AsyncMock(return_value={"status": "done", "result": "ok"})

        with patch("opnsense.tools.diagnostics.asyncio.sleep", new_callable=AsyncMock):
            await opnsense__diagnostics__run_ping(client, "8.8.8.8", count=5)

        call_data = client.post.call_args[1]["data"]
        assert call_data["count"] == "5"

    @pytest.mark.asyncio
    async def test_ping_with_source_ip(self) -> None:
        from opnsense.tools.diagnostics import opnsense__diagnostics__run_ping

        client = AsyncMock()
        client.post = AsyncMock(return_value={"status": "started"})
        client.get = AsyncMock(return_value={"status": "done", "result": "ok"})

        with patch("opnsense.tools.diagnostics.asyncio.sleep", new_callable=AsyncMock):
            await opnsense__diagnostics__run_ping(
                client,
                "8.8.8.8",
                source_ip="192.168.1.1",
            )

        call_data = client.post.call_args[1]["data"]
        assert call_data["source_address"] == "192.168.1.1"

    @pytest.mark.asyncio
    async def test_ping_timeout(self) -> None:
        from opnsense.tools.diagnostics import opnsense__diagnostics__run_ping

        client = AsyncMock()
        client.post = AsyncMock(return_value={"status": "started"})

        # Always running, never done -- growing output to avoid stabilisation
        call_count = 0

        async def growing(*args: Any, **kwargs: Any) -> dict[str, Any]:
            nonlocal call_count
            call_count += 1
            return {"status": "running", "result": "x" * call_count}

        client.get = AsyncMock(side_effect=growing)

        with (
            patch("opnsense.tools.diagnostics.asyncio.sleep", new_callable=AsyncMock),
            patch("opnsense.tools.diagnostics._POLL_TIMEOUT_SECONDS", 4.0),
            patch("opnsense.tools.diagnostics._POLL_INTERVAL_SECONDS", 2.0),
        ):
            response = await opnsense__diagnostics__run_ping(client, "8.8.8.8")

        assert response["completed"] is False
        assert response["host"] == "8.8.8.8"

    @pytest.mark.asyncio
    async def test_ping_output_fallback_key(self) -> None:
        """When the poll response uses 'output' instead of 'result'."""
        from opnsense.tools.diagnostics import opnsense__diagnostics__run_ping

        client = AsyncMock()
        client.post = AsyncMock(return_value={"status": "started"})
        client.get = AsyncMock(
            return_value={"status": "done", "output": "PING output here"}
        )

        with patch("opnsense.tools.diagnostics.asyncio.sleep", new_callable=AsyncMock):
            response = await opnsense__diagnostics__run_ping(client, "1.1.1.1")

        assert response["output"] == "PING output here"


# ---------------------------------------------------------------------------
# run_traceroute (26.x POST-then-poll)
# ---------------------------------------------------------------------------


class TestRunTraceroute:
    @pytest.mark.asyncio
    async def test_basic_traceroute(self) -> None:
        from opnsense.tools.diagnostics import opnsense__diagnostics__run_traceroute

        client = AsyncMock()
        client.post = AsyncMock(return_value={"status": "started"})
        client.get = AsyncMock(
            side_effect=[
                {"status": "running", "result": "1  192.168.1.1  1.2ms"},
                {
                    "status": "done",
                    "result": "1  192.168.1.1  1.2ms\n2  10.0.0.1  5.3ms\n3  8.8.8.8  12.1ms",
                },
            ]
        )

        with patch("opnsense.tools.diagnostics.asyncio.sleep", new_callable=AsyncMock):
            response = await opnsense__diagnostics__run_traceroute(client, "8.8.8.8")

        assert response["host"] == "8.8.8.8"
        assert response["completed"] is True
        assert "8.8.8.8" in response["output"]

        # Verify the start POST used the correct 26.x endpoint
        client.post.assert_called_once_with(
            "diagnostics",
            "interface",
            "trace",
            data={"address": "8.8.8.8"},
        )

    @pytest.mark.asyncio
    async def test_traceroute_with_max_hops(self) -> None:
        from opnsense.tools.diagnostics import opnsense__diagnostics__run_traceroute

        client = AsyncMock()
        client.post = AsyncMock(return_value={"status": "started"})
        client.get = AsyncMock(return_value={"status": "done", "result": "ok"})

        with patch("opnsense.tools.diagnostics.asyncio.sleep", new_callable=AsyncMock):
            await opnsense__diagnostics__run_traceroute(client, "8.8.8.8", max_hops=15)

        call_data = client.post.call_args[1]["data"]
        assert call_data["maxttl"] == "15"

    @pytest.mark.asyncio
    async def test_traceroute_timeout(self) -> None:
        from opnsense.tools.diagnostics import opnsense__diagnostics__run_traceroute

        client = AsyncMock()
        client.post = AsyncMock(return_value={"status": "started"})

        call_count = 0

        async def growing(*args: Any, **kwargs: Any) -> dict[str, Any]:
            nonlocal call_count
            call_count += 1
            return {"status": "running", "result": "hop" * call_count}

        client.get = AsyncMock(side_effect=growing)

        with (
            patch("opnsense.tools.diagnostics.asyncio.sleep", new_callable=AsyncMock),
            patch("opnsense.tools.diagnostics._POLL_TIMEOUT_SECONDS", 4.0),
            patch("opnsense.tools.diagnostics._POLL_INTERVAL_SECONDS", 2.0),
        ):
            response = await opnsense__diagnostics__run_traceroute(client, "8.8.8.8")

        assert response["completed"] is False
        assert response["host"] == "8.8.8.8"


# ---------------------------------------------------------------------------
# dns_lookup (26.x Unbound endpoint)
# ---------------------------------------------------------------------------


class TestDNSLookup:
    @pytest.mark.asyncio
    async def test_basic_lookup(self) -> None:
        from opnsense.tools.diagnostics import opnsense__diagnostics__dns_lookup

        result = {
            "rows": [
                {"hostname": "example.com", "address": "93.184.216.34", "type": "A"}
            ]
        }
        client = _make_client(get_returns=result)

        response = await opnsense__diagnostics__dns_lookup(client, "example.com")

        assert response == result
        client.get.assert_called_once_with(
            "unbound",
            "diagnostics",
            "lookup",
            params={"hostname": "example.com"},
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
            "unbound",
            "diagnostics",
            "lookup",
            params={"hostname": "example.com", "type": "MX"},
        )

    @pytest.mark.asyncio
    async def test_reverse_lookup(self) -> None:
        from opnsense.tools.diagnostics import opnsense__diagnostics__dns_lookup

        result = {"rows": [{"hostname": "dns.google", "address": "8.8.8.8"}]}
        client = _make_client(get_returns=result)

        response = await opnsense__diagnostics__dns_lookup(client, "8.8.8.8")

        assert response == result
        client.get.assert_called_once_with(
            "unbound",
            "diagnostics",
            "lookup",
            params={"hostname": "8.8.8.8"},
        )

    @pytest.mark.asyncio
    async def test_lookup_aaaa_record(self) -> None:
        from opnsense.tools.diagnostics import opnsense__diagnostics__dns_lookup

        result = {
            "rows": [{"hostname": "example.com", "address": "2606:2800:220:1::248", "type": "AAAA"}]
        }
        client = _make_client(get_returns=result)

        response = await opnsense__diagnostics__dns_lookup(
            client, "example.com", record_type="AAAA"
        )

        assert response == result


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
