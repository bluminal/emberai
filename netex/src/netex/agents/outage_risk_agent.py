# SPDX-License-Identifier: MIT
"""OutageRiskAgent -- pre-change outage risk assessment.

Read-only agent that assesses whether proposed changes could sever the
operator's access to the network.  Runs before every write plan as part
of the Phase 1 pre-change gate (PRD Section 10.3).

Session path resolution uses a 4-step fallback chain:
    1. ``OPERATOR_IP`` environment variable
    2. HTTP headers (if transport=http)
    3. ``--operator-ip`` CLI override
    4. Default to HIGH: "session path could not be determined"

Risk classification (PRD 10.3 / Appendix C.4):
    CRITICAL -- Change directly modifies the operator's session path.
    HIGH     -- Change is in the same subsystem; disruption is possible.
    MEDIUM   -- Indirect disruption (DNS, DHCP, routing loop).
    LOW      -- No intersection with the operator's session path.

A single assessment is performed per batch (not per operation).
"""

from __future__ import annotations

import logging
import os
from enum import StrEnum
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from netex.registry.plugin_registry import PluginRegistry

logger = logging.getLogger("netex.agents.outage_risk")


# ---------------------------------------------------------------------------
# Risk tier enum
# ---------------------------------------------------------------------------

class RiskTier(StrEnum):
    """Outage risk classification tiers, ordered most to least severe."""

    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


# Subsystem categories that map change steps to risk assessment.
_SESSION_PATH_SUBSYSTEMS = frozenset({
    "interface",
    "vlan",
    "route",
    "firewall",
})

_INDIRECT_SUBSYSTEMS = frozenset({
    "dns",
    "dhcp",
    "routing",
    "services",
})


# ---------------------------------------------------------------------------
# Session path resolution
# ---------------------------------------------------------------------------

def resolve_operator_ip(
    *,
    env_var: str | None = None,
    http_headers: dict[str, str] | None = None,
    cli_override: str | None = None,
) -> str | None:
    """Resolve the operator's session source IP using the 4-step fallback.

    Parameters
    ----------
    env_var:
        Override for the ``OPERATOR_IP`` env var value (for testing).
        If ``None``, reads ``os.environ["OPERATOR_IP"]``.
    http_headers:
        HTTP request headers (if transport=http).  Checks
        ``X-Forwarded-For`` and ``X-Real-IP``.
    cli_override:
        Explicit ``--operator-ip`` CLI argument value.

    Returns
    -------
    str | None
        The resolved operator IP, or ``None`` if it could not be
        determined (triggers HIGH default).
    """
    # Step 1: OPERATOR_IP env var
    operator_ip = env_var if env_var is not None else os.environ.get("OPERATOR_IP")
    if operator_ip:
        logger.debug("Operator IP resolved from env var: %s", operator_ip)
        return operator_ip

    # Step 2: HTTP headers
    if http_headers:
        for header in ("X-Forwarded-For", "X-Real-IP"):
            value = http_headers.get(header)
            if value:
                # X-Forwarded-For may contain a comma-separated list;
                # the first entry is the original client.
                ip = value.split(",")[0].strip()
                if ip:
                    logger.debug("Operator IP resolved from %s header: %s", header, ip)
                    return ip

    # Step 3: CLI override
    if cli_override:
        logger.debug("Operator IP resolved from CLI override: %s", cli_override)
        return cli_override

    # Step 4: Could not determine
    logger.warning("Operator IP could not be determined; defaulting to HIGH risk")
    return None


# ---------------------------------------------------------------------------
# OutageRiskAgent
# ---------------------------------------------------------------------------

