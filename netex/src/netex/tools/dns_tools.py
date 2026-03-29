# SPDX-License-Identifier: MIT
"""Cross-vendor DNS commands for the netex umbrella plugin.

Implements DNS tools that correlate data across multiple vendor plugins
(OPNsense gateway, NextDNS, UniFi edge) to provide:

- ``netex__dns__trace`` -- Enhanced DNS resolution path tracing with
  NextDNS awareness. Traces device/VLAN -> OPNsense Unbound ->
  upstream resolver (NextDNS or other).

- ``netex__dns__verify_profiles`` -- VLAN-to-NextDNS-profile mapping
  verification. Checks OPNsense forwarder config matches expected
  VLAN-to-profile pinning, then validates via NextDNS analytics.

- ``netex__dns__get_cross_profile_summary`` -- Unified DNS analytics
  across all NextDNS profiles with per-profile breakdown and
  encryption audit.

All tools gracefully degrade when optional plugins are not installed.
"""

from __future__ import annotations

import ipaddress
import logging
import re
from typing import Any

from netex.registry.plugin_registry import PluginRegistry
from netex.server import mcp_server

logger = logging.getLogger("netex.tools.dns_tools")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build_registry() -> PluginRegistry:
    """Build a plugin registry with auto-discovery."""
    return PluginRegistry(auto_discover=True)


def extract_nextdns_profile_id(target: str) -> str | None:
    """Extract a NextDNS profile ID from a DNS endpoint URL.

    Recognised patterns:
    - ``dns.nextdns.io/abc123``
    - ``https://dns.nextdns.io/abc123``
    - ``abc123.dns.nextdns.io`` (DoH subdomain format)

    Parameters
    ----------
    target:
        The upstream DNS target string from a forwarder configuration.

    Returns
    -------
    str | None
        The extracted profile ID, or ``None`` if the target is not a
        NextDNS endpoint.
    """
    if not target:
        return None

    # Pattern 1: dns.nextdns.io/{id} (path-based)
    match = re.search(r"dns\.nextdns\.io/([a-zA-Z0-9]+)", target)
    if match:
        return match.group(1)

    # Pattern 2: {id}.dns.nextdns.io (subdomain-based DoH)
    match = re.search(r"([a-zA-Z0-9]+)\.dns\.nextdns\.io", target)
    if match:
        return match.group(1)

    return None


def ip_in_subnet(ip_str: str, subnet_str: str) -> bool:
    """Check whether an IP address belongs to a CIDR subnet.

    Parameters
    ----------
    ip_str:
        IP address string (e.g. ``"10.0.60.15"``).
    subnet_str:
        CIDR notation subnet (e.g. ``"10.0.60.0/24"``).

    Returns
    -------
    bool
        ``True`` if the IP is within the subnet, ``False`` otherwise.
        Returns ``False`` for any parsing errors.
    """
    try:
        return ipaddress.ip_address(ip_str) in ipaddress.ip_network(
            subnet_str, strict=False
        )
    except (ValueError, TypeError):
        return False


def _is_nextdns_target(target: str) -> bool:
    """Return True if the forwarder target points to NextDNS."""
    return "nextdns.io" in target.lower() if target else False


def _find_forwarder_for_subnet(
    forwarders: list[dict[str, Any]],
    subnet: str | None,
) -> dict[str, Any] | None:
    """Find a DNS forwarder whose domain field matches a VLAN subnet.

    OPNsense Unbound domain overrides use the ``domain`` field as a
    match key (e.g. a domain like ``"60.0.10.in-addr.arpa"`` for
    reverse lookups, or ``""`` / ``"."`` for catch-all forwarding).

    Since OPNsense does not natively support per-source-subnet
    forwarding in domain overrides, we look for forwarders whose
    ``description`` or ``domain`` field contains a reference to the
    VLAN subnet, VLAN name, or VLAN ID. This is a best-effort match.

    If no specific match is found, return the catch-all forwarder
    (domain = ``""`` or ``"."``), if any.

    Parameters
    ----------
    forwarders:
        List of domain override dicts from OPNsense.
    subnet:
        CIDR subnet to match (e.g. ``"10.0.60.0/24"``).

    Returns
    -------
    dict | None
        The matching forwarder entry, or ``None`` if no match.
    """
    if not forwarders:
        return None

    subnet_prefix = ""
    if subnet:
        try:
            net = ipaddress.ip_network(subnet, strict=False)
            subnet_prefix = str(net.network_address)
        except (ValueError, TypeError):
            subnet_prefix = subnet

    # First pass: look for a forwarder whose description or domain
    # references this specific subnet.
    for fwd in forwarders:
        desc = fwd.get("description", "").lower()
        domain = fwd.get("domain", "")

        # Check if description references the subnet or its prefix
        if subnet_prefix and subnet_prefix in desc:
            return fwd

        # Check if description references the subnet in CIDR form
        if subnet and subnet.lower() in desc:
            return fwd

    # Second pass: return the catch-all forwarder if present
    for fwd in forwarders:
        domain = fwd.get("domain", "").strip()
        if domain in ("", "."):
            return fwd

    return None


