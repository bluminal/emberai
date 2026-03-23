# SPDX-License-Identifier: MIT
"""Security skill tools for OPNsense IDS/IPS (Suricata) and certificates.

Provides read-only tools for querying Suricata IDS alerts, rules, policy
settings, and TLS certificate inventory. No write operations -- IDS
configuration changes are handled via the OPNsense web UI.

Tools
-----
- ``opnsense__security__get_ids_alerts`` -- Recent IDS alerts with filtering
- ``opnsense__security__get_ids_rules`` -- IDS rule search
- ``opnsense__security__get_ids_policy`` -- IDS/IPS policy settings
- ``opnsense__security__get_certificates`` -- TLS certificate inventory
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from opnsense.models.security import Certificate, IDSAlert

if TYPE_CHECKING:
    from opnsense.api.opnsense_client import OPNsenseClient

logger = logging.getLogger(__name__)


async def opnsense__security__get_ids_alerts(
    client: OPNsenseClient,
    *,
    hours: int | None = None,
    severity: int | None = None,
) -> list[dict[str, Any]]:
    """Get recent IDS/IPS alerts from Suricata.

    Queries ``GET /api/ids/service/queryAlerts`` and returns alert data
    with optional time-based and severity filtering.

    Parameters
    ----------
    client:
        Authenticated OPNsense API client.
    hours:
        If provided, only return alerts from the last N hours.
        Passed as ``fileSince`` parameter to the API.
    severity:
        If provided, filter to alerts at this severity level or higher
        (1=high, 2=medium, 3=low). Post-API filter since the API
        returns all alerts.

    Returns
    -------
    list[dict]
        List of IDS alert dictionaries with normalized field names.
    """
    params: dict[str, Any] = {}
    if hours is not None:
        # OPNsense uses fileSince parameter for time filtering
        params["fileSince"] = str(hours)

    raw = await client.get("ids", "service", "queryAlerts", params=params)
    rows = raw.get("rows", [])

    alerts: list[dict[str, Any]] = []
    for row in rows:
        try:
            alert = IDSAlert.model_validate(row)
            alert_dict = alert.model_dump()

            # Post-filter by severity if requested
            if severity is not None and alert_dict.get("severity", 3) > severity:
                continue

            alerts.append(alert_dict)
        except Exception:
            logger.warning("Failed to parse IDS alert: %s", row.get("timestamp", "unknown"))
            # Still include unparseable alerts if they pass severity filter
            if severity is None or row.get("alert_sev", 3) <= severity:
                alerts.append(row)

    logger.info(
        "Retrieved %d IDS alerts (hours=%s, severity=%s)",
        len(alerts),
        hours,
        severity,
    )
    return alerts


async def opnsense__security__get_ids_rules(
    client: OPNsenseClient,
    *,
    filter_text: str | None = None,
) -> list[dict[str, Any]]:
    """Search IDS/IPS rules.

    Queries ``GET /api/ids/rule/searchRule`` and returns matching rules.

    Parameters
    ----------
    client:
        Authenticated OPNsense API client.
    filter_text:
        If provided, search rules matching this text pattern.
        Passed as ``searchPhrase`` parameter.

    Returns
    -------
    list[dict]
        List of IDS rule dictionaries.
    """
    params: dict[str, Any] = {}
    if filter_text is not None:
        params["searchPhrase"] = filter_text

    raw = await client.get("ids", "rule", "searchRule", params=params)
    rows: list[dict[str, Any]] = raw.get("rows", [])

    logger.info("Retrieved %d IDS rules (filter=%s)", len(rows), filter_text)
    return rows


async def opnsense__security__get_ids_policy(
    client: OPNsenseClient,
) -> dict[str, Any]:
    """Get IDS/IPS policy settings.

    Queries ``GET /api/ids/settings/getSettings`` and returns the full
    Suricata configuration including enabled rulesets, interfaces,
    pattern matcher, and operation mode (IDS vs IPS).

    Parameters
    ----------
    client:
        Authenticated OPNsense API client.

    Returns
    -------
    dict
        IDS policy settings dictionary.
    """
    raw = await client.get("ids", "settings", "getSettings")
    logger.info("Retrieved IDS policy settings")
    return raw


async def opnsense__security__get_certificates(
    client: OPNsenseClient,
) -> list[dict[str, Any]]:
    """Get TLS certificate inventory from the trust store.

    Queries ``GET /api/trust/cert/search`` and returns all certificates
    with expiry dates, SANs, issuer information, and which services
    are currently using each certificate.

    Parameters
    ----------
    client:
        Authenticated OPNsense API client.

    Returns
    -------
    list[dict]
        List of certificate dictionaries with normalized field names.
    """
    raw = await client.get("trust", "cert", "search")
    rows = raw.get("rows", [])

    certs: list[dict[str, Any]] = []
    for row in rows:
        try:
            cert = Certificate.model_validate(row)
            certs.append(cert.model_dump())
        except Exception:
            logger.warning("Failed to parse certificate: %s", row.get("cn", "unknown"))
            certs.append(row)

    logger.info("Listed %d certificates", len(certs))
    return certs