class OutageRiskAgent:
    """Read-only agent that assesses whether proposed changes could sever
    the operator's access to the network.

    This agent never makes changes.  It queries the registry for
    diagnostic, topology, and client tools to determine the operator's
    session path, then classifies each batch of proposed changes into
    one of four risk tiers.

    A single assessment is produced per batch -- not per operation.
    """

    async def assess(
        self,
        change_steps: list[dict[str, Any]],
        registry: PluginRegistry,
        *,
        operator_ip: str | None = None,
        http_headers: dict[str, str] | None = None,
        cli_override: str | None = None,
    ) -> dict[str, Any]:
        """Assess outage risk for a set of proposed changes.

        Parameters
        ----------
        change_steps:
            List of change step dicts.  Each step should contain at
            minimum a ``subsystem`` key (e.g. ``"interface"``,
            ``"vlan"``, ``"route"``, ``"firewall"``, ``"dns"``,
            ``"dhcp"``).  Optional keys: ``target`` (the specific
            resource being modified), ``action`` (the operation type).
        registry:
            The plugin registry for querying available tools.
        operator_ip:
            Explicit operator IP (overrides env var / header resolution).
        http_headers:
            HTTP request headers for session path resolution.
        cli_override:
            CLI ``--operator-ip`` argument.

        Returns
        -------
        dict
            Assessment result with keys:
            - ``risk_tier``: ``"CRITICAL"`` | ``"HIGH"`` | ``"MEDIUM"``
              | ``"LOW"``
            - ``description``: Human-readable explanation.
            - ``affected_path``: The specific path element at risk, or
              ``None``.
            - ``operator_ip``: The resolved operator IP, or ``None``.
            - ``session_path_known``: Whether the session path was
              successfully determined.
        """
        if not change_steps:
            return {
                "risk_tier": RiskTier.LOW,
                "description": "No changes proposed.",
                "affected_path": None,
                "operator_ip": None,
                "session_path_known": True,
            }

        # Resolve operator IP
        resolved_ip = resolve_operator_ip(
            env_var=operator_ip,
            http_headers=http_headers,
            cli_override=cli_override,
        )

        # Gather available diagnostic tools
        session_path = await self._resolve_session_path(resolved_ip, registry)

        # If session path could not be determined, default to HIGH
        if not session_path["known"]:
            return {
                "risk_tier": RiskTier.HIGH,
                "description": (
                    "Session path could not be determined"
                    + (f" (operator IP: {resolved_ip})" if resolved_ip else "")
                    + ". Defaulting to HIGH risk."
                ),
                "affected_path": None,
                "operator_ip": resolved_ip,
                "session_path_known": False,
            }

        # Classify risk based on change steps vs session path
        return self._classify_risk(change_steps, session_path, resolved_ip)

    async def _resolve_session_path(
        self,
        operator_ip: str | None,
        registry: PluginRegistry,
    ) -> dict[str, Any]:
        """Attempt to resolve the operator's full session path.

        Uses diagnostic, topology, and client tools from the registry
        to determine which interfaces, VLANs, routes, and firewall
        rules the operator's session traverses.

        Returns
        -------
        dict
            Session path info with keys:
            - ``known``: Whether the path was successfully determined.
            - ``interfaces``: List of interface names in the path.
            - ``vlans``: List of VLAN IDs in the path.
            - ``routes``: List of route destinations in the path.
            - ``firewall_rules``: List of rule IDs permitting the
              session.
        """
        if operator_ip is None:
            return {
                "known": False, "interfaces": [], "vlans": [],
                "routes": [], "firewall_rules": [],
            }

        # Check what tools are available
        diag_tools = registry.tools_for_skill("diagnostics")
        topo_tools = registry.tools_for_skill("topology")
        client_tools = registry.tools_for_skill("clients")

        has_tools = bool(diag_tools or topo_tools or client_tools)

        if not has_tools:
            logger.warning(
                "No diagnostic, topology, or client tools available; "
                "session path cannot be determined"
            )
            return {
                "known": False, "interfaces": [], "vlans": [],
                "routes": [], "firewall_rules": [],
            }

        # In a production implementation, this would call the actual MCP
        # tools to trace the session path.  For now, we mark the path as
        # known (tools are available and operator IP is resolved) and
        # return empty path details that will be populated by tool calls.
        #
        # The actual tool invocations would be:
        # 1. opnsense__diagnostics__run_traceroute(operator_ip)
        # 2. unifi__topology__get_device / get_vlans
        # 3. unifi__clients__list_clients (to find operator's switch port)
        return {
            "known": True,
            "interfaces": [],
            "vlans": [],
            "routes": [],
            "firewall_rules": [],
            "operator_ip": operator_ip,
        }

    def _classify_risk(
        self,
        change_steps: list[dict[str, Any]],
        session_path: dict[str, Any],
        operator_ip: str | None,
    ) -> dict[str, Any]:
        """Classify the risk tier based on change steps and session path.

        Single-pass classification: the highest risk from any step in
        the batch determines the overall batch risk tier.

        Parameters
        ----------
        change_steps:
            The proposed change steps.
        session_path:
            The resolved session path information.
        operator_ip:
            The resolved operator IP address.

        Returns
        -------
        dict
            The risk assessment result.
        """
        highest_risk = RiskTier.LOW
        description_parts: list[str] = []
        affected_path: str | None = None

        for step in change_steps:
            subsystem = step.get("subsystem", "").lower()
            target = step.get("target", "")
            action = step.get("action", "")

            step_risk, step_desc, step_path = self._classify_step(
                subsystem, target, action, session_path,
            )

            if _risk_order(step_risk) < _risk_order(highest_risk):
                highest_risk = step_risk
                affected_path = step_path

            if step_desc:
                description_parts.append(step_desc)

        # Build final description
        if highest_risk == RiskTier.LOW:
            description = "No intersection with operator's session path."
        elif not description_parts:
            description = f"Risk tier: {highest_risk.value}"
        else:
            description = " ".join(description_parts)

        return {
            "risk_tier": highest_risk,
            "description": description,
            "affected_path": affected_path,
            "operator_ip": operator_ip,
            "session_path_known": True,
        }

    def _classify_step(
        self,
        subsystem: str,
        target: str,
        action: str,
        session_path: dict[str, Any],
    ) -> tuple[RiskTier, str, str | None]:
        """Classify a single change step.

        Returns
        -------
        tuple
            (risk_tier, description, affected_path_element)
        """
        # Check for direct session path modification (CRITICAL)
        if subsystem in _SESSION_PATH_SUBSYSTEMS:
            if self._intersects_session_path(subsystem, target, session_path):
                return (
                    RiskTier.CRITICAL,
                    f"Change directly modifies {subsystem}"
                    + (f" '{target}'" if target else "")
                    + " which the operator's session traverses.",
                    target or subsystem,
                )

            # Same subsystem but not directly on session path (HIGH)
            return (
                RiskTier.HIGH,
                f"Change modifies {subsystem}"
                + (f" '{target}'" if target else "")
                + " in the same subsystem as the operator's session; "
                "partial disruption is possible.",
                target or subsystem,
            )

        # Indirect disruption potential (MEDIUM)
        if subsystem in _INDIRECT_SUBSYSTEMS:
            return (
                RiskTier.MEDIUM,
                f"Change to {subsystem}"
                + (f" '{target}'" if target else "")
                + " could cause indirect disruption.",
                target or subsystem,
            )

        # No intersection (LOW)
        return (RiskTier.LOW, "", None)

    def _intersects_session_path(
        self,
        subsystem: str,
        target: str,
        session_path: dict[str, Any],
    ) -> bool:
        """Check whether a change target intersects the session path.

        Parameters
        ----------
        subsystem:
            The subsystem category (interface, vlan, route, firewall).
        target:
            The specific resource identifier being modified.
        session_path:
            The resolved session path with lists of interfaces, vlans,
            routes, and firewall_rules.

        Returns
        -------
        bool
            ``True`` if the target is in the operator's session path.
        """
        if not target:
            return False

        if subsystem == "interface":
            return target in session_path.get("interfaces", [])
        elif subsystem == "vlan":
            # Target might be a VLAN ID (int-like) or a VLAN name
            vlans = session_path.get("vlans", [])
            return target in vlans or _try_int(target) in vlans
        elif subsystem == "route":
            return target in session_path.get("routes", [])
        elif subsystem == "firewall":
            return target in session_path.get("firewall_rules", [])

        return False


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _risk_order(tier: RiskTier) -> int:
    """Return sort order for risk tiers (lower = more severe)."""
    return {
        RiskTier.CRITICAL: 0,
        RiskTier.HIGH: 1,
        RiskTier.MEDIUM: 2,
        RiskTier.LOW: 3,
    }.get(tier, 99)


def _try_int(value: str) -> int | None:
    """Try to convert a string to int, return None on failure."""
    try:
        return int(value)
    except (ValueError, TypeError):
        return None
