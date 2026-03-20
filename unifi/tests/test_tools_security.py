"""Tests for the security MCP tools (firewall rules, ZBF, ACLs, port forwards, IDS alerts)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from tests.fixtures import load_fixture
from unifi.api.response import NormalizedResponse
from unifi.errors import APIError, NetworkError
from unifi.tools.security import (
    _filter_ids_by_time,
    _format_acl,
    _format_firewall_rule,
    _format_ids_alert,
    _format_port_forward,
    _format_zbf_policy,
    _get_client,
    unifi__security__get_acls,
    unifi__security__get_firewall_rules,
    unifi__security__get_ids_alerts,
    unifi__security__get_port_forwards,
    unifi__security__get_zbf_policies,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _normalized_from_fixture(fixture: dict[str, Any]) -> NormalizedResponse:
    data = fixture.get("data", [])
    return NormalizedResponse(
        data=data,
        count=len(data),
        total_count=None,
        meta=fixture.get("meta", {}),
    )


def _mock_client_with_normalized(fixture_data: dict[str, Any]) -> AsyncMock:
    """Create a mock client that returns a NormalizedResponse from fixture data."""
    normalized = _normalized_from_fixture(fixture_data)
    mock_client = AsyncMock()
    mock_client.get_normalized = AsyncMock(return_value=normalized)
    mock_client.close = AsyncMock()
    return mock_client


# ---------------------------------------------------------------------------
# _get_client
# ---------------------------------------------------------------------------


class TestGetClient:
    """Verify the helper builds a client from env vars."""

    def test_creates_client_from_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("UNIFI_LOCAL_HOST", "10.0.0.1")
        monkeypatch.setenv("UNIFI_LOCAL_KEY", "sec-key-123")

        client = _get_client()

        assert client._host == "10.0.0.1"
        assert client._api_key == "sec-key-123"

    def test_defaults_to_empty(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("UNIFI_LOCAL_HOST", raising=False)
        monkeypatch.delenv("UNIFI_LOCAL_KEY", raising=False)

        client = _get_client()

        assert client._host == ""
        assert client._api_key == ""


# ---------------------------------------------------------------------------
# _format_firewall_rule
# ---------------------------------------------------------------------------


class TestFormatFirewallRule:
    """Verify firewall rule field extraction."""

    def test_full_rule(self) -> None:
        raw = {
            "_id": "rule001",
            "name": "Allow LAN",
            "action": "accept",
            "enabled": True,
            "src_address": "192.168.1.0/24",
            "dst_address": "0.0.0.0/0",
            "protocol": "all",
            "rule_index": 2001,
        }
        result = _format_firewall_rule(raw)

        assert result["rule_id"] == "rule001"
        assert result["name"] == "Allow LAN"
        assert result["action"] == "accept"
        assert result["enabled"] is True
        assert result["src"] == "192.168.1.0/24"
        assert result["dst"] == "0.0.0.0/0"
        assert result["protocol"] == "all"
        assert result["position"] == 2001

    def test_missing_fields_use_defaults(self) -> None:
        raw = {"_id": "rule_min"}
        result = _format_firewall_rule(raw)

        assert result["rule_id"] == "rule_min"
        assert result["name"] == ""
        assert result["action"] == ""
        assert result["enabled"] is True
        assert result["protocol"] == "all"

    def test_fallback_to_firewallgroup_ids(self) -> None:
        raw = {
            "_id": "rule_group",
            "src_firewallgroup_ids": ["grp1", "grp2"],
            "dst_firewallgroup_ids": ["grp3"],
        }
        result = _format_firewall_rule(raw)

        assert result["src"] == ["grp1", "grp2"]
        assert result["dst"] == ["grp3"]


# ---------------------------------------------------------------------------
# _format_zbf_policy
# ---------------------------------------------------------------------------


class TestFormatZbfPolicy:
    """Verify ZBF policy field extraction."""

    def test_full_policy(self) -> None:
        raw = {
            "_id": "zbf001",
            "src_zone": "LAN",
            "dst_zone": "WAN",
            "action": "accept",
            "match_all": False,
        }
        result = _format_zbf_policy(raw)

        assert result["policy_id"] == "zbf001"
        assert result["from_zone"] == "LAN"
        assert result["to_zone"] == "WAN"
        assert result["action"] == "accept"
        assert result["match_all"] is False

    def test_fallback_zone_keys(self) -> None:
        raw = {
            "_id": "zbf_alt",
            "from_zone": "Guest",
            "to_zone": "LAN",
            "action": "drop",
        }
        result = _format_zbf_policy(raw)

        assert result["from_zone"] == "Guest"
        assert result["to_zone"] == "LAN"


# ---------------------------------------------------------------------------
# _format_acl
# ---------------------------------------------------------------------------


class TestFormatAcl:
    """Verify ACL field extraction."""

    def test_full_acl(self) -> None:
        raw = {
            "_id": "acl001",
            "name": "Mgmt ACL",
            "entries": [{"action": "allow", "src": "10.0.0.0/8"}],
            "applied_to": ["sw1"],
        }
        result = _format_acl(raw)

        assert result["acl_id"] == "acl001"
        assert result["name"] == "Mgmt ACL"
        assert len(result["entries"]) == 1
        assert result["applied_to"] == ["sw1"]

    def test_fallback_keys(self) -> None:
        raw = {
            "_id": "acl_alt",
            "name": "Alt ACL",
            "rules": [{"action": "deny"}],
            "device_ids": ["dev1", "dev2"],
        }
        result = _format_acl(raw)

        assert result["entries"] == [{"action": "deny"}]
        assert result["applied_to"] == ["dev1", "dev2"]


# ---------------------------------------------------------------------------
# _format_port_forward
# ---------------------------------------------------------------------------


class TestFormatPortForward:
    """Verify port forward field extraction."""

    def test_full_forward(self) -> None:
        raw = {
            "_id": "pf001",
            "name": "Web",
            "proto": "tcp",
            "dst_port": "443",
            "fwd": "192.168.1.100",
            "fwd_port": "443",
            "enabled": True,
        }
        result = _format_port_forward(raw)

        assert result["rule_id"] == "pf001"
        assert result["name"] == "Web"
        assert result["proto"] == "tcp"
        assert result["wan_port"] == "443"
        assert result["lan_host"] == "192.168.1.100"
        assert result["lan_port"] == "443"
        assert result["enabled"] is True

    def test_disabled_forward(self) -> None:
        raw = {"_id": "pf_off", "enabled": False}
        result = _format_port_forward(raw)

        assert result["enabled"] is False


# ---------------------------------------------------------------------------
# _format_ids_alert
# ---------------------------------------------------------------------------


class TestFormatIdsAlert:
    """Verify IDS alert field extraction."""

    def test_epoch_ms_timestamp(self) -> None:
        raw = {
            "timestamp": 1742342400000,
            "inner_alert_signature": "ET SCAN SSH Brute Force",
            "inner_alert_severity": 1,
            "src_ip": "203.0.113.50",
            "dst_ip": "192.168.1.50",
            "inner_alert_action": "blocked",
        }
        result = _format_ids_alert(raw)

        assert "2025" in result["timestamp"]  # epoch ms -> ISO
        assert result["signature"] == "ET SCAN SSH Brute Force"
        assert result["severity"] == 1
        assert result["src_ip"] == "203.0.113.50"
        assert result["dst_ip"] == "192.168.1.50"
        assert result["action_taken"] == "blocked"

    def test_iso_timestamp(self) -> None:
        raw = {
            "timestamp": "2025-03-18T12:00:00+00:00",
            "inner_alert_signature": "test sig",
        }
        result = _format_ids_alert(raw)

        assert result["timestamp"] == "2025-03-18T12:00:00+00:00"

    def test_fallback_keys(self) -> None:
        raw = {
            "datetime": 1742342400,
            "msg": "Fallback sig",
            "catname": "info",
            "action": "alert",
        }
        result = _format_ids_alert(raw)

        assert result["signature"] == "Fallback sig"
        assert result["severity"] == "info"
        assert result["action_taken"] == "alert"


# ---------------------------------------------------------------------------
# _filter_ids_by_time
# ---------------------------------------------------------------------------


class TestFilterIdsByTime:
    """Verify IDS time-window filtering."""

    def test_filters_old_events(self) -> None:
        now_ts = datetime.now(tz=UTC).timestamp()
        old_ts = (datetime.now(tz=UTC) - timedelta(hours=48)).timestamp()

        events = [
            {"timestamp": now_ts, "msg": "recent"},
            {"timestamp": old_ts, "msg": "old"},
        ]
        result = _filter_ids_by_time(events, hours=24)

        assert len(result) == 1
        assert result[0]["msg"] == "recent"

    def test_iso_string_timestamps(self) -> None:
        recent = datetime.now(tz=UTC).isoformat()
        events = [{"timestamp": recent, "msg": "recent"}]

        result = _filter_ids_by_time(events, hours=24)
        assert len(result) == 1

    def test_epoch_ms_timestamps(self) -> None:
        now_ms = datetime.now(tz=UTC).timestamp() * 1000
        events = [{"timestamp": now_ms, "msg": "recent_ms"}]

        result = _filter_ids_by_time(events, hours=24)
        assert len(result) == 1

    def test_missing_timestamp_skipped(self) -> None:
        events = [{"msg": "no timestamp"}]
        result = _filter_ids_by_time(events, hours=24)
        assert len(result) == 0

    def test_invalid_timestamp_skipped(self) -> None:
        events = [{"timestamp": "not-a-date", "msg": "bad"}]
        result = _filter_ids_by_time(events, hours=24)
        assert len(result) == 0

    def test_empty_list(self) -> None:
        result = _filter_ids_by_time([], hours=24)
        assert result == []


# ---------------------------------------------------------------------------
# Tool 1: unifi__security__get_firewall_rules
# ---------------------------------------------------------------------------


class TestGetFirewallRules:
    """Integration tests for the get_firewall_rules MCP tool."""

    async def test_returns_formatted_rules(self) -> None:
        fixture = load_fixture("firewall_rules.json")
        mock_client = _mock_client_with_normalized(fixture)

        with patch("unifi.tools.security._get_client", return_value=mock_client):
            result = await unifi__security__get_firewall_rules()

        assert isinstance(result, list)
        assert len(result) == 5
        assert result[0]["rule_id"] == "rule001"
        assert result[0]["name"] == "Allow LAN to WAN"
        assert result[0]["action"] == "accept"

        mock_client.get_normalized.assert_called_once_with(
            "/api/s/default/rest/firewallrule"
        )
        mock_client.close.assert_called_once()

    async def test_custom_site_id(self) -> None:
        fixture = load_fixture("firewall_rules.json")
        mock_client = _mock_client_with_normalized(fixture)

        with patch("unifi.tools.security._get_client", return_value=mock_client):
            await unifi__security__get_firewall_rules(site_id="site-xyz")

        mock_client.get_normalized.assert_called_once_with(
            "/api/s/site-xyz/rest/firewallrule"
        )

    async def test_empty_rules(self) -> None:
        mock_client = _mock_client_with_normalized({"data": [], "meta": {"rc": "ok"}})

        with patch("unifi.tools.security._get_client", return_value=mock_client):
            result = await unifi__security__get_firewall_rules()

        assert result == []

    async def test_api_error_propagates(self) -> None:
        mock_client = AsyncMock()
        mock_client.get_normalized = AsyncMock(
            side_effect=APIError("API error", status_code=500)
        )
        mock_client.close = AsyncMock()

        with (
            patch("unifi.tools.security._get_client", return_value=mock_client),
            pytest.raises(APIError, match="API error"),
        ):
            await unifi__security__get_firewall_rules()

        mock_client.close.assert_called_once()

    async def test_client_closed_on_error(self) -> None:
        mock_client = AsyncMock()
        mock_client.get_normalized = AsyncMock(
            side_effect=NetworkError("Connection refused")
        )
        mock_client.close = AsyncMock()

        with (
            patch("unifi.tools.security._get_client", return_value=mock_client),
            pytest.raises(NetworkError),
        ):
            await unifi__security__get_firewall_rules()

        mock_client.close.assert_called_once()


# ---------------------------------------------------------------------------
# Tool 2: unifi__security__get_zbf_policies
# ---------------------------------------------------------------------------


class TestGetZbfPolicies:
    """Integration tests for the get_zbf_policies MCP tool."""

    async def test_returns_formatted_policies(self) -> None:
        fixture = load_fixture("zbf_policies.json")
        mock_client = _mock_client_with_normalized(fixture)

        with patch("unifi.tools.security._get_client", return_value=mock_client):
            result = await unifi__security__get_zbf_policies()

        assert isinstance(result, list)
        assert len(result) == 3
        assert result[0]["from_zone"] == "LAN"
        assert result[0]["to_zone"] == "WAN"

        mock_client.get_normalized.assert_called_once_with(
            "/api/s/default/rest/firewallzone"
        )

    async def test_empty_policies(self) -> None:
        mock_client = _mock_client_with_normalized({"data": [], "meta": {"rc": "ok"}})

        with patch("unifi.tools.security._get_client", return_value=mock_client):
            result = await unifi__security__get_zbf_policies()

        assert result == []

    async def test_client_closed_on_error(self) -> None:
        mock_client = AsyncMock()
        mock_client.get_normalized = AsyncMock(
            side_effect=APIError("Forbidden", status_code=403)
        )
        mock_client.close = AsyncMock()

        with (
            patch("unifi.tools.security._get_client", return_value=mock_client),
            pytest.raises(APIError),
        ):
            await unifi__security__get_zbf_policies()

        mock_client.close.assert_called_once()


# ---------------------------------------------------------------------------
# Tool 3: unifi__security__get_acls
# ---------------------------------------------------------------------------


class TestGetAcls:
    """Integration tests for the get_acls MCP tool."""

    async def test_returns_formatted_acls(self) -> None:
        fixture = load_fixture("acl_rules.json")
        mock_client = _mock_client_with_normalized(fixture)

        with patch("unifi.tools.security._get_client", return_value=mock_client):
            result = await unifi__security__get_acls()

        assert isinstance(result, list)
        assert len(result) == 2
        assert result[0]["acl_id"] == "acl001"
        assert result[0]["name"] == "Management ACL"

        mock_client.get_normalized.assert_called_once_with(
            "/api/s/default/rest/firewallgroup"
        )

    async def test_custom_site_id(self) -> None:
        fixture = load_fixture("acl_rules.json")
        mock_client = _mock_client_with_normalized(fixture)

        with patch("unifi.tools.security._get_client", return_value=mock_client):
            await unifi__security__get_acls(site_id="branch-01")

        mock_client.get_normalized.assert_called_once_with(
            "/api/s/branch-01/rest/firewallgroup"
        )

    async def test_empty_acls(self) -> None:
        mock_client = _mock_client_with_normalized({"data": [], "meta": {"rc": "ok"}})

        with patch("unifi.tools.security._get_client", return_value=mock_client):
            result = await unifi__security__get_acls()

        assert result == []


# ---------------------------------------------------------------------------
# Tool 4: unifi__security__get_port_forwards
# ---------------------------------------------------------------------------


class TestGetPortForwards:
    """Integration tests for the get_port_forwards MCP tool."""

    async def test_returns_formatted_forwards(self) -> None:
        fixture = load_fixture("port_forwards.json")
        mock_client = _mock_client_with_normalized(fixture)

        with patch("unifi.tools.security._get_client", return_value=mock_client):
            result = await unifi__security__get_port_forwards()

        assert isinstance(result, list)
        assert len(result) == 4
        assert result[0]["name"] == "Web Server"
        assert result[0]["wan_port"] == "443"
        assert result[0]["lan_host"] == "192.168.1.100"

        mock_client.get_normalized.assert_called_once_with(
            "/api/s/default/rest/portforward"
        )

    async def test_includes_disabled_forwards(self) -> None:
        fixture = load_fixture("port_forwards.json")
        mock_client = _mock_client_with_normalized(fixture)

        with patch("unifi.tools.security._get_client", return_value=mock_client):
            result = await unifi__security__get_port_forwards()

        disabled = [r for r in result if not r["enabled"]]
        assert len(disabled) == 1
        assert disabled[0]["name"] == "Old RDP"

    async def test_empty_forwards(self) -> None:
        mock_client = _mock_client_with_normalized({"data": [], "meta": {"rc": "ok"}})

        with patch("unifi.tools.security._get_client", return_value=mock_client):
            result = await unifi__security__get_port_forwards()

        assert result == []


# ---------------------------------------------------------------------------
# Tool 5: unifi__security__get_ids_alerts
# ---------------------------------------------------------------------------


class TestGetIdsAlerts:
    """Integration tests for the get_ids_alerts MCP tool."""

    async def test_returns_formatted_alerts(self) -> None:
        # Build fixture with recent timestamps
        now_ms = datetime.now(tz=UTC).timestamp() * 1000
        fixture = {
            "data": [
                {
                    "timestamp": now_ms,
                    "inner_alert_signature": "ET SCAN SSH",
                    "inner_alert_severity": 1,
                    "src_ip": "203.0.113.50",
                    "dst_ip": "192.168.1.50",
                    "inner_alert_action": "blocked",
                },
            ],
            "meta": {"rc": "ok"},
        }
        mock_client = _mock_client_with_normalized(fixture)

        with patch("unifi.tools.security._get_client", return_value=mock_client):
            result = await unifi__security__get_ids_alerts()

        assert isinstance(result, list)
        assert len(result) == 1
        assert result[0]["signature"] == "ET SCAN SSH"
        assert result[0]["severity"] == 1

        mock_client.get_normalized.assert_called_once_with(
            "/api/s/default/stat/ips/event"
        )

    async def test_filters_by_time_window(self) -> None:
        now_ms = datetime.now(tz=UTC).timestamp() * 1000
        old_ms = (datetime.now(tz=UTC) - timedelta(hours=48)).timestamp() * 1000

        fixture = {
            "data": [
                {"timestamp": now_ms, "inner_alert_signature": "recent"},
                {"timestamp": old_ms, "inner_alert_signature": "old"},
            ],
            "meta": {"rc": "ok"},
        }
        mock_client = _mock_client_with_normalized(fixture)

        with patch("unifi.tools.security._get_client", return_value=mock_client):
            result = await unifi__security__get_ids_alerts(hours=24)

        assert len(result) == 1
        assert result[0]["signature"] == "recent"

    async def test_custom_hours_and_site(self) -> None:
        fixture = {"data": [], "meta": {"rc": "ok"}}
        mock_client = _mock_client_with_normalized(fixture)

        with patch("unifi.tools.security._get_client", return_value=mock_client):
            result = await unifi__security__get_ids_alerts(site_id="lab", hours=48)

        assert result == []
        mock_client.get_normalized.assert_called_once_with(
            "/api/s/lab/stat/ips/event"
        )

    async def test_empty_alerts(self) -> None:
        mock_client = _mock_client_with_normalized({"data": [], "meta": {"rc": "ok"}})

        with patch("unifi.tools.security._get_client", return_value=mock_client):
            result = await unifi__security__get_ids_alerts()

        assert result == []

    async def test_client_closed_on_error(self) -> None:
        mock_client = AsyncMock()
        mock_client.get_normalized = AsyncMock(
            side_effect=NetworkError("timeout")
        )
        mock_client.close = AsyncMock()

        with (
            patch("unifi.tools.security._get_client", return_value=mock_client),
            pytest.raises(NetworkError),
        ):
            await unifi__security__get_ids_alerts()

        mock_client.close.assert_called_once()
