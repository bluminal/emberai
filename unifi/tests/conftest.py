"""Shared pytest fixtures for UniFi plugin tests."""

from __future__ import annotations

from typing import Any

import pytest

from tests.fixtures import load_fixture

# ---------------------------------------------------------------------------
# Raw API response fixtures (full envelope: {"data": [...], "meta": {...}})
# ---------------------------------------------------------------------------


@pytest.fixture()
def device_list_response() -> dict[str, Any]:
    """Full UniFi API response for /api/s/default/stat/device (3 devices)."""
    return load_fixture("device_list.json")


@pytest.fixture()
def device_single_response() -> dict[str, Any]:
    """Full UniFi API response for a single device with port_table detail."""
    return load_fixture("device_single.json")


@pytest.fixture()
def client_list_response() -> dict[str, Any]:
    """Full UniFi API response for /api/s/default/stat/sta (6 clients)."""
    return load_fixture("client_list.json")


@pytest.fixture()
def event_list_response() -> dict[str, Any]:
    """Full UniFi API response for /api/s/default/stat/event (6 events)."""
    return load_fixture("event_list.json")


@pytest.fixture()
def vlan_config_response() -> dict[str, Any]:
    """Full UniFi API response for /api/s/default/rest/networkconf (4 VLANs)."""
    return load_fixture("vlan_config.json")


@pytest.fixture()
def health_response() -> dict[str, Any]:
    """Full UniFi API response for /api/s/default/stat/health."""
    return load_fixture("health.json")


@pytest.fixture()
def firmware_status_response() -> dict[str, Any]:
    """Full UniFi API response for device firmware status."""
    return load_fixture("firmware_status.json")


# ---------------------------------------------------------------------------
# Extracted data-only fixtures (just the list inside "data")
# ---------------------------------------------------------------------------


@pytest.fixture()
def device_list(device_list_response: dict[str, Any]) -> list[dict[str, Any]]:
    """Just the device list (3 devices: USG, switch, AP)."""
    return device_list_response["data"]


@pytest.fixture()
def client_list(client_list_response: dict[str, Any]) -> list[dict[str, Any]]:
    """Just the client list (6 clients: mix of wired/wireless/guest)."""
    return client_list_response["data"]


@pytest.fixture()
def event_list(event_list_response: dict[str, Any]) -> list[dict[str, Any]]:
    """Just the event list (6 events: mix of severities)."""
    return event_list_response["data"]


@pytest.fixture()
def vlan_list(vlan_config_response: dict[str, Any]) -> list[dict[str, Any]]:
    """Just the VLAN/network list (4 networks: Default, Guest, IoT, Management)."""
    return vlan_config_response["data"]


@pytest.fixture()
def health_list(health_response: dict[str, Any]) -> list[dict[str, Any]]:
    """Just the health subsystem list."""
    return health_response["data"]