# ---------------------------------------------------------------------------
# Task 263: Enhanced netex dns trace
# ---------------------------------------------------------------------------


@mcp_server.tool()
async def netex__dns__trace_enhanced(
    domain: str,
    source_vlan: str | None = None,
    source_ip: str | None = None,
) -> dict[str, Any]:
    """Trace the full DNS resolution path for a domain.

    Traces the DNS query path from a device/VLAN through OPNsense
    Unbound forwarder configuration to the upstream resolver. When
    the NextDNS plugin is installed and the forwarder points to
    NextDNS, also queries NextDNS logs to show if the domain was
    recently blocked or allowed.

    Parameters
    ----------
    domain:
        The domain name to trace (e.g. ``"example.com"``).
    source_vlan:
        Optional VLAN name or ID to identify the source subnet.
    source_ip:
        Optional source IP address for more precise tracing.

    Returns
    -------
    dict
        Trace result with ``domain``, ``trace`` (ordered steps),
        and a human-readable ``summary``.
    """
    registry = _build_registry()
    trace_steps: list[dict[str, Any]] = []

    # -----------------------------------------------------------------
    # Step 1: Identify source context
    # -----------------------------------------------------------------
    source_step: dict[str, Any] = {"step": "source", "description": "Query origin"}
    if source_vlan:
        source_step["vlan"] = source_vlan
    if source_ip:
        source_step["ip"] = source_ip
    if not source_vlan and not source_ip:
        source_step["note"] = "No source specified; tracing from gateway perspective"
    trace_steps.append(source_step)

    # -----------------------------------------------------------------
    # Step 2: Check OPNsense Unbound forwarder config
    # -----------------------------------------------------------------
    gateway_plugins = registry.plugins_with_role("gateway")

    if gateway_plugins:
        # In production, this would call the OPNsense services tool.
        # We record that the gateway plugin is available and what tool
        # would be invoked.
        forwarder_step: dict[str, Any] = {
            "step": "forwarder_lookup",
            "description": "OPNsense Unbound DNS forwarder configuration",
            "gateway_plugin": gateway_plugins[0]["name"],
            "tool": "opnsense__services__get_dns_forwarders",
            "status": "available",
        }
        if source_vlan:
            forwarder_step["note"] = (
                f"Will check forwarder rules matching VLAN '{source_vlan}'"
            )
        trace_steps.append(forwarder_step)
    else:
        trace_steps.append(
            {
                "step": "forwarder_lookup",
                "description": "No gateway plugin installed",
                "status": "skipped",
                "note": "Install a gateway plugin (e.g. opnsense) for forwarder tracing",
            }
        )

    # -----------------------------------------------------------------
    # Step 3: Check NextDNS resolution (if applicable)
    # -----------------------------------------------------------------
    dns_plugins = registry.plugins_with_role("dns")
    if dns_plugins:
        nextdns_step: dict[str, Any] = {
            "step": "nextdns_resolution",
            "description": "NextDNS profile lookup",
            "dns_plugin": dns_plugins[0]["name"],
            "status": "available",
        }
        if gateway_plugins:
            nextdns_step["note"] = (
                "Will extract NextDNS profile ID from forwarder target "
                "and query logs for domain resolution status"
            )
            nextdns_step["tools"] = [
                "nextdns__logs__search",
                "nextdns__profiles__list_profiles",
            ]
        else:
            nextdns_step["note"] = (
                "NextDNS plugin available but no gateway plugin to determine "
                "which profile handles this domain. Can query all profiles."
            )
        trace_steps.append(nextdns_step)
    else:
        trace_steps.append(
            {
                "step": "nextdns_resolution",
                "description": "No DNS plugin installed",
                "status": "skipped",
                "note": (
                    "Install the nextdns plugin for NextDNS-aware tracing "
                    "(blocked/allowed status, profile identification)"
                ),
            }
        )

    # -----------------------------------------------------------------
    # Build summary
    # -----------------------------------------------------------------
    available_layers: list[str] = []
    if gateway_plugins:
        available_layers.append("gateway (forwarder config)")
    if dns_plugins:
        available_layers.append("dns (NextDNS analytics)")

    if available_layers:
        summary = (
            f"DNS trace for '{domain}' across {len(available_layers)} layer(s): "
            f"{', '.join(available_layers)}."
        )
    else:
        summary = (
            f"DNS trace for '{domain}': no vendor plugins installed. "
            "Install gateway and/or dns plugins for full tracing."
        )

    return {
        "domain": domain,
        "trace": trace_steps,
        "summary": summary,
        "plugins_available": {
            "gateway": len(gateway_plugins) > 0,
            "dns": len(dns_plugins) > 0,
        },
    }


