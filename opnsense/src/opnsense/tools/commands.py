# SPDX-License-Identifier: MIT
"""Command-level MCP tools -- thin wrappers that delegate to agent orchestrators.

These tools represent the user-facing ``opnsense_scan``, ``opnsense_health``,
``opnsense_diagnose``, ``opnsense_firewall``, ``opnsense_firewall_policy_from_matrix``,
``opnsense_vlan``, ``opnsense_vlan_create``, ``opnsense_alias_create``,
``opnsense_rule_create``, ``opnsense_dhcp_configure``, ``opnsense_dns_configure``,
``opnsense_dhcp_reserve_batch``, ``opnsense_vpn``,
``opnsense_dns``, ``opnsense_secure``, and ``opnsense_firmware`` commands.

Each command is a minimal shim that forwards to the corresponding agent function
or composes multiple tool calls, keeping the tool surface lean and the business
logic testable independently.

Write-gated commands use the safety.py decorators and follow the OPNsense
two-step pattern: save config then reconfigure.

Tasks 101-109 (Milestone 3.4).
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from opnsense.errors import ValidationError
from opnsense.output import (
    Finding,
    Severity,
    format_change_plan,
    format_key_value,
    format_severity_report,
    format_summary,
    format_table,
)
from opnsense.safety import check_write_enabled, describe_write_status
from opnsense.server import mcp_server

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Client factory (shared helper)
# ---------------------------------------------------------------------------


def _get_client():
    """Get a configured OPNsenseClient from environment variables."""
    import os

    from opnsense.api.opnsense_client import OPNsenseClient

    host = os.environ.get("OPNSENSE_HOST", "")
    api_key = os.environ.get("OPNSENSE_API_KEY", "")
    api_secret = os.environ.get("OPNSENSE_API_SECRET", "")
    verify_ssl = os.environ.get("OPNSENSE_VERIFY_SSL", "true").lower() != "false"
    return OPNsenseClient(
        host=host,
        api_key=api_key,
        api_secret=api_secret,
        verify_ssl=verify_ssl,
    )


# ===========================================================================
# Task 101: opnsense_scan -- full inventory
# ===========================================================================


@mcp_server.tool()
async def opnsense_scan() -> str:
    """Full OPNsense inventory.

    Covers interfaces, VLANs, firewall rules, routes, gateways,
    VPNs, DNS, DHCP. Collects and formats a comprehensive snapshot of the entire OPNsense
    configuration and operational state. Useful for initial discovery and
    documentation.

    Returns a formatted markdown report with all subsystems.
    """
    from opnsense.agents.firewall import run_firewall_audit
    from opnsense.agents.interfaces import run_interface_report
    from opnsense.agents.routing import run_routing_report

    sections: list[str] = []

    # Interfaces, VLANs, DHCP leases
    try:
        iface_report = await run_interface_report()
        sections.append(iface_report)
    except Exception as exc:
        logger.warning("Interface scan failed: %s", exc)
        sections.append("### Interfaces\n\nFailed to retrieve interface data.\n")

    # Firewall rules, aliases, NAT
    try:
        fw_report = await run_firewall_audit()
        sections.append(fw_report)
    except Exception as exc:
        logger.warning("Firewall scan failed: %s", exc)
        sections.append("### Firewall\n\nFailed to retrieve firewall data.\n")

    # Routes, gateways
    try:
        routing_report = await run_routing_report()
        sections.append(routing_report)
    except Exception as exc:
        logger.warning("Routing scan failed: %s", exc)
        sections.append("### Routing\n\nFailed to retrieve routing data.\n")

    # VPN, security, services, firmware (require client)
    client = _get_client()
    try:
        from opnsense.agents.vpn import vpn_status_report

        try:
            vpn_report = await vpn_status_report(client)
            sections.append(vpn_report)
        except Exception as exc:
            logger.warning("VPN scan failed: %s", exc)
            sections.append("### VPN\n\nFailed to retrieve VPN data.\n")

        from opnsense.agents.security import security_audit_report

        try:
            sec_report = await security_audit_report(client)
            sections.append(sec_report)
        except Exception as exc:
            logger.warning("Security scan failed: %s", exc)
            sections.append("### Security\n\nFailed to retrieve security data.\n")

        from opnsense.agents.services import services_report

        try:
            svc_report = await services_report(client)
            sections.append(svc_report)
        except Exception as exc:
            logger.warning("Services scan failed: %s", exc)
            sections.append("### Services\n\nFailed to retrieve services data.\n")

        from opnsense.agents.firmware import firmware_report

        try:
            fw_status = await firmware_report(client)
            sections.append(fw_status)
        except Exception as exc:
            logger.warning("Firmware scan failed: %s", exc)
            sections.append("### Firmware\n\nFailed to retrieve firmware data.\n")
    finally:
        await client.close()

    full_report = "\n\n---\n\n".join(sections)

    logger.info(
        "Full OPNsense scan completed (%d sections)",
        len(sections),
        extra={"component": "commands"},
    )

    return f"# OPNsense Full Inventory Scan\n\n{full_report}"


# ===========================================================================
# Task 102: opnsense_health -- gateway health + IDS + firmware + WAN
# ===========================================================================


@mcp_server.tool()
async def opnsense_health() -> str:
    """Comprehensive health check -- gateway status, IDS alerts, firmware updates, WAN reachability.

    Runs parallel health probes across all critical subsystems and returns
    a severity-tiered findings report. Gateway health is checked via RTT
    and status, IDS alerts are scanned for recent high-severity events,
    firmware update availability is checked, and WAN reachability is
    verified with ping tests.

    Returns a markdown-formatted health report with findings grouped
    by severity (Critical > High > Warning > Informational).
    """
    findings: list[Finding] = []
    sections: list[str] = []

    # --- Gateway health ---
    try:
        from opnsense.tools.routing import opnsense__routing__list_gateways

        gateways = await opnsense__routing__list_gateways()
        offline = [g for g in gateways if g.get("status", "").lower() in ("offline", "down")]

        for gw in offline:
            findings.append(
                Finding(
                    severity=Severity.CRITICAL,
                    title=f"Gateway offline: {gw.get('name', '')}",
                    detail=(
                        f"Gateway {gw.get('name', '')} at {gw.get('gateway', '')} "
                        f"on {gw.get('interface', '')} is down."
                    ),
                    recommendation="Check physical connectivity and upstream provider.",
                )
            )

        for gw in gateways:
            rtt = gw.get("rtt_ms")
            if rtt is not None and rtt >= 200.0:
                findings.append(
                    Finding(
                        severity=Severity.HIGH,
                        title=f"High latency on gateway {gw.get('name', '')}",
                        detail=f"RTT: {rtt:.1f} ms (threshold: 200 ms).",
                        recommendation="Investigate upstream link quality.",
                    )
                )
            elif rtt is not None and rtt >= 50.0:
                findings.append(
                    Finding(
                        severity=Severity.WARNING,
                        title=f"Elevated latency on gateway {gw.get('name', '')}",
                        detail=f"RTT: {rtt:.1f} ms (warning threshold: 50 ms).",
                    )
                )

        gw_rows = [
            [
                g.get("name", ""),
                g.get("gateway", ""),
                g.get("interface", ""),
                g.get("status", ""),
                f"{g.get('rtt_ms', 0):.1f}" if g.get("rtt_ms") is not None else "n/a",
            ]
            for g in gateways
        ]
        if gw_rows:
            sections.append(
                format_table(
                    ["Name", "Address", "Interface", "Status", "RTT (ms)"],
                    gw_rows,
                    title="Gateway Health",
                )
            )

        if not gateways:
            findings.append(
                Finding(
                    severity=Severity.HIGH,
                    title="No gateways found",
                    detail="Could not retrieve gateway status data.",
                )
            )
    except Exception as exc:
        logger.warning("Gateway health check failed: %s", exc)
        findings.append(
            Finding(
                severity=Severity.HIGH,
                title="Gateway health check failed",
                detail=f"Error: {exc}",
            )
        )

    # --- IDS alerts ---
    client = _get_client()
    try:
        from opnsense.tools.security import opnsense__security__get_ids_alerts

        try:
            alerts = await opnsense__security__get_ids_alerts(client, hours=24)
            high_alerts = [a for a in alerts if a.get("severity") == 1]
            medium_alerts = [a for a in alerts if a.get("severity") == 2]

            if high_alerts:
                findings.append(
                    Finding(
                        severity=Severity.HIGH,
                        title=f"{len(high_alerts)} high-severity IDS alert(s) in last 24h",
                        detail="Active attack attempts or known-malicious traffic detected.",
                        recommendation=(
                            "Review source IPs and consider blocking persistent offenders."
                        ),
                    )
                )
            if medium_alerts:
                findings.append(
                    Finding(
                        severity=Severity.WARNING,
                        title=f"{len(medium_alerts)} medium-severity IDS alert(s) in last 24h",
                        detail="Potential reconnaissance or suspicious activity detected.",
                    )
                )
            if not alerts:
                findings.append(
                    Finding(
                        severity=Severity.INFORMATIONAL,
                        title="No IDS alerts in last 24h",
                        detail="No Suricata alerts recorded.",
                    )
                )
        except Exception as exc:
            logger.warning("IDS alert check failed: %s", exc)
            findings.append(
                Finding(
                    severity=Severity.WARNING,
                    title="IDS alert check failed",
                    detail=f"Error: {exc}",
                )
            )

        # --- Firmware status ---
        from opnsense.tools.firmware import opnsense__firmware__get_status

        try:
            fw_status = await opnsense__firmware__get_status(client)
            if fw_status.get("upgrade_available"):
                findings.append(
                    Finding(
                        severity=Severity.WARNING,
                        title=f"Firmware update available: {fw_status.get('latest_version', '?')}",
                        detail=f"Current: {fw_status.get('current_version', '?')}",
                        recommendation="Schedule a maintenance window for the upgrade.",
                    )
                )
            else:
                findings.append(
                    Finding(
                        severity=Severity.INFORMATIONAL,
                        title=f"Firmware up to date ({fw_status.get('current_version', '?')})",
                        detail="No updates available.",
                    )
                )
        except Exception as exc:
            logger.warning("Firmware check failed: %s", exc)
            findings.append(
                Finding(
                    severity=Severity.WARNING,
                    title="Firmware check failed",
                    detail=f"Error: {exc}",
                )
            )

        # --- WAN reachability ---
        from opnsense.tools.diagnostics import opnsense__diagnostics__run_ping

        for target in ("8.8.8.8", "1.1.1.1"):
            try:
                ping = await opnsense__diagnostics__run_ping(client, target, count=3)
                loss = ping.get("loss", "")
                if isinstance(loss, str) and "100" in loss:
                    findings.append(
                        Finding(
                            severity=Severity.CRITICAL,
                            title=f"WAN unreachable: {target}",
                            detail="100% packet loss.",
                            recommendation="Check WAN interface and upstream connectivity.",
                        )
                    )
                elif loss and str(loss) != "0":
                    findings.append(
                        Finding(
                            severity=Severity.WARNING,
                            title=f"Packet loss to {target}",
                            detail=f"Loss: {loss}",
                        )
                    )
                else:
                    findings.append(
                        Finding(
                            severity=Severity.INFORMATIONAL,
                            title=f"WAN reachable: {target}",
                            detail="Ping successful, no packet loss.",
                        )
                    )
            except Exception as exc:
                logger.warning("WAN reachability check to %s failed: %s", target, exc)
                findings.append(
                    Finding(
                        severity=Severity.HIGH,
                        title=f"WAN reachability check failed: {target}",
                        detail=f"Error: {exc}",
                    )
                )
    finally:
        await client.close()

    # Build report
    report = format_severity_report("OPNsense Health Check", findings)
    for section in sections:
        report += "\n" + section

    logger.info(
        "Health check completed: %d findings",
        len(findings),
        extra={"component": "commands"},
    )

    return report


# ===========================================================================
# Task 103: opnsense_diagnose -- host/interface diagnosis with ambiguity
# ===========================================================================


@mcp_server.tool()
async def opnsense_diagnose(target: str) -> str:
    """Diagnose a host or interface on the OPNsense firewall.

    Searches for the target by IP, hostname, MAC address, or interface name.
    If ambiguous (matches both a DHCP host and an interface name), returns
    all matches with a prompt to clarify.

    For hosts: shows DHCP lease, ping result, DNS lookup, and any matching
    firewall rules.

    For interfaces: shows interface config, VLAN details, gateway status,
    and DHCP lease count on that interface.

    Args:
        target: IP address, hostname, MAC address, or interface name.
    """
    from opnsense.tools.interfaces import (
        opnsense__interfaces__get_dhcp_leases,
        opnsense__interfaces__list_interfaces,
        opnsense__interfaces__list_vlan_interfaces,
    )

    target_stripped = target.strip()
    if not target_stripped:
        raise ValidationError(
            "Target must not be empty.",
            details={"field": "target"},
        )

    # Gather interface and DHCP data
    interfaces = await opnsense__interfaces__list_interfaces()
    leases = await opnsense__interfaces__get_dhcp_leases()

    # Search for matches
    matched_interfaces: list[dict[str, Any]] = []
    matched_hosts: list[dict[str, Any]] = []
    target_lower = target_stripped.lower()

    # Match interfaces by name or description
    for iface in interfaces:
        if (
            iface.get("name", "").lower() == target_lower
            or iface.get("description", "").lower() == target_lower
            or iface.get("ip", "").lower() == target_lower
        ):
            matched_interfaces.append(iface)

    # Match hosts by IP, MAC, or hostname in DHCP leases
    for lease in leases:
        if (
            lease.get("ip", "").lower() == target_lower
            or lease.get("mac", "").lower() == target_lower
            or (lease.get("hostname") or "").lower() == target_lower
        ):
            matched_hosts.append(lease)

    # Handle ambiguity
    if matched_interfaces and matched_hosts:
        sections: list[str] = [
            "## Ambiguous Target\n",
            f"The target `{target_stripped}` matches both interfaces and hosts.\n",
        ]

        iface_names = [
            f"- Interface: **{i.get('name', '')}** ({i.get('description', '')})"
            for i in matched_interfaces
        ]
        host_names = [
            f"- Host: **{h.get('hostname', h.get('ip', ''))}** "
            f"({h.get('ip', '')}, {h.get('mac', '')})"
            for h in matched_hosts
        ]

        sections.append("### Matching Interfaces")
        sections.extend(iface_names)
        sections.append("")
        sections.append("### Matching Hosts")
        sections.extend(host_names)
        sections.append("")
        sections.append(
            "Please clarify which one you mean by providing a more specific identifier."
        )

        return "\n".join(sections)

    # No matches
    if not matched_interfaces and not matched_hosts:
        return (
            f"## Target Not Found\n\n"
            f"No interface or host matching `{target_stripped}` was found.\n\n"
            f"Try using an exact IP address, MAC address, hostname, or interface name "
            f"(e.g., `igb0`, `192.168.1.100`, `aa:bb:cc:dd:ee:ff`)."
        )

    # --- Interface diagnosis ---
    if matched_interfaces:
        iface = matched_interfaces[0]
        sections = []

        kv = {
            "Name": iface.get("name", ""),
            "Description": iface.get("description", ""),
            "IP": iface.get("ip", "") or "(none)",
            "Subnet": iface.get("subnet", "") or "(none)",
            "Type": iface.get("if_type", ""),
            "Enabled": "Yes" if iface.get("enabled", True) else "No",
        }
        if iface.get("vlan_id"):
            kv["VLAN ID"] = str(iface["vlan_id"])

        sections.append(format_key_value(kv, title=f"Interface: {iface.get('name', '')}"))

        # DHCP leases on this interface
        iface_leases = [le for le in leases if le.get("interface") == iface.get("name")]
        if iface_leases:
            lease_rows = [
                [
                    le.get("hostname", "") or "(unknown)",
                    le.get("ip", ""),
                    le.get("mac", ""),
                    le.get("state", ""),
                ]
                for le in iface_leases[:10]
            ]
            sections.append(
                format_table(
                    ["Hostname", "IP", "MAC", "State"],
                    lease_rows,
                    title=f"DHCP Leases on {iface.get('name', '')} ({len(iface_leases)} total)",
                )
            )

        # VLANs on same parent
        try:
            vlans = await opnsense__interfaces__list_vlan_interfaces()
            related = [v for v in vlans if v.get("parent_if") == iface.get("name")]
            if related:
                vlan_rows = [
                    [str(v.get("tag", "")), v.get("if_", ""), v.get("description", "")]
                    for v in related
                ]
                sections.append(
                    format_table(
                        ["Tag", "Interface", "Description"],
                        vlan_rows,
                        title="VLANs on this interface",
                    )
                )
        except Exception:
            pass

        return "\n".join(sections)

    # --- Host diagnosis ---
    host = matched_hosts[0]
    sections = []

    kv = {
        "Hostname": host.get("hostname", "") or "(unknown)",
        "IP": host.get("ip", ""),
        "MAC": host.get("mac", ""),
        "State": host.get("state", ""),
        "Interface": host.get("interface", ""),
    }
    if host.get("expiry"):
        kv["Lease Expires"] = host["expiry"]

    sections.append(format_key_value(kv, title=f"Host: {host.get('hostname', host.get('ip', ''))}"))

    # Ping the host
    client = _get_client()
    try:
        from opnsense.tools.diagnostics import opnsense__diagnostics__run_ping

        try:
            ping_result = await opnsense__diagnostics__run_ping(client, host["ip"], count=3)
            ping_kv: dict[str, str] = {"Target": host["ip"]}
            for key in ("avg", "min", "max", "loss"):
                if key in ping_result:
                    ping_kv[key.title()] = str(ping_result[key])
            sections.append(format_key_value(ping_kv, title="Ping Result"))
        except Exception as exc:
            sections.append(f"### Ping\n\nPing failed: {exc}\n")

        # DNS lookup
        from opnsense.tools.diagnostics import opnsense__diagnostics__dns_lookup

        hostname = host.get("hostname")
        if hostname:
            try:
                dns_result = await opnsense__diagnostics__dns_lookup(client, hostname)
                sections.append(
                    format_key_value(
                        {k: str(v) for k, v in dns_result.items()},
                        title="DNS Lookup",
                    )
                )
            except Exception:
                pass
    finally:
        await client.close()

    return "\n".join(sections)


# ===========================================================================
# Task 104: opnsense_firewall -- list rules + shadow analysis with --audit
# ===========================================================================


@mcp_server.tool()
async def opnsense_firewall(audit: bool = False) -> str:
    """List firewall rules, aliases, and NAT rules. With audit=True, run shadow analysis.

    Without ``audit``: returns a formatted table of all firewall rules.

    With ``audit=True``: runs the full firewall audit agent which checks
    for overly permissive rules, disabled rules, rules without logging,
    shadow rules, and interfaces without deny policies.

    Args:
        audit: If True, run the full audit with security findings.
    """
    if audit:
        from opnsense.agents.firewall import run_firewall_audit

        return await run_firewall_audit()

    # Simple rule listing
    from opnsense.tools.firewall import opnsense__firewall__list_rules

    rules = await opnsense__firewall__list_rules()

    if not rules:
        return "## Firewall Rules\n\nNo firewall rules found."

    headers = ["Pos", "Action", "Interface", "Source", "Destination", "Proto", "Log", "Enabled"]
    rows = [
        [
            str(r.get("position", "")),
            r.get("action", ""),
            r.get("interface", ""),
            r.get("source", ""),
            r.get("destination", ""),
            r.get("protocol", ""),
            "yes" if r.get("log") else "no",
            "yes" if r.get("enabled") else "no",
        ]
        for r in rules
    ]

    table = format_table(headers, rows, title="Firewall Rules")
    summary = format_summary(
        "Firewall Summary",
        {
            "Total rules": len(rules),
            "Active": sum(1 for r in rules if r.get("enabled")),
            "Disabled": sum(1 for r in rules if not r.get("enabled")),
        },
        detail="Use `opnsense_firewall(audit=True)` for a full security audit.",
    )

    return f"{summary}\n{table}"


# ===========================================================================
# Task 105: opnsense_firewall_policy_from_matrix -- derive ruleset from
# access matrix
# ===========================================================================

# MAC regex for basic validation
_MAC_PATTERN = re.compile(r"^([0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2}$")


def _parse_access_matrix(matrix_json: str) -> list[dict[str, str]]:
    """Parse and validate the access matrix JSON string.

    Expected format: list of objects with src, dst, and action fields.
    Example: [{"src": "LAN", "dst": "WAN", "action": "pass"}]

    Returns the parsed list of rule dicts.
    Raises ValidationError if parsing or validation fails.
    """
    try:
        matrix = json.loads(matrix_json)
    except json.JSONDecodeError as exc:
        raise ValidationError(
            f"Invalid JSON in access matrix: {exc}",
            details={"field": "matrix"},
        ) from exc

    if not isinstance(matrix, list):
        raise ValidationError(
            "Access matrix must be a JSON array of rule objects.",
            details={"field": "matrix"},
        )

    valid_actions = {"pass", "block", "reject"}
    validated: list[dict[str, str]] = []

    for i, entry in enumerate(matrix):
        if not isinstance(entry, dict):
            raise ValidationError(
                f"Matrix entry {i} must be an object, got {type(entry).__name__}.",
                details={"field": "matrix", "index": i},
            )

        src = entry.get("src", "").strip()
        dst = entry.get("dst", "").strip()
        action = entry.get("action", "").strip().lower()

        if not src:
            raise ValidationError(
                f"Matrix entry {i} is missing 'src'.",
                details={"field": "matrix", "index": i},
            )
        if not dst:
            raise ValidationError(
                f"Matrix entry {i} is missing 'dst'.",
                details={"field": "matrix", "index": i},
            )
        if action not in valid_actions:
            raise ValidationError(
                f"Matrix entry {i} has invalid action '{action}'. Must be one of {valid_actions}.",
                details={"field": "matrix", "index": i, "value": action},
            )

        validated.append(
            {
                "src": src,
                "dst": dst,
                "action": action,
                "protocol": entry.get("protocol", "any").strip(),
                "description": entry.get("description", f"Matrix rule {i}").strip(),
            }
        )

    if not validated:
        raise ValidationError(
            "Access matrix must not be empty.",
            details={"field": "matrix"},
        )

    return validated


def _detect_shadows(
    matrix_rules: list[dict[str, str]],
    existing_rules: list[dict[str, Any]],
) -> list[Finding]:
    """Detect shadow conflicts between matrix rules and existing rules.

    A shadow occurs when an existing rule with the same source/destination
    pair has a conflicting action (e.g., matrix says pass but existing
    says block).
    """
    findings: list[Finding] = []

    for m_rule in matrix_rules:
        for e_rule in existing_rules:
            if not e_rule.get("enabled", True):
                continue

            e_src = e_rule.get("source", "").lower()
            e_dst = e_rule.get("destination", "").lower()
            e_action = e_rule.get("action", "").lower()
            m_src = m_rule["src"].lower()
            m_dst = m_rule["dst"].lower()

            # Check for matching source/destination with conflicting action
            if (
                (e_src == m_src or e_src == "any" or m_src == "any")
                and (e_dst == m_dst or e_dst == "any" or m_dst == "any")
                and e_action != m_rule["action"]
            ):
                findings.append(
                    Finding(
                        severity=Severity.WARNING,
                        title=f"Shadow conflict: {m_rule['src']} -> {m_rule['dst']}",
                        detail=(
                            f"Matrix rule ({m_rule['action']}) conflicts with existing "
                            f"rule '{e_rule.get('description', e_rule.get('uuid', ''))}' "
                            f"({e_action}). The existing rule may shadow the matrix intent."
                        ),
                        recommendation="Review rule ordering and resolve the conflict.",
                    )
                )

    return findings


@mcp_server.tool()
async def opnsense_firewall_policy_from_matrix(
    matrix: str,
    audit: bool = False,
    apply: bool = False,
) -> str:
    """Derive a firewall ruleset from an access matrix.

    Accepts an access matrix as a JSON string describing intended traffic
    flows, and either audits existing rules against it or creates the
    corresponding aliases and firewall rules.

    Matrix format (JSON array)::

        [{"src": "LAN", "dst": "WAN", "action": "pass",
          "protocol": "TCP", "description": "Allow LAN out"}]

    With ``audit=True``: compares the matrix against existing rules and
    reports shadow conflicts.

    With ``apply=True``: creates aliases and firewall rules implementing
    the matrix. Requires OPNSENSE_WRITE_ENABLED=true.

    Args:
        matrix: JSON string of access matrix rules. Each rule has src, dst,
            action (pass/block/reject), and optional protocol and description.
        audit: Compare matrix against existing rules for shadow analysis.
        apply: Create rules implementing the matrix (write-gated).
    """
    # Parse and validate
    rules = _parse_access_matrix(matrix)

    sections: list[str] = []

    # Build a display table of the matrix
    matrix_headers = ["Source", "Destination", "Action", "Protocol", "Description"]
    matrix_rows = [
        [r["src"], r["dst"], r["action"], r.get("protocol", "any"), r.get("description", "")]
        for r in rules
    ]
    sections.append(format_table(matrix_headers, matrix_rows, title="Access Matrix"))

    # --- Audit mode: compare against existing rules ---
    if audit:
        from opnsense.tools.firewall import opnsense__firewall__list_rules

        existing = await opnsense__firewall__list_rules()
        shadows = _detect_shadows(rules, existing)

        if shadows:
            sections.append(format_severity_report("Shadow Analysis", shadows))
        else:
            sections.append(
                "### Shadow Analysis\n\n"
                "No shadow conflicts detected between the matrix and existing rules.\n"
            )

        sections.append(
            format_summary(
                "Audit Summary",
                {
                    "Matrix rules": len(rules),
                    "Existing rules": len(existing),
                    "Shadows detected": len(shadows),
                },
            )
        )

        return "\n".join(sections)

    # --- Apply mode: create rules ---
    if apply:
        if not check_write_enabled("OPNSENSE"):
            return (
                "\n".join(sections)
                + f"\n\n---\n*Write operations are disabled.* {describe_write_status()}"
            )

        from opnsense.tools.firewall import opnsense__firewall__add_rule

        results: list[dict[str, Any]] = []
        errors: list[str] = []

        for rule in rules:
            try:
                result = await opnsense__firewall__add_rule(
                    interface="lan",  # Default; matrix rules map to LAN
                    action=rule["action"],
                    src=rule["src"],
                    dst=rule["dst"],
                    protocol=rule.get("protocol", "any"),
                    description=rule.get("description", ""),
                    apply=True,
                )
                results.append(result)
            except Exception as exc:
                errors.append(f"Failed to create rule {rule['src']} -> {rule['dst']}: {exc}")

        if results:
            sections.append(
                format_summary(
                    "Rules Created",
                    {
                        "Created": len(results),
                        "Failed": len(errors),
                    },
                )
            )

        if errors:
            sections.append("### Errors\n\n" + "\n".join(f"- {e}" for e in errors) + "\n")

        return "\n".join(sections)

    # --- Plan-only mode ---
    steps = [
        {
            "description": (
                f"{r['action'].upper()} {r['src']} -> {r['dst']} ({r.get('protocol', 'any')})"
            ),
        }
        for r in rules
    ]
    sections.append(format_change_plan(steps))
    sections.append(f"\n---\n*Plan-only mode.* {describe_write_status()}")

    return "\n".join(sections)


# ===========================================================================
# Task 106: opnsense_vlan -- list / configure / audit VLANs
# ===========================================================================


@mcp_server.tool()
async def opnsense_vlan(
    configure: bool = False,
    audit: bool = False,
) -> str:
    """List, configure, or audit VLANs on the OPNsense firewall.

    Without flags: lists all VLAN interfaces with their configuration.

    With ``audit=True``: checks for VLANs without IPs, orphaned VLANs,
    and VLANs without firewall rules.

    With ``configure=True``: shows VLAN configuration guidance (actual
    VLAN creation uses opnsense__interfaces__configure_vlan directly).

    Args:
        configure: Show VLAN configuration guidance.
        audit: Run VLAN health audit with findings.
    """
    from opnsense.tools.interfaces import (
        opnsense__interfaces__list_interfaces,
        opnsense__interfaces__list_vlan_interfaces,
    )

    vlans = await opnsense__interfaces__list_vlan_interfaces()
    interfaces = await opnsense__interfaces__list_interfaces()

    if not vlans:
        return "## VLANs\n\nNo VLAN interfaces configured."

    sections: list[str] = []

    # VLAN table
    vlan_headers = ["Tag", "Interface", "Parent", "Description"]
    vlan_rows = [
        [str(v.get("tag", "")), v.get("if_", ""), v.get("parent_if", ""), v.get("description", "")]
        for v in vlans
    ]
    sections.append(format_table(vlan_headers, vlan_rows, title="VLAN Interfaces"))

    if audit:
        findings: list[Finding] = []

        # Check VLANs without IPs
        vlan_if_names = {v.get("if_", "") for v in vlans}
        iface_with_ip = {i.get("name", "") for i in interfaces if i.get("ip")}
        orphans = vlan_if_names - iface_with_ip

        for orphan in orphans:
            if orphan:
                findings.append(
                    Finding(
                        severity=Severity.WARNING,
                        title=f"VLAN interface '{orphan}' has no IP address",
                        detail=f"VLAN {orphan} is defined but has no IP assigned.",
                        recommendation="Assign an IP to make this VLAN functional.",
                    )
                )

        # Check for VLANs without firewall rules
        try:
            from opnsense.tools.firewall import opnsense__firewall__list_rules

            rules = await opnsense__firewall__list_rules()
            interfaces_with_rules = {r.get("interface", "") for r in rules}

            for vlan in vlans:
                vlan_if = vlan.get("if_", "")
                if vlan_if and vlan_if not in interfaces_with_rules:
                    findings.append(
                        Finding(
                            severity=Severity.WARNING,
                            title=f"VLAN '{vlan_if}' has no firewall rules",
                            detail=(
                                f"VLAN {vlan_if} (tag {vlan.get('tag', '')}) has "
                                "no firewall rules. Traffic may be unrestricted."
                            ),
                            recommendation="Add firewall rules for this VLAN interface.",
                        )
                    )
        except Exception:
            pass

        if not findings:
            findings.append(
                Finding(
                    severity=Severity.INFORMATIONAL,
                    title="All VLANs healthy",
                    detail="No issues detected with VLAN configuration.",
                )
            )

        sections.append(format_severity_report("VLAN Audit", findings))

    if configure:
        sections.append(
            "### VLAN Configuration\n\n"
            "To create a new VLAN with full configuration (VLAN interface + IP + DHCP), "
            "use `opnsense__interfaces__configure_vlan` with:\n\n"
            "- `tag`: 802.1Q VLAN tag (1-4094)\n"
            "- `parent_if`: Parent physical interface (e.g., 'igb1')\n"
            "- `ip`: IP address for the VLAN interface\n"
            "- `subnet`: Subnet prefix length (e.g., '24')\n"
            "- `dhcp_range_from` / `dhcp_range_to`: Optional DHCP pool\n"
            "- `apply=True`: Required (write-gated)\n"
        )

    return "\n".join(sections)


# ===========================================================================
# Task 107: opnsense_dhcp_reserve_batch -- batch DHCP reservations
# ===========================================================================


def _parse_devices_json(devices_json: str) -> list[dict[str, str]]:
    """Parse and validate the devices JSON string for batch reservation.

    Expected format: [{"hostname": "x", "mac": "y", "ip": "z"}, ...]
    """
    try:
        devices = json.loads(devices_json)
    except json.JSONDecodeError as exc:
        raise ValidationError(
            f"Invalid JSON in devices list: {exc}",
            details={"field": "devices"},
        ) from exc

    if not isinstance(devices, list):
        raise ValidationError(
            "Devices must be a JSON array.",
            details={"field": "devices"},
        )

    validated: list[dict[str, str]] = []
    for i, dev in enumerate(devices):
        if not isinstance(dev, dict):
            raise ValidationError(
                f"Device entry {i} must be an object.",
                details={"field": "devices", "index": i},
            )

        mac = dev.get("mac", "").strip()
        ip = dev.get("ip", "").strip()
        hostname = dev.get("hostname", "").strip()

        if not mac:
            raise ValidationError(
                f"Device entry {i} is missing 'mac'.",
                details={"field": "devices", "index": i},
            )
        if not ip:
            raise ValidationError(
                f"Device entry {i} is missing 'ip'.",
                details={"field": "devices", "index": i},
            )
        if not _MAC_PATTERN.match(mac):
            raise ValidationError(
                f"Device entry {i} has invalid MAC format: '{mac}'. "
                "Expected format: aa:bb:cc:dd:ee:ff",
                details={"field": "devices", "index": i, "value": mac},
            )

        validated.append(
            {
                "hostname": hostname or f"device-{i}",
                "mac": mac.lower(),
                "ip": ip,
            }
        )

    if not validated:
        raise ValidationError(
            "Devices list must not be empty.",
            details={"field": "devices"},
        )

    return validated


@mcp_server.tool()
async def opnsense_dhcp_reserve_batch(
    interface: str,
    devices: str,
    apply: bool = False,
) -> str:
    """Batch-create DHCP static reservations for multiple devices.

    Accepts a list of devices as a JSON string and creates DHCP reservations
    for each. Verifies MAC addresses against current DHCP leases before
    creating reservations.

    Devices format (JSON array):
    ``[{"hostname": "printer", "mac": "aa:bb:cc:dd:ee:ff", "ip": "192.168.1.50"}, ...]``

    Without ``apply``: shows a plan of reservations to be created.
    With ``apply=True``: creates all reservations and reconfigures DHCP.
    Requires OPNSENSE_WRITE_ENABLED=true.

    Args:
        interface: Interface for the reservations (e.g., 'igb1').
        devices: JSON string array of device objects with hostname, mac, ip.
        apply: Create the reservations (write-gated).
    """
    if not interface or not interface.strip():
        raise ValidationError(
            "Interface must not be empty.",
            details={"field": "interface"},
        )

    # Parse and validate devices
    device_list = _parse_devices_json(devices)

    sections: list[str] = []

    # Show planned reservations
    headers = ["Hostname", "MAC", "IP", "Interface"]
    rows = [[d["hostname"], d["mac"], d["ip"], interface.strip()] for d in device_list]
    sections.append(format_table(headers, rows, title="Planned DHCP Reservations"))

    # Verify MACs against dnsmasq DHCP leases
    client = _get_client()
    lease_macs: set[str] = set()
    try:
        leases_raw = await client.get("dnsmasq", "leases", "search")
        if isinstance(leases_raw, dict):
            for lease in leases_raw.get("rows", []):
                mac = lease.get("hwaddr", "").lower()
                if mac:
                    lease_macs.add(mac)
    except Exception:
        pass  # Skip verification if leases endpoint fails
    finally:
        await client.close()

    verified: list[dict[str, str]] = []
    unverified: list[dict[str, str]] = []

    for dev in device_list:
        if dev["mac"] in lease_macs:
            verified.append(dev)
        else:
            unverified.append(dev)

    if verified:
        sections.append(f"\n**{len(verified)} device(s) verified** in current DHCP leases.")
    if unverified:
        unverified_list = ", ".join(f"{d['hostname']} ({d['mac']})" for d in unverified)
        sections.append(
            f"\n**{len(unverified)} device(s) not found** in current leases: "
            f"{unverified_list}\n\n"
            "These devices may not be currently connected or may use a different interface."
        )

    if not apply:
        sections.append(f"\n---\n*Plan-only mode.* {describe_write_status()}")
        return "\n".join(sections)

    # Apply mode — use dnsmasq addHost API (not Kea)
    if not check_write_enabled("OPNSENSE"):
        sections.append(f"\n---\n*Write operations are disabled.* {describe_write_status()}")
        return "\n".join(sections)

    client = _get_client()
    results: list[dict[str, Any]] = []
    errors: list[str] = []

    try:
        for dev in device_list:
            try:
                result = await client.write(
                    "dnsmasq",
                    "settings",
                    "addHost",
                    data={
                        "host": {
                            "host": dev["hostname"],
                            "domain": "home.local",
                            "ip": dev["ip"],
                            "hwaddr": dev["mac"],
                            "descr": f"Static reservation for {dev['hostname']}",
                        },
                    },
                )
                results.append({"hostname": dev["hostname"], "uuid": result.get("uuid", "")})
            except Exception as exc:
                errors.append(f"Failed: {dev['hostname']} ({dev['mac']} -> {dev['ip']}): {exc}")

        # Reconfigure dnsmasq once after all reservations
        if results:
            await client.reconfigure("dnsmasq", "service")
    finally:
        await client.close()

    sections.append(
        format_summary(
            "Batch Reservation Results",
            {
                "Created": len(results),
                "Failed": len(errors),
                "Total": len(device_list),
            },
        )
    )

    if errors:
        sections.append("### Errors\n\n" + "\n".join(f"- {e}" for e in errors) + "\n")

    return "\n".join(sections)


# ===========================================================================
# Task 108: opnsense_vpn, opnsense_dns, opnsense_secure, opnsense_firmware
# ===========================================================================


@mcp_server.tool()
async def opnsense_vpn() -> str:
    """VPN status report -- IPSec, OpenVPN, and WireGuard tunnels.

    Queries all three VPN technologies and returns a consolidated
    status report with per-technology tables, connection counts,
    and severity-tiered findings for disconnected tunnels or
    inactive peers.
    """
    from opnsense.agents.vpn import vpn_status_report

    client = _get_client()
    try:
        return await vpn_status_report(client)
    finally:
        await client.close()


@mcp_server.tool()
async def opnsense_dns() -> str:
    """DNS service report -- Unbound overrides, forwarders, and DHCP leases.

    Shows all DNS host overrides configured in Unbound and current
    DHCP leases from Kea. Highlights devices without hostnames and
    DNS configuration completeness.
    """
    from opnsense.agents.services import services_report

    client = _get_client()
    try:
        return await services_report(client)
    finally:
        await client.close()


@mcp_server.tool()
async def opnsense_secure() -> str:
    """Security posture audit -- IDS alerts, certificates, and policy review.

    Runs a comprehensive security audit covering:
    - Recent IDS/IPS alerts from Suricata (last 24h)
    - TLS certificate inventory and expiry status
    - IDS policy settings

    Returns a severity-tiered report with actionable findings.
    """
    from opnsense.agents.security import security_audit_report

    client = _get_client()
    try:
        return await security_audit_report(client)
    finally:
        await client.close()


@mcp_server.tool()
async def opnsense_firmware() -> str:
    """Firmware status -- version, updates, and installed packages.

    Checks the current firmware version, available updates, and
    installed package inventory. Highlights when firmware updates
    are available.
    """
    from opnsense.agents.firmware import firmware_report

    client = _get_client()
    try:
        return await firmware_report(client)
    finally:
        await client.close()


# ---------------------------------------------------------------------------
# VLAN creation command (write-gated)
# ---------------------------------------------------------------------------


@mcp_server.tool()
async def opnsense_vlan_create(
    tag: int,
    parent_if: str,
    ip: str,
    subnet: str,
    dhcp_range_from: str = "",
    dhcp_range_to: str = "",
    description: str = "",
    dns_servers: str = "",
    apply: bool = False,
) -> str:
    """Create a complete VLAN: interface, IP, and optionally DHCP.

    Atomic 4-step operation with rollback on failure:
    1. Create VLAN interface on parent
    2. Assign to OPNsense interface
    3. Set IP address
    4. (Optional) Configure DHCP subnet

    Without ``apply``: returns a plan preview.
    With ``apply=True``: executes (requires OPNSENSE_WRITE_ENABLED=true).

    Args:
        tag: 802.1Q VLAN tag (1-4094).
        parent_if: Parent physical interface (e.g. 'igb2').
        ip: IP address for the VLAN gateway (e.g. '172.16.20.1').
        subnet: CIDR prefix length (e.g. '24').
        dhcp_range_from: Start of DHCP pool (e.g. '172.16.20.100').
        dhcp_range_to: End of DHCP pool (e.g. '172.16.20.199').
        description: Human-readable name (e.g. 'Admin').
        dns_servers: Comma-separated DNS servers for DHCP clients.
        apply: Execute the changes. Requires OPNSENSE_WRITE_ENABLED=true.
    """
    has_dhcp = bool(dhcp_range_from and dhcp_range_to)

    # --- Plan preview ---
    plan_steps: list[dict[str, str]] = [
        {
            "description": (
                f"Create VLAN {tag} on {parent_if}" + (f" ({description})" if description else "")
            ),
        },
        {"description": f"Assign IP {ip}/{subnet}"},
    ]
    if has_dhcp:
        plan_steps.append({"description": f"Configure DHCP: {dhcp_range_from} - {dhcp_range_to}"})
        if dns_servers:
            plan_steps.append({"description": f"Set DNS servers: {dns_servers}"})

    plan = format_change_plan(steps=plan_steps)

    if not apply:
        write_status = describe_write_status("OPNSENSE")
        return f"{plan}\n\n---\n*Plan-only mode.* {write_status}"

    # --- Execute ---
    from opnsense.tools.interfaces import opnsense__interfaces__configure_vlan

    result = await opnsense__interfaces__configure_vlan(
        tag=tag,
        parent_if=parent_if,
        ip=ip,
        subnet=subnet,
        dhcp_range_from=dhcp_range_from,
        dhcp_range_to=dhcp_range_to,
        description=description,
        dns_servers=dns_servers,
        apply=True,
    )

    logger.info(
        "VLAN %d created via command layer (uuid=%s)",
        tag,
        result.get("vlan_uuid", ""),
        extra={"component": "commands"},
    )

    lines = [
        "## VLAN Created",
        "",
        f"- **Tag:** {result['tag']}",
        f"- **Parent:** {result['parent_if']}",
        f"- **IP:** {result['ip']}/{result['subnet']}",
        f"- **Description:** {result.get('description', '')}",
        f"- **UUID:** {result.get('vlan_uuid', '')}",
        f"- **Steps completed:** {', '.join(result.get('completed_steps', []))}",
    ]
    if has_dhcp:
        dhcp_from = result.get("dhcp_range_from", "")
        dhcp_to = result.get("dhcp_range_to", "")
        lines.append(f"- **DHCP:** {dhcp_from} - {dhcp_to}")
        if dns_servers:
            lines.append(f"- **DNS:** {result.get('dns_servers', '')}")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Firewall alias creation command (write-gated)
# ---------------------------------------------------------------------------


@mcp_server.tool()
async def opnsense_alias_create(
    name: str,
    alias_type: str,
    content: str,
    description: str = "",
    apply: bool = False,
) -> str:
    """Create a firewall alias (named address/port group).

    Without ``apply``: returns a plan preview.
    With ``apply=True``: executes (requires OPNSENSE_WRITE_ENABLED=true).

    Args:
        name: Alias name (e.g. 'RFC1918').
        alias_type: Type: 'host', 'network', 'port', or 'url'.
        content: Newline-separated values (e.g. '10.0.0.0/8\\n172.16.0.0/12').
        description: Human-readable description.
        apply: Execute the changes. Requires OPNSENSE_WRITE_ENABLED=true.
    """
    plan = format_change_plan(
        steps=[
            {"description": f"Create {alias_type} alias '{name}'"},
            {"description": f"Content: {content[:80]}{'...' if len(content) > 80 else ''}"},
        ]
    )

    if not apply:
        write_status = describe_write_status("OPNSENSE")
        return f"{plan}\n\n---\n*Plan-only mode.* {write_status}"

    from opnsense.tools.firewall import opnsense__firewall__add_alias

    result = await opnsense__firewall__add_alias(
        name=name,
        alias_type=alias_type,
        content=content,
        description=description,
        apply=True,
    )

    return (
        f"## Alias Created\n\n"
        f"- **Name:** {result['name']}\n"
        f"- **Type:** {result['alias_type']}\n"
        f"- **UUID:** {result.get('uuid', '')}"
    )


# ---------------------------------------------------------------------------
# Firewall rule creation command (write-gated)
# ---------------------------------------------------------------------------


@mcp_server.tool()
async def opnsense_rule_create(
    interface: str,
    action: str,
    src: str,
    dst: str,
    protocol: str = "any",
    description: str = "",
    position: int | None = None,
    apply: bool = False,
) -> str:
    """Create a firewall filter rule.

    Without ``apply``: returns a plan preview.
    With ``apply=True``: executes (requires OPNSENSE_WRITE_ENABLED=true).

    Args:
        interface: Interface name (e.g. 'lan', 'opt1').
        action: 'pass', 'block', or 'reject'.
        src: Source address, CIDR, alias name, or 'any'.
        dst: Destination address, CIDR, alias name, or 'any'.
        protocol: IP protocol (default 'any').
        description: Rule description.
        position: Optional rule sequence/position.
        apply: Execute the changes. Requires OPNSENSE_WRITE_ENABLED=true.
    """
    plan = format_change_plan(
        steps=[
            {"description": f"{action.upper()} {src} → {dst} on {interface}"},
            {"description": f"Protocol: {protocol}"},
        ]
    )

    if not apply:
        write_status = describe_write_status("OPNSENSE")
        return f"{plan}\n\n---\n*Plan-only mode.* {write_status}"

    from opnsense.tools.firewall import opnsense__firewall__add_rule

    result = await opnsense__firewall__add_rule(
        interface=interface,
        action=action,
        src=src,
        dst=dst,
        protocol=protocol,
        description=description,
        position=position,
        apply=True,
    )

    return (
        f"## Rule Created\n\n"
        f"- **Interface:** {result['interface']}\n"
        f"- **Action:** {result['action']}\n"
        f"- **Source:** {result['source']}\n"
        f"- **Destination:** {result['destination']}\n"
        f"- **Protocol:** {result['protocol']}\n"
        f"- **UUID:** {result.get('uuid', '')}"
    )


# ---------------------------------------------------------------------------
# DHCP configuration command (dnsmasq MVC API)
# ---------------------------------------------------------------------------


@mcp_server.tool()
async def opnsense_dhcp_configure(
    interface: str,
    start_addr: str,
    end_addr: str,
    description: str = "",
    domain: str = "",
    apply: bool = False,
) -> str:
    """Configure DHCP on an interface via dnsmasq.

    Adds the interface to dnsmasq listeners, creates a DHCP range,
    and reconfigures the service.

    Without ``apply``: returns a plan preview.
    With ``apply=True``: executes (requires OPNSENSE_WRITE_ENABLED=true).

    Args:
        interface: OPNsense interface identifier (e.g. 'opt3', 'opt4').
        start_addr: Start of DHCP pool (e.g. '172.16.20.100').
        end_addr: End of DHCP pool (e.g. '172.16.20.199').
        description: Human-readable description.
        domain: DNS domain for this range (e.g. 'home.local').
        apply: Execute the changes. Requires OPNSENSE_WRITE_ENABLED=true.
    """
    plan_steps = [
        {"description": f"Add {interface} to dnsmasq listeners"},
        {"description": f"Create DHCP range: {start_addr} - {end_addr}"},
    ]
    if domain:
        plan_steps.append({"description": f"Set domain: {domain}"})

    plan = format_change_plan(steps=plan_steps)

    if not apply:
        write_status = describe_write_status("OPNSENSE")
        return f"{plan}\n\n---\n*Plan-only mode.* {write_status}"

    client = _get_client()
    try:
        # Step 1: Add interface to dnsmasq listeners
        settings_raw = await client.get("dnsmasq", "settings", "get")
        iface_list: list[str] = []
        if isinstance(settings_raw, dict):
            dnsmasq_cfg = settings_raw.get("dnsmasq", {})
            if isinstance(dnsmasq_cfg, dict):
                iface_field = dnsmasq_cfg.get("interface", "")
                if isinstance(iface_field, str):
                    iface_list = [i.strip() for i in iface_field.split(",") if i.strip()]
                elif isinstance(iface_field, dict):
                    # OPNsense multi-select: {"opt3": {"selected": 1, ...}, ...}
                    iface_list = [
                        k
                        for k, v in iface_field.items()
                        if isinstance(v, dict) and v.get("selected")
                    ]
        if interface not in iface_list:
            iface_list.append(interface)

        await client.write(
            "dnsmasq",
            "settings",
            "set",
            data={"dnsmasq": {"interface": ",".join(iface_list)}},
        )

        # Step 2: Create DHCP range
        range_data: dict[str, Any] = {
            "range": {
                "interface": interface,
                "start_addr": start_addr,
                "end_addr": end_addr,
                "description": description,
                "domain_type": "range",
            },
        }
        if domain:
            range_data["range"]["domain"] = domain

        range_result = await client.write(
            "dnsmasq",
            "settings",
            "add_range",
            data=range_data,
        )

        range_uuid = range_result.get("uuid", "")

        # Step 3: Reconfigure
        await client.reconfigure("dnsmasq", "service")

    finally:
        await client.close()

    logger.info(
        "Configured DHCP on %s: %s-%s (uuid=%s)",
        interface,
        start_addr,
        end_addr,
        range_uuid,
        extra={"component": "commands"},
    )

    return (
        f"## DHCP Configured\n\n"
        f"- **Interface:** {interface}\n"
        f"- **Range:** {start_addr} - {end_addr}\n"
        f"- **Domain:** {domain or '(default)'}\n"
        f"- **UUID:** {range_uuid}\n"
        f"- **Description:** {description}"
    )


# ---------------------------------------------------------------------------
# DNS (Unbound) configuration command
# ---------------------------------------------------------------------------


@mcp_server.tool()
async def opnsense_dns_configure(
    interfaces: str,
    apply: bool = False,
) -> str:
    """Configure Unbound DNS to listen on specified interfaces.

    Reads current Unbound settings, adds the specified interfaces to
    the active listener list, and reconfigures the service.

    Without ``apply``: returns a plan preview.
    With ``apply=True``: executes (requires OPNSENSE_WRITE_ENABLED=true).

    Args:
        interfaces: Comma-separated OPNsense interface identifiers
            to add (e.g. 'opt3,opt4,opt5,opt6,opt7,opt8,opt9').
        apply: Execute the changes. Requires OPNSENSE_WRITE_ENABLED=true.
    """
    new_ifaces = [i.strip() for i in interfaces.split(",") if i.strip()]

    plan = format_change_plan(
        steps=[
            {"description": f"Add interfaces to Unbound DNS: {', '.join(new_ifaces)}"},
            {"description": "Reconfigure Unbound to apply"},
        ]
    )

    if not apply:
        write_status = describe_write_status("OPNSENSE")
        return f"{plan}\n\n---\n*Plan-only mode.* {write_status}"

    client = _get_client()
    try:
        # Get current Unbound settings
        settings_raw = await client.get("unbound", "settings", "get")

        # Parse current active interfaces
        current_list: list[str] = []
        if isinstance(settings_raw, dict):
            unbound_cfg = settings_raw.get("unbound", {})
            if isinstance(unbound_cfg, dict):
                general = unbound_cfg.get("general", {})
                if isinstance(general, dict):
                    iface_field = general.get("active_interface", "")
                    if isinstance(iface_field, str):
                        current_list = [i.strip() for i in iface_field.split(",") if i.strip()]
                    elif isinstance(iface_field, dict):
                        current_list = [
                            k
                            for k, v in iface_field.items()
                            if isinstance(v, dict) and v.get("selected")
                        ]

        # Merge new interfaces
        for iface in new_ifaces:
            if iface not in current_list:
                current_list.append(iface)

        # Set updated interfaces + enable DHCP hostname registration
        await client.write(
            "unbound",
            "settings",
            "set",
            data={
                "unbound": {
                    "general": {
                        "active_interface": ",".join(current_list),
                        "regdhcp": "1",
                        "regdhcpstatic": "1",
                    },
                },
            },
        )

        # Reconfigure
        await client.reconfigure("unbound", "service")

    finally:
        await client.close()

    logger.info(
        "Configured Unbound DNS to listen on: %s",
        ", ".join(current_list),
        extra={"component": "commands"},
    )

    return (
        f"## DNS Configured\n\n"
        f"- **Listening interfaces:** {', '.join(current_list)}\n"
        f"- **Status:** Reconfigured and applied"
    )


# ---------------------------------------------------------------------------
# DNS-over-TLS forwarding configuration
# ---------------------------------------------------------------------------


@mcp_server.tool()
async def opnsense_dns_forward(
    server: str,
    tls_hostname: str,
    port: int = 853,
    description: str = "",
    apply: bool = False,
) -> str:
    """Configure DNS-over-TLS forwarding to an upstream resolver.

    Adds a DoT forwarding server to Unbound and enables forwarding mode.
    Local DNS (DHCP hostnames, overrides) still resolves locally; only
    external queries are forwarded.

    Without ``apply``: returns a plan preview.
    With ``apply=True``: executes (requires OPNSENSE_WRITE_ENABLED=true).

    Args:
        server: DNS server IP address (e.g. '45.90.28.0' for NextDNS).
        tls_hostname: TLS verification hostname (e.g. 'fe1de8.dns.nextdns.io').
        port: DNS-over-TLS port (default 853).
        description: Human-readable description.
        apply: Execute the changes. Requires OPNSENSE_WRITE_ENABLED=true.
    """
    plan = format_change_plan(
        steps=[
            {"description": f"Add DoT forwarder: {server} ({tls_hostname}:{port})"},
            {"description": "Enable DNS forwarding mode"},
            {"description": "Reconfigure Unbound"},
        ]
    )

    if not apply:
        write_status = describe_write_status("OPNSENSE")
        return f"{plan}\n\n---\n*Plan-only mode.* {write_status}"

    client = _get_client()
    try:
        # Step 1: Add DoT forwarding entry
        dot_result = await client.write(
            "unbound",
            "settings",
            "addDot",
            data={
                "dot": {
                    "enabled": "1",
                    "type": "dot",
                    "server": server,
                    "port": str(port),
                    "verify": tls_hostname,
                    "description": description or f"DoT: {tls_hostname}",
                },
            },
        )

        dot_uuid = dot_result.get("uuid", "")

        # Step 2: Enable forwarding mode
        await client.write(
            "unbound",
            "settings",
            "set",
            data={
                "unbound": {
                    "forwarding": {
                        "enabled": "1",
                    },
                },
            },
        )

        # Step 3: Reconfigure
        await client.reconfigure("unbound", "service")

    finally:
        await client.close()

    logger.info(
        "Configured DoT forwarding to %s (%s:%d, uuid=%s)",
        tls_hostname,
        server,
        port,
        dot_uuid,
        extra={"component": "commands"},
    )

    return (
        f"## DNS-over-TLS Forwarding Configured\n\n"
        f"- **Server:** {server}\n"
        f"- **TLS Hostname:** {tls_hostname}\n"
        f"- **Port:** {port}\n"
        f"- **UUID:** {dot_uuid}\n"
        f"- **Forwarding mode:** Enabled\n"
        f"- **Description:** {description or f'DoT: {tls_hostname}'}"
    )
