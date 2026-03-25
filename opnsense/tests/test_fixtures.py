"""Tests for the fixture loader and fixture data integrity.

Verifies:
- load_fixture() loads all fixture files correctly
- All fixture files contain valid JSON
- Fixture data has the expected structure for OPNsense API responses
- Conftest shared fixtures are accessible and return correct types
- Missing fixture raises FileNotFoundError
"""

from __future__ import annotations

from typing import Any

import pytest

from tests.fixtures import load_fixture

# ---------------------------------------------------------------------------
# Fixture loader
# ---------------------------------------------------------------------------


class TestLoadFixture:
    """Verify the load_fixture() helper."""

    def test_load_interfaces(self) -> None:
        data = load_fixture("interfaces.json")
        assert "rows" in data
        assert len(data["rows"]) == 4

    def test_load_vlan_interfaces(self) -> None:
        data = load_fixture("vlan_interfaces.json")
        assert "rows" in data
        assert len(data["rows"]) == 7

    def test_load_firewall_rules(self) -> None:
        data = load_fixture("firewall_rules.json")
        assert "rows" in data
        assert len(data["rows"]) == 5

    def test_load_aliases(self) -> None:
        data = load_fixture("aliases.json")
        assert "rows" in data
        assert len(data["rows"]) == 3

    def test_load_routes(self) -> None:
        data = load_fixture("routes.json")
        assert "rows" in data
        assert len(data["rows"]) == 3

    def test_load_gateways(self) -> None:
        data = load_fixture("gateways.json")
        assert "items" in data
        assert len(data["items"]) == 2

    def test_load_ipsec_sessions(self) -> None:
        data = load_fixture("ipsec_sessions.json")
        assert "rows" in data
        assert len(data["rows"]) == 2

    def test_load_wireguard_peers(self) -> None:
        data = load_fixture("wireguard_peers.json")
        assert "rows" in data
        assert len(data["rows"]) == 3

    def test_load_ids_alerts(self) -> None:
        data = load_fixture("ids_alerts.json")
        assert "rows" in data
        assert len(data["rows"]) == 4

    def test_load_dhcp_leases(self) -> None:
        data = load_fixture("dhcp_leases.json")
        assert "rows" in data
        assert len(data["rows"]) == 5

    def test_missing_fixture_raises(self) -> None:
        with pytest.raises(FileNotFoundError):
            load_fixture("nonexistent.json")


# ---------------------------------------------------------------------------
# Interfaces fixture data
# ---------------------------------------------------------------------------


class TestInterfacesFixtureData:
    """Verify interfaces.json has realistic OPNsense API response structure."""

    def test_wan_interface(self) -> None:
        data = load_fixture("interfaces.json")
        wan = data["rows"][0]
        assert wan["name"] == "igb0"
        assert wan["description"] == "WAN"
        assert wan["type"] == "ethernet"
        assert wan["vlan_tag"] is None

    def test_lan_interface(self) -> None:
        data = load_fixture("interfaces.json")
        lan = data["rows"][1]
        assert lan["name"] == "igb1"
        assert lan["description"] == "LAN"
        assert lan["addr4"] == "192.168.1.1"

    def test_vlan_interface(self) -> None:
        data = load_fixture("interfaces.json")
        guest = data["rows"][2]
        assert guest["type"] == "vlan"
        assert guest["vlan_tag"] == 10
        assert guest["description"] == "Guest"

    def test_all_interfaces_have_required_fields(self) -> None:
        data = load_fixture("interfaces.json")
        required_fields = {"name", "description", "addr4", "subnet4", "type", "status"}
        for iface in data["rows"]:
            assert required_fields.issubset(iface.keys()), (
                f"Interface {iface['name']} missing fields: {required_fields - iface.keys()}"
            )


# ---------------------------------------------------------------------------
# VLAN interfaces fixture data
# ---------------------------------------------------------------------------