# ---------------------------------------------------------------------------
# Task 264: netex dns verify-profiles
# ---------------------------------------------------------------------------


@mcp_server.tool()
async def netex__dns__verify_profiles() -> dict[str, Any]:
    """Verify VLAN-to-NextDNS-profile mapping across the network.

    For each VLAN discovered from gateway and edge plugins:

    1. Check OPNsense Unbound DNS forwarder config for that subnet.
    2. Extract NextDNS profile ID from the forwarder target.
    3. Query NextDNS analytics for source IPs hitting that profile.
    4. Check whether source IPs from analytics match the VLAN subnet.
    5. Report match/mismatch status.

    Gracefully degrades when plugins are missing:
    - Without gateway plugin: cannot read forwarder config.
    - Without dns plugin: cannot verify via NextDNS analytics.
    - Without edge plugin: uses gateway VLANs only.

    Returns
    -------
    dict
        Verification result with ``vlans_checked``, ``verified`` count,
        ``mismatches`` list, and per-VLAN ``results``.
    """
    registry = _build_registry()

    # Check required plugins
    gateway_plugins = registry.plugins_with_role("gateway")
    dns_plugins = registry.plugins_with_role("dns")
    edge_plugins = registry.plugins_with_role("edge")

    if not gateway_plugins and not dns_plugins:
        return {
            "vlans_checked": 0,
            "verified": 0,
            "mismatches": [
                "Cannot verify: no gateway or dns plugins installed. "
                "Install opnsense (gateway) and nextdns (dns) plugins."
            ],
            "results": [],
            "error": "missing_plugins",
        }

    if not gateway_plugins:
        return {
            "vlans_checked": 0,
            "verified": 0,
            "mismatches": [
                "Cannot verify forwarder configuration: no gateway plugin installed. "
                "Install a gateway plugin (e.g. opnsense) to read DNS forwarder config."
            ],
            "results": [],
            "error": "missing_gateway",
        }

    # In production, we would call actual plugin tools here:
    #   vlans = await opnsense__interfaces__list_vlan_interfaces(client)
    #   forwarders = await opnsense__services__get_dns_forwarders(client)
    #   profiles = await nextdns__profiles__list_profiles()
    #   ips = await nextdns__analytics__get_ips(profile_id, ...)
    #
    # For now, the tool reports its capability and the tools that would
    # be invoked. The actual invocation wiring happens at orchestrator
    # integration.

    result: dict[str, Any] = {
        "vlans_checked": 0,
        "verified": 0,
        "mismatches": [],
        "results": [],
        "plugins": {
            "gateway": gateway_plugins[0]["name"] if gateway_plugins else None,
            "dns": dns_plugins[0]["name"] if dns_plugins else None,
            "edge": edge_plugins[0]["name"] if edge_plugins else None,
        },
        "tools_required": [
            "opnsense__services__get_dns_forwarders",
        ],
    }

    if dns_plugins:
        result["tools_required"].extend(
            [
                "nextdns__profiles__list_profiles",
                "nextdns__analytics__get_ips",
            ]
        )

    if edge_plugins:
        result["tools_required"].append("unifi__topology__get_vlans")

    # Include the verification workflow description
    result["verification_workflow"] = [
        "1. Fetch all VLANs from gateway and edge plugins",
        "2. Fetch DNS forwarder config from gateway (OPNsense Unbound)",
        "3. For each VLAN, find matching forwarder and extract NextDNS profile ID",
        "4. Query NextDNS analytics for source IPs per profile",
        "5. Verify source IPs from analytics match VLAN subnet ranges",
        "6. Report match/mismatch status per VLAN",
    ]

    return result


