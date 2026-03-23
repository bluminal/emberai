"""Tests for the config MCP tools (config snapshot, diff baseline, backup state)."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from tests.fixtures import load_fixture
from unifi.api.response import NormalizedResponse
from unifi.errors import APIError, NetworkError
from unifi.tools.config import (
    _baselines,
    _compute_structural_diff,
    _get_client,
    unifi__config__diff_baseline,
    unifi__config__get_backup_state,
    unifi__config__get_config_snapshot,
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


def _mock_client_for_snapshot() -> AsyncMock:
    """Create a mock client that returns data for all config snapshot endpoints."""
    networks_fixture = load_fixture("vlan_config.json")
    # Build minimal wlan and firewall fixtures
    wlan_fixture = {
        "data": [
            {"_id": "wlan001", "name": "HomeNet", "ssid": "HomeNet", "enabled": True},
            {"_id": "wlan002", "name": "GuestNet", "ssid": "GuestNet", "enabled": True},
        ],
        "meta": {"rc": "ok"},
    }
    firewall_fixture = load_fixture("firewall_rules.json")

    mock_client = AsyncMock()

    async def mock_get_normalized(endpoint: str) -> NormalizedResponse:
        if "networkconf" in endpoint:
            return _normalized_from_fixture(networks_fixture)
        elif "wlanconf" in endpoint:
            return _normalized_from_fixture(wlan_fixture)
        elif "firewallrule" in endpoint:
            return _normalized_from_fixture(firewall_fixture)
        elif "sysinfo" in endpoint:
            return _normalized_from_fixture(load_fixture("sysinfo.json"))
        return _normalized_from_fixture({"data": [], "meta": {"rc": "ok"}})

    mock_client.get_normalized = AsyncMock(side_effect=mock_get_normalized)
    mock_client.close = AsyncMock()
    return mock_client


# ---------------------------------------------------------------------------
# _get_client
# ---------------------------------------------------------------------------


class TestGetClient:
    """Verify the helper builds a client from env vars."""

    def test_creates_client_from_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("UNIFI_LOCAL_HOST", "10.0.0.1")
        monkeypatch.setenv("UNIFI_LOCAL_KEY", "cfg-key-456")

        client = _get_client()

        assert client._host == "10.0.0.1"
        assert client._api_key == "cfg-key-456"

    def test_defaults_to_empty(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("UNIFI_LOCAL_HOST", raising=False)
        monkeypatch.delenv("UNIFI_LOCAL_KEY", raising=False)

        client = _get_client()

        assert client._host == ""
        assert client._api_key == ""


# ---------------------------------------------------------------------------
# _compute_structural_diff
# ---------------------------------------------------------------------------


class TestComputeStructuralDiff:
    """Verify structural diff computation."""

    def test_no_changes(self) -> None:
        config = {
            "networks": [{"_id": "net1", "name": "LAN"}],
            "wlans": [{"_id": "wlan1", "name": "Home"}],
            "firewall_rules": [],
        }
        diff = _compute_structural_diff(config, config)

        assert diff["added"] == []
        assert diff["removed"] == []
        assert diff["modified"] == []

    def test_added_items(self) -> None:
        current = {
            "networks": [
                {"_id": "net1", "name": "LAN"},
                {"_id": "net2", "name": "Guest"},
            ],
            "wlans": [],
            "firewall_rules": [],
        }
        baseline = {
            "networks": [{"_id": "net1", "name": "LAN"}],
            "wlans": [],
            "firewall_rules": [],
        }
        diff = _compute_structural_diff(current, baseline)

        assert len(diff["added"]) == 1
        assert diff["added"][0]["id"] == "net2"
        assert diff["added"][0]["name"] == "Guest"
        assert diff["added"][0]["section"] == "networks"

    def test_removed_items(self) -> None:
        current = {
            "networks": [],
            "wlans": [],
            "firewall_rules": [],
        }
        baseline = {
            "networks": [{"_id": "net1", "name": "Old Net"}],
            "wlans": [],
            "firewall_rules": [],
        }
        diff = _compute_structural_diff(current, baseline)

        assert len(diff["removed"]) == 1
        assert diff["removed"][0]["id"] == "net1"

    def test_modified_items(self) -> None:
        current = {
            "networks": [{"_id": "net1", "name": "LAN-New", "subnet": "10.0.0.0/24"}],
            "wlans": [],
            "firewall_rules": [],
        }
        baseline = {
            "networks": [{"_id": "net1", "name": "LAN", "subnet": "192.168.1.0/24"}],
            "wlans": [],
            "firewall_rules": [],
        }
        diff = _compute_structural_diff(current, baseline)

        assert len(diff["modified"]) == 1
        assert diff["modified"][0]["id"] == "net1"
        assert diff["modified"][0]["name"] == "LAN-New"

    def test_mixed_changes(self) -> None:
        current = {
            "networks": [{"_id": "net1", "name": "Changed"}],
            "wlans": [{"_id": "wlan2", "name": "New WLAN"}],
            "firewall_rules": [],
        }
        baseline = {
            "networks": [{"_id": "net1", "name": "Original"}],
            "wlans": [{"_id": "wlan1", "name": "Old WLAN"}],
            "firewall_rules": [{"_id": "rule1", "name": "Old Rule"}],
        }
        diff = _compute_structural_diff(current, baseline)

        assert len(diff["added"]) == 1  # wlan2
        assert len(diff["removed"]) == 2  # wlan1 + rule1
        assert len(diff["modified"]) == 1  # net1

    def test_empty_configs(self) -> None:
        diff = _compute_structural_diff(
            {"networks": [], "wlans": [], "firewall_rules": []},
            {"networks": [], "wlans": [], "firewall_rules": []},
        )
        assert diff["added"] == []
        assert diff["removed"] == []
        assert diff["modified"] == []


# ---------------------------------------------------------------------------
# Tool 1: unifi__config__get_config_snapshot
# ---------------------------------------------------------------------------


class TestGetConfigSnapshot:
    """Integration tests for the get_config_snapshot MCP tool."""

    async def test_returns_snapshot(self) -> None:
        mock_client = _mock_client_for_snapshot()

        with patch("unifi.tools.config._get_client", return_value=mock_client):
            result = await unifi__config__get_config_snapshot()

        assert result["site_id"] == "default"
        assert "timestamp" in result
        assert result["network_count"] == 4  # from vlan_config fixture
        assert result["wlan_count"] == 2
        assert result["rule_count"] == 5  # from firewall_rules fixture
        assert "raw_config" in result
        assert len(result["raw_config"]["networks"]) == 4
        assert len(result["raw_config"]["wlans"]) == 2

    async def test_custom_site_id(self) -> None:
        mock_client = _mock_client_for_snapshot()

        with patch("unifi.tools.config._get_client", return_value=mock_client):
            result = await unifi__config__get_config_snapshot(site_id="branch")

        assert result["site_id"] == "branch"

    async def test_empty_config(self) -> None:
        mock_client = AsyncMock()
        empty_resp = NormalizedResponse(data=[], count=0, total_count=None, meta={})
        mock_client.get_normalized = AsyncMock(return_value=empty_resp)
        mock_client.close = AsyncMock()

        with patch("unifi.tools.config._get_client", return_value=mock_client):
            result = await unifi__config__get_config_snapshot()

        assert result["network_count"] == 0
        assert result["wlan_count"] == 0
        assert result["rule_count"] == 0

    async def test_api_error_propagates(self) -> None:
        mock_client = AsyncMock()
        mock_client.get_normalized = AsyncMock(
            side_effect=APIError("Server error", status_code=500)
        )
        mock_client.close = AsyncMock()

        with (
            patch("unifi.tools.config._get_client", return_value=mock_client),
            pytest.raises(APIError, match="Server error"),
        ):
            await unifi__config__get_config_snapshot()

        mock_client.close.assert_called_once()


# ---------------------------------------------------------------------------
# Tool 2: unifi__config__diff_baseline
# ---------------------------------------------------------------------------


class TestDiffBaseline:
    """Integration tests for the diff_baseline MCP tool."""

    def setup_method(self) -> None:
        """Clear baselines between tests."""
        _baselines.clear()

    async def test_no_baseline_returns_error(self) -> None:
        result = await unifi__config__diff_baseline()

        assert "error" in result
        assert "No baseline found" in result["error"]
        assert result["added"] == []
        assert result["removed"] == []
        assert result["modified"] == []

    async def test_with_matching_baseline(self) -> None:
        # Store a baseline
        baseline_config = {
            "networks": [{"_id": "net1", "name": "LAN"}],
            "wlans": [{"_id": "wlan1", "name": "Home"}],
            "firewall_rules": [],
        }
        _baselines["default:latest"] = baseline_config

        # Mock current config to match baseline
        mock_client = AsyncMock()

        call_count = 0

        async def mock_get_normalized(endpoint: str) -> NormalizedResponse:
            nonlocal call_count
            if "networkconf" in endpoint:
                return NormalizedResponse(data=[{"_id": "net1", "name": "LAN"}], count=1, meta={})
            elif "wlanconf" in endpoint:
                return NormalizedResponse(data=[{"_id": "wlan1", "name": "Home"}], count=1, meta={})
            elif "firewallrule" in endpoint:
                return NormalizedResponse(data=[], count=0, meta={})
            return NormalizedResponse(data=[], count=0, meta={})

        mock_client.get_normalized = AsyncMock(side_effect=mock_get_normalized)
        mock_client.close = AsyncMock()

        with patch("unifi.tools.config._get_client", return_value=mock_client):
            result = await unifi__config__diff_baseline()

        assert result["added"] == []
        assert result["removed"] == []
        assert result["modified"] == []

    async def test_with_drifted_baseline(self) -> None:
        # Store a baseline
        _baselines["default:latest"] = {
            "networks": [{"_id": "net1", "name": "OldLAN"}],
            "wlans": [],
            "firewall_rules": [],
        }

        mock_client = AsyncMock()

        async def mock_get_normalized(endpoint: str) -> NormalizedResponse:
            if "networkconf" in endpoint:
                return NormalizedResponse(
                    data=[{"_id": "net1", "name": "NewLAN"}], count=1, meta={}
                )
            elif "wlanconf" in endpoint or "firewallrule" in endpoint:
                return NormalizedResponse(data=[], count=0, meta={})
            return NormalizedResponse(data=[], count=0, meta={})

        mock_client.get_normalized = AsyncMock(side_effect=mock_get_normalized)
        mock_client.close = AsyncMock()

        with patch("unifi.tools.config._get_client", return_value=mock_client):
            result = await unifi__config__diff_baseline()

        assert len(result["modified"]) == 1
        assert result["modified"][0]["id"] == "net1"

    async def test_custom_baseline_id(self) -> None:
        _baselines["default:v1.0"] = {
            "networks": [],
            "wlans": [],
            "firewall_rules": [],
        }

        mock_client = AsyncMock()
        empty_resp = NormalizedResponse(data=[], count=0, meta={})
        mock_client.get_normalized = AsyncMock(return_value=empty_resp)
        mock_client.close = AsyncMock()

        with patch("unifi.tools.config._get_client", return_value=mock_client):
            result = await unifi__config__diff_baseline(site_id="default", baseline_id="v1.0")

        assert result["added"] == []
        assert result["removed"] == []
        assert result["modified"] == []


# ---------------------------------------------------------------------------
# Tool 3: unifi__config__get_backup_state
# ---------------------------------------------------------------------------


class TestGetBackupState:
    """Integration tests for the get_backup_state MCP tool."""

    async def test_returns_backup_state(self) -> None:
        fixture = load_fixture("sysinfo.json")
        mock_client = AsyncMock()
        mock_client.get_normalized = AsyncMock(return_value=_normalized_from_fixture(fixture))
        mock_client.close = AsyncMock()

        with patch("unifi.tools.config._get_client", return_value=mock_client):
            result = await unifi__config__get_backup_state()

        assert result["last_backup_time"] != ""
        assert result["backup_type"] == "auto"
        assert result["size_mb"] == 12.5
        assert result["cloud_enabled"] is True

        mock_client.get_normalized.assert_called_once_with("/api/s/default/stat/sysinfo")

    async def test_custom_site_id(self) -> None:
        fixture = load_fixture("sysinfo.json")
        mock_client = AsyncMock()
        mock_client.get_normalized = AsyncMock(return_value=_normalized_from_fixture(fixture))
        mock_client.close = AsyncMock()

        with patch("unifi.tools.config._get_client", return_value=mock_client):
            await unifi__config__get_backup_state(site_id="remote")

        mock_client.get_normalized.assert_called_once_with("/api/s/remote/stat/sysinfo")

    async def test_empty_sysinfo(self) -> None:
        mock_client = AsyncMock()
        mock_client.get_normalized = AsyncMock(
            return_value=NormalizedResponse(data=[], count=0, meta={})
        )
        mock_client.close = AsyncMock()

        with patch("unifi.tools.config._get_client", return_value=mock_client):
            result = await unifi__config__get_backup_state()

        assert result["last_backup_time"] == ""
        assert result["cloud_enabled"] is False

    async def test_no_cloud_backup(self) -> None:
        fixture = {
            "data": [
                {
                    "autobackup": False,
                    "cloud_key": "",
                    "cloud_backup_enabled": False,
                }
            ],
            "meta": {"rc": "ok"},
        }
        mock_client = AsyncMock()
        mock_client.get_normalized = AsyncMock(return_value=_normalized_from_fixture(fixture))
        mock_client.close = AsyncMock()

        with patch("unifi.tools.config._get_client", return_value=mock_client):
            result = await unifi__config__get_backup_state()

        assert result["cloud_enabled"] is False
        assert result["backup_type"] == "manual"

    async def test_client_closed_on_error(self) -> None:
        mock_client = AsyncMock()
        mock_client.get_normalized = AsyncMock(side_effect=NetworkError("timeout"))
        mock_client.close = AsyncMock()

        with (
            patch("unifi.tools.config._get_client", return_value=mock_client),
            pytest.raises(NetworkError),
        ):
            await unifi__config__get_backup_state()

        mock_client.close.assert_called_once()