class TestVLANInterfacesFixtureData:
    """Verify vlan_interfaces.json matches OPNsense 26.x VLAN search response."""

    def test_has_pagination_metadata(self) -> None:
        data = load_fixture("vlan_interfaces.json")
        assert "rowCount" in data
        assert "total" in data
        assert data["rowCount"] == 7

    def test_vlan_has_required_fields(self) -> None:
        data = load_fixture("vlan_interfaces.json")
        required_fields = {"uuid", "tag", "if", "descr", "vlanif"}
        for vlan in data["rows"]:
            assert required_fields.issubset(vlan.keys()), (
                f"VLAN {vlan.get('descr', '?')} missing fields"
            )

    def test_vlan_tags_are_strings_in_26x(self) -> None:
        """OPNsense 26.x returns tag as a string, not an integer."""
        data = load_fixture("vlan_interfaces.json")
        for vlan in data["rows"]:
            assert isinstance(vlan["tag"], str), (
                f"26.x fixture should have string tags, got {type(vlan['tag'])}"
            )
            tag = int(vlan["tag"])
            assert 1 <= tag <= 4094, f"Invalid VLAN tag: {tag}"

    def test_pcp_values(self) -> None:
        data = load_fixture("vlan_interfaces.json")
        # 26.x returns pcp as strings; Work VLAN (tag 50) has pcp=4, Management (tag 99) has pcp=6
        work = next(v for v in data["rows"] if v["descr"] == "Work")
        mgmt = next(v for v in data["rows"] if v["descr"] == "Management")
        assert work["pcp"] == "4"
        assert mgmt["pcp"] == "6"


# ---------------------------------------------------------------------------
# Firewall rules fixture data
# ---------------------------------------------------------------------------


class TestFirewallRulesFixtureData:
    """Verify firewall_rules.json matches OPNsense /api/firewall/filter/searchRule."""

    def test_has_pagination_metadata(self) -> None:
        data = load_fixture("firewall_rules.json")
        assert data["rowCount"] == 5
        assert data["total"] == 5

    def test_rule_has_required_fields(self) -> None:
        data = load_fixture("firewall_rules.json")
        required_fields = {"uuid", "description", "action", "enabled", "direction"}
        for rule in data["rows"]:
            assert required_fields.issubset(rule.keys())

    def test_actions_are_valid(self) -> None:
        valid_actions = {"pass", "block", "reject"}
        data = load_fixture("firewall_rules.json")
        for rule in data["rows"]:
            assert rule["action"] in valid_actions, f"Invalid action: {rule['action']}"

    def test_has_inter_vlan_block_rules(self) -> None:
        """Fixture should include realistic inter-VLAN isolation rules."""
        data = load_fixture("firewall_rules.json")
        block_rules = [r for r in data["rows"] if r["action"] == "block"]
        assert len(block_rules) >= 2


# ---------------------------------------------------------------------------
# Aliases fixture data
# ---------------------------------------------------------------------------


class TestAliasesFixtureData:
    """Verify aliases.json matches OPNsense /api/firewall/alias/searchItem."""

    def test_alias_has_required_fields(self) -> None:
        data = load_fixture("aliases.json")
        required_fields = {"uuid", "name", "type", "description", "content"}
        for alias in data["rows"]:
            assert required_fields.issubset(alias.keys())

    def test_alias_types_are_valid(self) -> None:
        valid_types = {"host", "network", "port", "url"}
        data = load_fixture("aliases.json")
        for alias in data["rows"]:
            assert alias["type"] in valid_types

    def test_rfc1918_alias_content(self) -> None:
        data = load_fixture("aliases.json")
        rfc1918 = next(a for a in data["rows"] if a["name"] == "rfc1918_nets")
        assert "10.0.0.0/8" in rfc1918["content"]
        assert "192.168.0.0/16" in rfc1918["content"]


# ---------------------------------------------------------------------------
# Routes fixture data
# ---------------------------------------------------------------------------


class TestRoutesFixtureData:
    """Verify routes.json matches OPNsense /api/routes/routes/searchRoute."""

    def test_route_has_required_fields(self) -> None:
        data = load_fixture("routes.json")
        required_fields = {"uuid", "network", "gateway", "descr", "disabled"}
        for route in data["rows"]:
            assert required_fields.issubset(route.keys())

    def test_includes_disabled_route(self) -> None:
        data = load_fixture("routes.json")
        disabled = [r for r in data["rows"] if r["disabled"] == "1"]
        assert len(disabled) >= 1


# ---------------------------------------------------------------------------
# Gateways fixture data
# ---------------------------------------------------------------------------