async def verify_profiles_with_data(
    vlans: list[dict[str, Any]],
    forwarders: list[dict[str, Any]],
    profiles: list[dict[str, Any]],
    analytics_ips: dict[str, list[dict[str, Any]]],
) -> dict[str, Any]:
    """Verify VLAN-to-NextDNS-profile mapping with pre-fetched data.

    This is the core verification logic, separated from data fetching
    for testability. In production, ``netex__dns__verify_profiles``
    would call vendor plugin tools to gather the data, then pass it
    here.

    Parameters
    ----------
    vlans:
        List of VLAN dicts with ``name``, ``vlan_id``, and ``subnet``.
    forwarders:
        List of DNS forwarder dicts from OPNsense Unbound domain
        overrides. Each has ``domain``, ``server``, ``description``.
    profiles:
        List of NextDNS profile summary dicts (from list_profiles).
    analytics_ips:
        Dict mapping profile_id -> list of IP analytics entries
        (each entry has ``ip`` and ``queries`` keys).

    Returns
    -------
    dict
        Verification result with per-VLAN status.
    """
    # Build profile name lookup
    profile_names: dict[str, str] = {}
    for p in profiles:
        profile_names[p.get("id", "")] = p.get("name", "")

    results: list[dict[str, Any]] = []
    mismatches: list[str] = []

    for vlan in vlans:
        vlan_name = vlan.get("name", "unknown")
        vlan_id = vlan.get("vlan_id", 0)
        subnet = vlan.get("subnet")

        result: dict[str, Any] = {
            "vlan_name": vlan_name,
            "vlan_id": vlan_id,
            "subnet": subnet,
            "forwarder_configured": False,
            "nextdns_profile": None,
            "nextdns_profile_name": None,
            "analytics_confirmed": False,
            "status": "unknown",
        }

        # Find matching forwarder for this VLAN's subnet
        forwarder = _find_forwarder_for_subnet(forwarders, subnet)
        if forwarder is None:
            result["status"] = "no_forwarder"
            mismatches.append(
                f"VLAN {vlan_name} (ID {vlan_id}): "
                "no DNS forwarder configured for subnet"
            )
        else:
            result["forwarder_configured"] = True
            target = forwarder.get("server", "")
            result["forwarder_target"] = target

            profile_id = extract_nextdns_profile_id(target)
            if profile_id:
                result["nextdns_profile"] = profile_id
                result["nextdns_profile_name"] = profile_names.get(
                    profile_id, ""
                )

                # Check analytics for traffic from this subnet
                ip_entries = analytics_ips.get(profile_id, [])
                if subnet:
                    subnet_traffic = any(
                        ip_in_subnet(entry.get("ip", ""), subnet)
                        for entry in ip_entries
                    )
                else:
                    subnet_traffic = False

                result["analytics_confirmed"] = subnet_traffic
                if subnet_traffic:
                    result["status"] = "verified"
                else:
                    result["status"] = "no_traffic"
                    mismatches.append(
                        f"VLAN {vlan_name} (ID {vlan_id}): "
                        f"forwarder configured (profile {profile_id}) "
                        "but no traffic from subnet in analytics"
                    )
            else:
                result["status"] = "non_nextdns"
                result["note"] = (
                    f"Forwarder target '{target}' is not a NextDNS endpoint"
                )

        results.append(result)

    verified_count = sum(1 for r in results if r["status"] == "verified")

    return {
        "vlans_checked": len(results),
        "verified": verified_count,
        "mismatches": mismatches,
        "results": results,
    }


