"""Shared pytest fixtures for OPNsense plugin tests."""

from __future__ import annotations

from typing import Any

import pytest

from tests.fixtures import load_fixture

# ---------------------------------------------------------------------------
# Fixture data loaders -- provide parsed JSON from fixture files
# ---------------------------------------------------------------------------


@pytest.fixture()
def interfaces_data() -> dict[str, Any]:
    """Load the interfaces fixture (``/api/interfaces/overview/export``)."""
    return load_fixture("interfaces.json")


@pytest.fixture()
def vlan_interfaces_data() -> dict[str, Any]:
    """Load the VLAN interfaces fixture (``/api/interfaces/vlan/searchItem``)."""
    return load_fixture("vlan_interfaces.json")


@pytest.fixture()
def firewall_rules_data() -> dict[str, Any]:
    """Load the firewall rules fixture (``/api/firewall/filter/searchRule``)."""
    return load_fixture("firewall_rules.json")


@pytest.fixture()
def aliases_data() -> dict[str, Any]:
    """Load the firewall aliases fixture (``/api/firewall/alias/searchItem``)."""
    return load_fixture("aliases.json")


@pytest.fixture()
def routes_data() -> dict[str, Any]:
    """Load the routes fixture (``/api/routes/routes/searchRoute``)."""
    return load_fixture("routes.json")


@pytest.fixture()
def gateways_data() -> dict[str, Any]:
    """Load the gateways fixture (``/api/routes/gateway/status``)."""
    return load_fixture("gateways.json")


@pytest.fixture()
def ipsec_sessions_data() -> dict[str, Any]:
    """Load the IPSec sessions fixture (``/api/ipsec/sessions/search``)."""
    return load_fixture("ipsec_sessions.json")


@pytest.fixture()
def wireguard_peers_data() -> dict[str, Any]:
    """Load the WireGuard peers fixture (``/api/wireguard/client/search``)."""
    return load_fixture("wireguard_peers.json")


@pytest.fixture()
def ids_alerts_data() -> dict[str, Any]:
    """Load the IDS alerts fixture (``/api/ids/service/queryAlerts``)."""
    return load_fixture("ids_alerts.json")


@pytest.fixture()
def dhcp_leases_data() -> dict[str, Any]:
    """Load the DHCP leases fixture (``/api/kea/leases4/search``)."""
    return load_fixture("dhcp_leases.json")


@pytest.fixture()
def nat_rules_data() -> dict[str, Any]:
    """Load the NAT rules fixture (``/api/firewall/source_nat/searchRule``)."""
    return load_fixture("nat_rules.json")


@pytest.fixture()
def lldp_neighbors_data() -> dict[str, Any]:
    """Load the LLDP neighbors fixture (``/api/diagnostics/interface/getLldpNeighbors``)."""
    return load_fixture("lldp_neighbors.json")