class TestGatewaysFixtureData:
    """Verify gateways.json matches OPNsense 26.x /api/routes/gateway/status.

    OPNsense 26.x returns dpinger metrics as strings with unit suffixes
    (e.g. "4.2 ms", "0.0 %") and uses "~" as a null sentinel. The
    ``interface`` field is not present in 26.x gateway status responses.
    """

    def test_gateway_has_required_fields(self) -> None:
        data = load_fixture("gateways.json")
        # 26.x fields: name, address, status, status_translated, loss, delay, stddev, monitor
        required_fields = {"name", "address", "status", "monitor"}
        for gw in data["items"]:
            assert required_fields.issubset(gw.keys())

    def test_all_gateways_have_valid_status(self) -> None:
        data = load_fixture("gateways.json")
        # dpinger raw statuses: none (online), down, delay, loss, delay+loss, force_down
        valid_statuses = {"none", "down", "delay", "loss", "delay+loss", "force_down",
                          "online", "offline"}
        for gw in data["items"]:
            assert gw["status"] in valid_statuses

    def test_delay_is_string_or_numeric(self) -> None:
        data = load_fixture("gateways.json")
        for gw in data["items"]:
            delay = gw["delay"]
            # 26.x returns strings like "4.2 ms" or "~"; older versions return float
            assert isinstance(delay, (int, float, str))


# ---------------------------------------------------------------------------
# IPSec sessions fixture data
# ---------------------------------------------------------------------------


class TestIPSecSessionsFixtureData:
    """Verify ipsec_sessions.json matches OPNsense /api/ipsec/sessions/search."""

    def test_session_has_required_fields(self) -> None:
        data = load_fixture("ipsec_sessions.json")
        required_fields = {"id", "description", "connected", "local-ts", "remote-ts"}
        for session in data["rows"]:
            assert required_fields.issubset(session.keys())

    def test_includes_connected_and_disconnected(self) -> None:
        data = load_fixture("ipsec_sessions.json")
        statuses = {s["connected"] for s in data["rows"]}
        assert "connected" in statuses
        assert "disconnected" in statuses

    def test_connected_session_has_byte_counters(self) -> None:
        data = load_fixture("ipsec_sessions.json")
        connected = next(s for s in data["rows"] if s["connected"] == "connected")
        assert connected["bytes-in"] > 0
        assert connected["bytes-out"] > 0

    def test_disconnected_session_has_zero_counters(self) -> None:
        data = load_fixture("ipsec_sessions.json")
        disconnected = next(s for s in data["rows"] if s["connected"] == "disconnected")
        assert disconnected["bytes-in"] == 0
        assert disconnected["bytes-out"] == 0


# ---------------------------------------------------------------------------
# WireGuard peers fixture data
# ---------------------------------------------------------------------------


class TestWireGuardPeersFixtureData:
    """Verify wireguard_peers.json matches OPNsense /api/wireguard/client/search."""

    def test_peer_has_required_fields(self) -> None:
        data = load_fixture("wireguard_peers.json")
        required_fields = {"uuid", "name", "pubkey", "tunneladdress"}
        for peer in data["rows"]:
            assert required_fields.issubset(peer.keys())

    def test_includes_active_and_inactive_peers(self) -> None:
        data = load_fixture("wireguard_peers.json")
        with_handshake = [p for p in data["rows"] if p["lasthandshake"] is not None]
        without_handshake = [p for p in data["rows"] if p["lasthandshake"] is None]
        assert len(with_handshake) >= 1
        assert len(without_handshake) >= 1

    def test_inactive_peer_has_no_endpoint(self) -> None:
        data = load_fixture("wireguard_peers.json")
        inactive = next(p for p in data["rows"] if p["lasthandshake"] is None)
        assert inactive["endpoint"] is None


# ---------------------------------------------------------------------------
# IDS alerts fixture data
# ---------------------------------------------------------------------------