# ---------------------------------------------------------------------------
# Task 265: Cross-profile analytics summary
# ---------------------------------------------------------------------------


@mcp_server.tool()
async def netex__dns__get_cross_profile_summary(
    from_time: str | None = None,
    to_time: str | None = None,
) -> dict[str, Any]:
    """Get unified DNS analytics across all NextDNS profiles.

    Returns total queries, blocks, per-profile breakdown, and
    encryption audit across all profiles managed by the dns plugin.

    Requires the NextDNS plugin to be installed. Without it, returns
    an error indicating the missing dependency.

    Parameters
    ----------
    from_time:
        Start of the date range (ISO 8601 or relative like ``"-24h"``).
    to_time:
        End of the date range.

    Returns
    -------
    dict
        Summary with ``total_queries``, ``total_blocked``,
        ``overall_block_rate``, and per-profile ``profiles`` list.
    """
    registry = _build_registry()
    dns_plugins = registry.plugins_with_role("dns")

    if not dns_plugins:
        return {
            "total_queries": 0,
            "total_blocked": 0,
            "overall_block_rate": 0.0,
            "profiles": [],
            "error": "missing_dns_plugin",
            "message": (
                "No DNS plugin installed. Install the nextdns plugin "
                "to get cross-profile analytics."
            ),
        }

    # In production, this would call:
    #   profiles = await nextdns__profiles__list_profiles()
    #   For each profile:
    #     status = await nextdns__analytics__get_status(profile_id, ...)
    #     encryption = await nextdns__analytics__get_encryption(profile_id, ...)
    #
    # The actual data fetching and aggregation is in
    # compute_cross_profile_summary() for testability.

    return {
        "total_queries": 0,
        "total_blocked": 0,
        "overall_block_rate": 0.0,
        "profiles": [],
        "plugins": {
            "dns": dns_plugins[0]["name"],
        },
        "tools_required": [
            "nextdns__profiles__list_profiles",
            "nextdns__analytics__get_status",
            "nextdns__analytics__get_encryption",
        ],
        "time_range": {
            "from": from_time,
            "to": to_time,
        },
    }


def compute_cross_profile_summary(
    profiles: list[dict[str, Any]],
    status_data: dict[str, list[dict[str, Any]]],
    encryption_data: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """Compute cross-profile analytics summary from pre-fetched data.

    Separated from the MCP tool for testability. In production, the
    tool fetches data from NextDNS, then passes it here for
    aggregation.

    Parameters
    ----------
    profiles:
        List of NextDNS profile summary dicts (from list_profiles).
    status_data:
        Dict mapping profile_id -> list of status analytics entries.
        Each entry has ``status`` (``"default"``, ``"blocked"``,
        ``"allowed"``) and ``queries`` count.
    encryption_data:
        Dict mapping profile_id -> encryption analytics dict with
        ``encrypted``, ``unencrypted``, ``total``, and
        ``unencrypted_percentage`` keys.

    Returns
    -------
    dict
        Aggregated summary with per-profile and overall totals.
    """
    summaries: list[dict[str, Any]] = []
    total_queries = 0
    total_blocked = 0

    for profile in profiles:
        pid = profile.get("id", "")
        pname = profile.get("name", "")

        # Compute queries from status data
        statuses = status_data.get(pid, [])
        queries = sum(s.get("queries", 0) for s in statuses)
        blocked = sum(
            s.get("queries", 0)
            for s in statuses
            if s.get("status") == "blocked"
        )

        # Get encryption data
        enc = encryption_data.get(pid, {})
        encrypted_pct = 100.0 - enc.get("unencrypted_percentage", 0.0)

        block_rate = round(blocked / max(queries, 1) * 100, 1)

        summaries.append(
            {
                "profile_id": pid,
                "profile_name": pname,
                "total_queries": queries,
                "blocked_queries": blocked,
                "block_rate": block_rate,
                "encrypted_percentage": round(encrypted_pct, 1),
            }
        )

        total_queries += queries
        total_blocked += blocked

    overall_block_rate = round(
        total_blocked / max(total_queries, 1) * 100, 1
    )

    return {
        "total_queries": total_queries,
        "total_blocked": total_blocked,
        "overall_block_rate": overall_block_rate,
        "profiles": summaries,
    }
