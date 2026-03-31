"""Tests for OPNsense 26.x gateway status parsing and list_gateways tool.

Covers:
- Gateway model validation with 26.x field format
- Coercion of dpinger metrics ("4.2 ms", "0.0 %", "~")
- dpinger status code mapping (none->online, down->offline, etc.)
- DHCP gateways that disappear (empty items array)
- Gateways with no monitor IP ("~" sentinel)
- Mixed gateway states (online, offline, degraded)
- Backward compatibility with older response formats
- End-to-end list_gateways tool with mocked API responses

Test strategy:
- Unit tests for _parse_dpinger_metric and _coerce_gateway_fields helpers
- Unit tests for Gateway model with coerced data
- Integration tests for list_gateways with mocked OPNsenseClient
- Edge cases: empty response, all-tilde values, missing fields
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from opnsense.api.opnsense_client import OPNsenseClient
from opnsense.models.routing import Gateway
from opnsense.tools.routing import (
    _coerce_gateway_fields,
    _parse_dpinger_metric,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_mock_client(
    get_cached_response: dict[str, Any] | None = None,
) -> MagicMock:
    """Create a mock OPNsenseClient with configured responses."""
    client = MagicMock(spec=OPNsenseClient)
    client.close = AsyncMock()
    client.get = AsyncMock(return_value=get_cached_response or {})
    client.get_cached = AsyncMock(return_value=get_cached_response or {})
    return client


# ---------------------------------------------------------------------------
# Fixtures: 26.x response shapes
# ---------------------------------------------------------------------------

# Typical 26.x response with two online gateways (Starlink WAN + backup)
GATEWAYS_26X_ONLINE: dict[str, Any] = {
    "items": [
        {
            "name": "WAN_DHCP",
            "address": "100.94.200.2",
            "status": "none",
            "status_translated": "Online",
            "loss": "0.0 %",
            "delay": "4.231 ms",
            "stddev": "0.803 ms",
            "monitor": "1.1.1.1",
        },
        {
            "name": "WAN2_DHCP",
            "address": "192.168.10.1",
            "status": "none",
            "status_translated": "Online",
            "loss": "0.1 %",
            "delay": "12.7 ms",
            "stddev": "2.1 ms",
            "monitor": "8.8.8.8",
        },
    ],
    "status": "ok",
}

# 26.x response with one gateway down
GATEWAYS_26X_ONE_DOWN: dict[str, Any] = {
    "items": [
        {
            "name": "WAN_DHCP",
            "address": "100.94.200.2",
            "status": "none",
            "status_translated": "Online",
            "loss": "0.0 %",
            "delay": "4.2 ms",
            "stddev": "0.8 ms",
            "monitor": "1.1.1.1",
        },
        {
            "name": "WAN2_DHCP",
            "address": "~",
            "status": "down",
            "status_translated": "Offline",
            "loss": "~",
            "delay": "~",
            "stddev": "~",
            "monitor": "8.8.8.8",
        },
    ],
    "status": "ok",
}

# 26.x response with gateway showing high latency (degraded)
GATEWAYS_26X_DEGRADED: dict[str, Any] = {
    "items": [
        {
            "name": "WAN_DHCP",
            "address": "100.94.200.2",
            "status": "delay",
            "status_translated": "Latency",
            "loss": "0.0 %",
            "delay": "250.5 ms",
            "stddev": "45.2 ms",
            "monitor": "1.1.1.1",
        },
    ],
    "status": "ok",
}

# 26.x response with packet loss
GATEWAYS_26X_PACKET_LOSS: dict[str, Any] = {
    "items": [
        {
            "name": "WAN_DHCP",
            "address": "100.94.200.2",
            "status": "loss",
            "status_translated": "Packetloss",
            "loss": "15.3 %",
            "delay": "8.1 ms",
            "stddev": "3.2 ms",
            "monitor": "1.1.1.1",
        },
    ],
    "status": "ok",
}

# 26.x response with combined delay+loss
GATEWAYS_26X_DELAY_AND_LOSS: dict[str, Any] = {
    "items": [
        {
            "name": "WAN_DHCP",
            "address": "100.94.200.2",
            "status": "delay+loss",
            "status_translated": "Latency+Packetloss",
            "loss": "25.0 %",
            "delay": "500.0 ms",
            "stddev": "100.0 ms",
            "monitor": "1.1.1.1",
        },
    ],
    "status": "ok",
}

# Empty response -- DHCP gateway disappeared (lease lost)
GATEWAYS_26X_EMPTY: dict[str, Any] = {
    "items": [],
    "status": "ok",
}

# Gateway with no monitor IP configured
GATEWAYS_26X_NO_MONITOR: dict[str, Any] = {
    "items": [
        {
            "name": "WAN_DHCP",
            "address": "100.94.200.2",
            "status": "none",
            "status_translated": "Online",
            "loss": "~",
            "delay": "~",
            "stddev": "~",
            "monitor": "~",
        },
    ],
    "status": "ok",
}

# Gateway with all-tilde values (newly configured, no data yet)
GATEWAYS_26X_ALL_TILDE: dict[str, Any] = {
    "items": [
        {
            "name": "WAN_DHCP",
            "address": "~",
            "status": "none",
            "status_translated": "Online",
            "loss": "~",
            "delay": "~",
            "stddev": "~",
            "monitor": "~",
        },
    ],
    "status": "ok",
}

# Older response format (pre-26.x with interface, priority, numeric delay)
GATEWAYS_LEGACY_FORMAT: dict[str, Any] = {
    "items": [
        {
            "name": "WAN_GW",
            "address": "203.0.113.1",
            "interface": "igb0",
            "monitor": "8.8.8.8",
            "status": "online",
            "priority": 255,
            "delay": 4.2,
        },
    ],
}

# Response with "force_down" status (manually forced down in web UI)
GATEWAYS_26X_FORCE_DOWN: dict[str, Any] = {
    "items": [
        {
            "name": "WAN2_DHCP",
            "address": "192.168.10.1",
            "status": "force_down",
            "status_translated": "Offline (forced)",
            "loss": "~",
            "delay": "~",
            "stddev": "~",
            "monitor": "8.8.8.8",
        },
    ],
    "status": "ok",
}

# Response where items come via "rows" key instead (unlikely but handled)
GATEWAYS_ROWS_FORMAT: dict[str, Any] = {
    "rows": [
        {
            "name": "WAN_DHCP",
            "address": "100.94.200.2",
            "status": "none",
            "status_translated": "Online",
            "loss": "0.0 %",
            "delay": "5.0 ms",
            "stddev": "1.0 ms",
            "monitor": "1.1.1.1",
        },
    ],
}


# ===========================================================================
# Unit tests: _parse_dpinger_metric
# ===========================================================================


class TestParseDpingerMetric:
    """_parse_dpinger_metric() helper."""

    def test_tilde_returns_none(self) -> None:
        assert _parse_dpinger_metric("~") is None

    def test_empty_string_returns_none(self) -> None:
        assert _parse_dpinger_metric("") is None

    def test_none_returns_none(self) -> None:
        assert _parse_dpinger_metric(None) is None

    def test_ms_suffix(self) -> None:
        assert _parse_dpinger_metric("4.231 ms") == pytest.approx(4.231)

    def test_percent_suffix(self) -> None:
        assert _parse_dpinger_metric("0.0 %") == pytest.approx(0.0)

    def test_large_percent(self) -> None:
        assert _parse_dpinger_metric("15.3 %") == pytest.approx(15.3)

    def test_numeric_float(self) -> None:
        assert _parse_dpinger_metric(4.2) == pytest.approx(4.2)

    def test_numeric_int(self) -> None:
        assert _parse_dpinger_metric(12) == pytest.approx(12.0)

    def test_numeric_string_no_unit(self) -> None:
        assert _parse_dpinger_metric("4.2") == pytest.approx(4.2)

    def test_ms_no_space(self) -> None:
        assert _parse_dpinger_metric("4.2ms") == pytest.approx(4.2)

    def test_whitespace_padding(self) -> None:
        assert _parse_dpinger_metric("  4.2 ms  ") == pytest.approx(4.2)

    def test_invalid_string_returns_none(self) -> None:
        assert _parse_dpinger_metric("not a number") is None

    def test_non_string_non_numeric_returns_none(self) -> None:
        assert _parse_dpinger_metric([1, 2]) is None

    def test_zero_ms(self) -> None:
        assert _parse_dpinger_metric("0.000 ms") == pytest.approx(0.0)


# ===========================================================================
# Unit tests: _coerce_gateway_fields
# ===========================================================================


class TestCoerceGatewayFields:
    """_coerce_gateway_fields() helper."""

    def test_26x_online_gateway(self) -> None:
        raw = {
            "name": "WAN_DHCP",
            "address": "100.94.200.2",
            "status": "none",
            "status_translated": "Online",
            "loss": "0.0 %",
            "delay": "4.2 ms",
            "stddev": "0.8 ms",
            "monitor": "1.1.1.1",
        }
        coerced = _coerce_gateway_fields(raw)
        assert coerced["name"] == "WAN_DHCP"
        assert coerced["address"] == "100.94.200.2"
        assert coerced["status"] == "online"
        assert coerced["delay"] == pytest.approx(4.2)
        assert coerced["loss_pct"] == pytest.approx(0.0)
        assert coerced["stddev_ms"] == pytest.approx(0.8)
        assert coerced["monitor"] == "1.1.1.1"

    def test_26x_down_gateway_tilde_values(self) -> None:
        raw = {
            "name": "WAN2_DHCP",
            "address": "~",
            "status": "down",
            "status_translated": "Offline",
            "loss": "~",
            "delay": "~",
            "stddev": "~",
            "monitor": "8.8.8.8",
        }
        coerced = _coerce_gateway_fields(raw)
        assert coerced["address"] == ""
        assert coerced["status"] == "offline"
        assert coerced["delay"] is None
        assert coerced["loss_pct"] is None
        assert coerced["stddev_ms"] is None

    def test_26x_degraded_high_latency(self) -> None:
        raw = {
            "name": "WAN_DHCP",
            "address": "100.94.200.2",
            "status": "delay",
            "status_translated": "Latency",
            "loss": "0.0 %",
            "delay": "250.5 ms",
            "stddev": "45.2 ms",
            "monitor": "1.1.1.1",
        }
        coerced = _coerce_gateway_fields(raw)
        assert coerced["status"] == "degraded"
        assert coerced["delay"] == pytest.approx(250.5)

    def test_26x_loss_status(self) -> None:
        raw = {
            "name": "WAN_DHCP",
            "address": "100.94.200.2",
            "status": "loss",
            "loss": "15.3 %",
            "delay": "8.1 ms",
            "stddev": "3.2 ms",
            "monitor": "1.1.1.1",
        }
        coerced = _coerce_gateway_fields(raw)
        assert coerced["status"] == "degraded"
        assert coerced["loss_pct"] == pytest.approx(15.3)

    def test_26x_delay_plus_loss(self) -> None:
        raw = {
            "name": "WAN_DHCP",
            "address": "100.94.200.2",
            "status": "delay+loss",
            "loss": "25.0 %",
            "delay": "500.0 ms",
            "stddev": "100.0 ms",
            "monitor": "1.1.1.1",
        }
        coerced = _coerce_gateway_fields(raw)
        assert coerced["status"] == "degraded"

    def test_force_down_status(self) -> None:
        raw = {
            "name": "WAN2_DHCP",
            "address": "192.168.10.1",
            "status": "force_down",
            "loss": "~",
            "delay": "~",
            "stddev": "~",
            "monitor": "8.8.8.8",
        }
        coerced = _coerce_gateway_fields(raw)
        assert coerced["status"] == "offline"

    def test_tilde_monitor(self) -> None:
        raw = {
            "name": "WAN_DHCP",
            "address": "100.94.200.2",
            "status": "none",
            "monitor": "~",
            "loss": "~",
            "delay": "~",
            "stddev": "~",
        }
        coerced = _coerce_gateway_fields(raw)
        assert coerced["monitor"] == ""  # "~" sentinel normalized to empty string

    def test_legacy_numeric_delay_preserved(self) -> None:
        """Backward compat: older versions may return numeric delay."""
        raw = {
            "name": "WAN_GW",
            "address": "203.0.113.1",
            "status": "online",
            "delay": 4.2,
            "monitor": "8.8.8.8",
        }
        coerced = _coerce_gateway_fields(raw)
        assert coerced["delay"] == pytest.approx(4.2)
        # "online" is not in dpinger map, so kept as-is
        assert coerced["status"] == "online"

    def test_priority_coercion_string(self) -> None:
        raw = {
            "name": "WAN_GW",
            "address": "203.0.113.1",
            "status": "none",
            "priority": "255",
            "delay": "~",
        }
        coerced = _coerce_gateway_fields(raw)
        assert coerced["priority"] == 255

    def test_priority_coercion_invalid(self) -> None:
        raw = {
            "name": "WAN_GW",
            "address": "203.0.113.1",
            "status": "none",
            "priority": "invalid",
            "delay": "~",
        }
        coerced = _coerce_gateway_fields(raw)
        assert coerced["priority"] == 255

    def test_loss_and_stddev_removed_from_dict(self) -> None:
        """loss and stddev are popped and replaced with loss_pct/stddev_ms."""
        raw = {
            "name": "WAN_DHCP",
            "address": "100.94.200.2",
            "status": "none",
            "loss": "0.0 %",
            "delay": "4.2 ms",
            "stddev": "0.8 ms",
            "monitor": "1.1.1.1",
        }
        coerced = _coerce_gateway_fields(raw)
        assert "loss" not in coerced
        assert "stddev" not in coerced
        assert "loss_pct" in coerced
        assert "stddev_ms" in coerced


# ===========================================================================
# Unit tests: Gateway model
# ===========================================================================


class TestGatewayModel:
    """Gateway Pydantic model with coerced 26.x data."""

    def test_26x_online_gateway(self) -> None:
        coerced = _coerce_gateway_fields(
            {
                "name": "WAN_DHCP",
                "address": "100.94.200.2",
                "status": "none",
                "status_translated": "Online",
                "loss": "0.0 %",
                "delay": "4.231 ms",
                "stddev": "0.803 ms",
                "monitor": "1.1.1.1",
            }
        )
        gw = Gateway.model_validate(coerced)
        assert gw.name == "WAN_DHCP"
        assert gw.gateway == "100.94.200.2"
        assert gw.status == "online"
        assert gw.status_translated == "Online"
        assert gw.monitor == "1.1.1.1"
        assert gw.rtt_ms == pytest.approx(4.231)
        assert gw.loss_pct == pytest.approx(0.0)
        assert gw.stddev_ms == pytest.approx(0.803)
        assert gw.interface == ""
        assert gw.priority == 255

    def test_26x_down_gateway(self) -> None:
        coerced = _coerce_gateway_fields(
            {
                "name": "WAN2_DHCP",
                "address": "~",
                "status": "down",
                "status_translated": "Offline",
                "loss": "~",
                "delay": "~",
                "stddev": "~",
                "monitor": "8.8.8.8",
            }
        )
        gw = Gateway.model_validate(coerced)
        assert gw.name == "WAN2_DHCP"
        assert gw.gateway == ""
        assert gw.status == "offline"
        assert gw.rtt_ms is None
        assert gw.loss_pct is None
        assert gw.stddev_ms is None

    def test_model_dump_by_alias_false(self) -> None:
        """Verify model_dump(by_alias=False) uses Python field names."""
        coerced = _coerce_gateway_fields(
            {
                "name": "WAN_DHCP",
                "address": "100.94.200.2",
                "status": "none",
                "loss": "0.0 %",
                "delay": "4.2 ms",
                "stddev": "0.8 ms",
                "monitor": "1.1.1.1",
            }
        )
        gw = Gateway.model_validate(coerced)
        dumped = gw.model_dump(by_alias=False)
        assert "gateway" in dumped  # not "address"
        assert "rtt_ms" in dumped  # not "delay"
        assert dumped["gateway"] == "100.94.200.2"
        assert dumped["rtt_ms"] == pytest.approx(4.2)

    def test_legacy_format_still_works(self) -> None:
        """Backward compat: older response with interface/priority/numeric delay."""
        coerced = _coerce_gateway_fields(
            {
                "name": "WAN_GW",
                "address": "203.0.113.1",
                "interface": "igb0",
                "monitor": "8.8.8.8",
                "status": "online",
                "priority": 255,
                "delay": 4.2,
            }
        )
        gw = Gateway.model_validate(coerced)
        assert gw.name == "WAN_GW"
        assert gw.gateway == "203.0.113.1"
        assert gw.interface == "igb0"
        assert gw.status == "online"
        assert gw.priority == 255
        assert gw.rtt_ms == pytest.approx(4.2)


# ===========================================================================
# Integration tests: opnsense__routing__list_gateways
# ===========================================================================


class TestListGateways:
    """opnsense__routing__list_gateways() end-to-end with mocked API."""

    @pytest.mark.asyncio
    async def test_26x_returns_all_gateways(self) -> None:
        mock_client = _make_mock_client(get_cached_response=GATEWAYS_26X_ONLINE)
        with patch("opnsense.tools.routing._get_client", return_value=mock_client):
            from opnsense.tools.routing import opnsense__routing__list_gateways

            result = await opnsense__routing__list_gateways()

        assert len(result) == 2
        assert result[0]["name"] == "WAN_DHCP"
        assert result[1]["name"] == "WAN2_DHCP"

    @pytest.mark.asyncio
    async def test_26x_gateway_fields_correct(self) -> None:
        mock_client = _make_mock_client(get_cached_response=GATEWAYS_26X_ONLINE)
        with patch("opnsense.tools.routing._get_client", return_value=mock_client):
            from opnsense.tools.routing import opnsense__routing__list_gateways

            result = await opnsense__routing__list_gateways()

        gw = result[0]
        assert gw["name"] == "WAN_DHCP"
        assert gw["gateway"] == "100.94.200.2"
        assert gw["status"] == "online"
        assert gw["monitor"] == "1.1.1.1"
        assert gw["rtt_ms"] == pytest.approx(4.231)
        assert gw["loss_pct"] == pytest.approx(0.0)
        assert gw["stddev_ms"] == pytest.approx(0.803)

    @pytest.mark.asyncio
    async def test_26x_one_down_gateway(self) -> None:
        mock_client = _make_mock_client(get_cached_response=GATEWAYS_26X_ONE_DOWN)
        with patch("opnsense.tools.routing._get_client", return_value=mock_client):
            from opnsense.tools.routing import opnsense__routing__list_gateways

            result = await opnsense__routing__list_gateways()

        assert len(result) == 2
        online = result[0]
        offline = result[1]
        assert online["status"] == "online"
        assert online["rtt_ms"] == pytest.approx(4.2)
        assert offline["status"] == "offline"
        assert offline["gateway"] == ""
        assert offline["rtt_ms"] is None

    @pytest.mark.asyncio
    async def test_26x_degraded_gateway(self) -> None:
        mock_client = _make_mock_client(get_cached_response=GATEWAYS_26X_DEGRADED)
        with patch("opnsense.tools.routing._get_client", return_value=mock_client):
            from opnsense.tools.routing import opnsense__routing__list_gateways

            result = await opnsense__routing__list_gateways()

        assert len(result) == 1
        assert result[0]["status"] == "degraded"
        assert result[0]["rtt_ms"] == pytest.approx(250.5)

    @pytest.mark.asyncio
    async def test_26x_packet_loss(self) -> None:
        mock_client = _make_mock_client(get_cached_response=GATEWAYS_26X_PACKET_LOSS)
        with patch("opnsense.tools.routing._get_client", return_value=mock_client):
            from opnsense.tools.routing import opnsense__routing__list_gateways

            result = await opnsense__routing__list_gateways()

        assert result[0]["status"] == "degraded"
        assert result[0]["loss_pct"] == pytest.approx(15.3)

    @pytest.mark.asyncio
    async def test_26x_delay_and_loss(self) -> None:
        mock_client = _make_mock_client(
            get_cached_response=GATEWAYS_26X_DELAY_AND_LOSS,
        )
        with patch("opnsense.tools.routing._get_client", return_value=mock_client):
            from opnsense.tools.routing import opnsense__routing__list_gateways

            result = await opnsense__routing__list_gateways()

        assert result[0]["status"] == "degraded"
        assert result[0]["loss_pct"] == pytest.approx(25.0)
        assert result[0]["rtt_ms"] == pytest.approx(500.0)

    @pytest.mark.asyncio
    async def test_empty_response_returns_empty_list(self) -> None:
        """DHCP gateways disappear entirely when lease is lost."""
        mock_client = _make_mock_client(get_cached_response=GATEWAYS_26X_EMPTY)
        with patch("opnsense.tools.routing._get_client", return_value=mock_client):
            from opnsense.tools.routing import opnsense__routing__list_gateways

            result = await opnsense__routing__list_gateways()

        assert result == []

    @pytest.mark.asyncio
    async def test_no_monitor_ip(self) -> None:
        mock_client = _make_mock_client(get_cached_response=GATEWAYS_26X_NO_MONITOR)
        with patch("opnsense.tools.routing._get_client", return_value=mock_client):
            from opnsense.tools.routing import opnsense__routing__list_gateways

            result = await opnsense__routing__list_gateways()

        assert len(result) == 1
        # Monitor "~" is not in the str_field normalization list for
        # _coerce_gateway_fields, but the model stores it as-is.
        # The gateway should still parse successfully.
        assert result[0]["name"] == "WAN_DHCP"
        assert result[0]["rtt_ms"] is None

    @pytest.mark.asyncio
    async def test_all_tilde_values(self) -> None:
        mock_client = _make_mock_client(get_cached_response=GATEWAYS_26X_ALL_TILDE)
        with patch("opnsense.tools.routing._get_client", return_value=mock_client):
            from opnsense.tools.routing import opnsense__routing__list_gateways

            result = await opnsense__routing__list_gateways()

        assert len(result) == 1
        gw = result[0]
        assert gw["name"] == "WAN_DHCP"
        assert gw["gateway"] == ""  # "~" -> ""
        assert gw["status"] == "online"  # "none" -> "online"
        assert gw["rtt_ms"] is None
        assert gw["loss_pct"] is None
        assert gw["stddev_ms"] is None

    @pytest.mark.asyncio
    async def test_force_down_status(self) -> None:
        mock_client = _make_mock_client(get_cached_response=GATEWAYS_26X_FORCE_DOWN)
        with patch("opnsense.tools.routing._get_client", return_value=mock_client):
            from opnsense.tools.routing import opnsense__routing__list_gateways

            result = await opnsense__routing__list_gateways()

        assert len(result) == 1
        assert result[0]["status"] == "offline"

    @pytest.mark.asyncio
    async def test_legacy_format_backward_compat(self) -> None:
        """Older OPNsense versions with interface/priority/numeric delay."""
        mock_client = _make_mock_client(get_cached_response=GATEWAYS_LEGACY_FORMAT)
        with patch("opnsense.tools.routing._get_client", return_value=mock_client):
            from opnsense.tools.routing import opnsense__routing__list_gateways

            result = await opnsense__routing__list_gateways()

        assert len(result) == 1
        gw = result[0]
        assert gw["name"] == "WAN_GW"
        assert gw["gateway"] == "203.0.113.1"
        assert gw["interface"] == "igb0"
        assert gw["status"] == "online"
        assert gw["priority"] == 255
        assert gw["rtt_ms"] == pytest.approx(4.2)

    @pytest.mark.asyncio
    async def test_rows_fallback(self) -> None:
        """Falls back to 'rows' key if 'items' is empty/missing."""
        mock_client = _make_mock_client(get_cached_response=GATEWAYS_ROWS_FORMAT)
        with patch("opnsense.tools.routing._get_client", return_value=mock_client):
            from opnsense.tools.routing import opnsense__routing__list_gateways

            result = await opnsense__routing__list_gateways()

        assert len(result) == 1
        assert result[0]["name"] == "WAN_DHCP"

    @pytest.mark.asyncio
    async def test_completely_empty_response(self) -> None:
        """API returns empty dict (unexpected but handled)."""
        mock_client = _make_mock_client(get_cached_response={})
        with patch("opnsense.tools.routing._get_client", return_value=mock_client):
            from opnsense.tools.routing import opnsense__routing__list_gateways

            result = await opnsense__routing__list_gateways()

        assert result == []

    @pytest.mark.asyncio
    async def test_failed_status_with_empty_items(self) -> None:
        """API returns failed status -- should still return empty list."""
        mock_client = _make_mock_client(
            get_cached_response={"items": [], "status": "failed"},
        )
        with patch("opnsense.tools.routing._get_client", return_value=mock_client):
            from opnsense.tools.routing import opnsense__routing__list_gateways

            result = await opnsense__routing__list_gateways()

        assert result == []

    @pytest.mark.asyncio
    async def test_client_closed_after_request(self) -> None:
        mock_client = _make_mock_client(get_cached_response=GATEWAYS_26X_ONLINE)
        with patch("opnsense.tools.routing._get_client", return_value=mock_client):
            from opnsense.tools.routing import opnsense__routing__list_gateways

            await opnsense__routing__list_gateways()

        mock_client.close.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_client_closed_on_error(self) -> None:
        mock_client = _make_mock_client()
        mock_client.get_cached = AsyncMock(side_effect=RuntimeError("API error"))
        with (
            patch("opnsense.tools.routing._get_client", return_value=mock_client),
            pytest.raises(RuntimeError, match="API error"),
        ):
            from opnsense.tools.routing import opnsense__routing__list_gateways

            await opnsense__routing__list_gateways()

        mock_client.close.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_malformed_gateway_entry_skipped(self) -> None:
        """A gateway entry missing 'name' should be skipped, not crash."""
        response = {
            "items": [
                {
                    "name": "WAN_DHCP",
                    "address": "100.94.200.2",
                    "status": "none",
                    "delay": "4.2 ms",
                    "monitor": "1.1.1.1",
                },
                {
                    # Missing "name" -- required field
                    "address": "192.168.10.1",
                    "status": "none",
                    "delay": "5.0 ms",
                    "monitor": "8.8.8.8",
                },
            ],
            "status": "ok",
        }
        mock_client = _make_mock_client(get_cached_response=response)
        with patch("opnsense.tools.routing._get_client", return_value=mock_client):
            from opnsense.tools.routing import opnsense__routing__list_gateways

            result = await opnsense__routing__list_gateways()

        # First gateway parses OK, second is skipped
        assert len(result) == 1
        assert result[0]["name"] == "WAN_DHCP"