class TestIDSAlertsFixtureData:
    """Verify ids_alerts.json matches OPNsense /api/ids/service/queryAlerts."""

    def test_alert_has_required_fields(self) -> None:
        data = load_fixture("ids_alerts.json")
        required_fields = {"timestamp", "alert", "alert_sev", "src_ip", "dest_ip", "action"}
        for alert in data["rows"]:
            assert required_fields.issubset(alert.keys())

    def test_severity_levels_present(self) -> None:
        data = load_fixture("ids_alerts.json")
        severities = {a["alert_sev"] for a in data["rows"]}
        # Should include at least two different severity levels
        assert len(severities) >= 2

    def test_includes_drop_action(self) -> None:
        data = load_fixture("ids_alerts.json")
        actions = {a["action"] for a in data["rows"]}
        assert "drop" in actions
        assert "alert" in actions

    def test_timestamps_are_iso8601(self) -> None:
        data = load_fixture("ids_alerts.json")
        for alert in data["rows"]:
            # Basic check that timestamp looks like ISO 8601
            assert "T" in alert["timestamp"]
            assert "Z" in alert["timestamp"]


# ---------------------------------------------------------------------------
# DHCP leases fixture data
# ---------------------------------------------------------------------------


class TestDHCPLeasesFixtureData:
    """Verify dhcp_leases.json matches OPNsense /api/kea/leases4/search."""

    def test_lease_has_required_fields(self) -> None:
        data = load_fixture("dhcp_leases.json")
        required_fields = {"hw_address", "address", "hostname", "expire", "state"}
        for lease in data["rows"]:
            assert required_fields.issubset(lease.keys())

    def test_includes_active_and_expired_leases(self) -> None:
        data = load_fixture("dhcp_leases.json")
        states = {row["state"] for row in data["rows"]}
        assert "active" in states
        assert "expired" in states

    def test_mac_addresses_are_formatted(self) -> None:
        data = load_fixture("dhcp_leases.json")
        for lease in data["rows"]:
            mac = lease["hw_address"]
            # MAC should have 5 colons (6 octets)
            assert mac.count(":") == 5, f"Invalid MAC format: {mac}"

    def test_leases_span_multiple_interfaces(self) -> None:
        data = load_fixture("dhcp_leases.json")
        interfaces = {row["interface"] for row in data["rows"]}
        assert len(interfaces) >= 2, "Leases should span multiple interfaces"


# ---------------------------------------------------------------------------
# Conftest shared fixtures
# ---------------------------------------------------------------------------


class TestConftestFixtures:
    """Verify conftest shared fixtures are accessible and return correct types."""

    def test_interfaces_fixture(self, interfaces_data: dict[str, Any]) -> None:
        assert isinstance(interfaces_data, dict)
        assert "rows" in interfaces_data

    def test_vlan_interfaces_fixture(self, vlan_interfaces_data: dict[str, Any]) -> None:
        assert isinstance(vlan_interfaces_data, dict)
        assert "rows" in vlan_interfaces_data

    def test_firewall_rules_fixture(self, firewall_rules_data: dict[str, Any]) -> None:
        assert isinstance(firewall_rules_data, dict)
        assert "rows" in firewall_rules_data

    def test_aliases_fixture(self, aliases_data: dict[str, Any]) -> None:
        assert isinstance(aliases_data, dict)
        assert "rows" in aliases_data

    def test_routes_fixture(self, routes_data: dict[str, Any]) -> None:
        assert isinstance(routes_data, dict)
        assert "rows" in routes_data

    def test_gateways_fixture(self, gateways_data: dict[str, Any]) -> None:
        assert isinstance(gateways_data, dict)
        assert "items" in gateways_data

    def test_ipsec_sessions_fixture(self, ipsec_sessions_data: dict[str, Any]) -> None:
        assert isinstance(ipsec_sessions_data, dict)
        assert "rows" in ipsec_sessions_data

    def test_wireguard_peers_fixture(self, wireguard_peers_data: dict[str, Any]) -> None:
        assert isinstance(wireguard_peers_data, dict)
        assert "rows" in wireguard_peers_data

    def test_ids_alerts_fixture(self, ids_alerts_data: dict[str, Any]) -> None:
        assert isinstance(ids_alerts_data, dict)
        assert "rows" in ids_alerts_data

    def test_dhcp_leases_fixture(self, dhcp_leases_data: dict[str, Any]) -> None:
        assert isinstance(dhcp_leases_data, dict)
        assert "rows" in dhcp_leases_data
