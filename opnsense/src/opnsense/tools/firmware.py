# SPDX-License-Identifier: MIT
"""Firmware skill tools for OPNsense system firmware management.

Provides read-only tools for querying firmware status and installed
packages. Firmware upgrades are intentionally NOT exposed as tools --
they should be performed through the OPNsense web UI with operator
oversight.

Tools
-----
- ``opnsense__firmware__get_status`` -- Firmware version and update status
- ``opnsense__firmware__list_packages`` -- Installed package inventory
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from opnsense.models.firmware import FirmwareStatus

if TYPE_CHECKING:
    from opnsense.api.opnsense_client import OPNsenseClient

logger = logging.getLogger(__name__)


async def opnsense__firmware__get_status(
    client: OPNsenseClient,
) -> dict[str, Any]:
    """Get firmware status and update availability.

    Queries ``GET /api/core/firmware/status`` and returns the current
    firmware version, available updates, and last check timestamp.

    Parameters
    ----------
    client:
        Authenticated OPNsense API client.

    Returns
    -------
    dict
        Firmware status with normalized field names.
    """
    raw = await client.get("core", "firmware", "status")

    try:
        status = FirmwareStatus.model_validate(raw)
        result = status.model_dump()
    except Exception:
        logger.warning("Failed to parse firmware status, returning raw response")
        result = raw

    logger.info(
        "Firmware status: current=%s, upgrade_available=%s",
        result.get("current_version", "unknown"),
        result.get("upgrade_available", "unknown"),
    )
    return result


async def opnsense__firmware__list_packages(
    client: OPNsenseClient,
) -> list[dict[str, Any]]:
    """List installed packages and plugins.

    Queries ``GET /api/core/firmware/info`` and returns the full
    package inventory including version numbers, descriptions,
    and update availability.

    Parameters
    ----------
    client:
        Authenticated OPNsense API client.

    Returns
    -------
    list[dict]
        List of package dictionaries with name, version, and status.
    """
    raw = await client.get("core", "firmware", "info")

    # The firmware info endpoint returns packages in various structures
    packages: list[dict[str, Any]] = []
    if "package" in raw and isinstance(raw["package"], list):
        packages = raw["package"]
    elif "packages" in raw and isinstance(raw["packages"], list):
        packages = raw["packages"]
    elif "rows" in raw and isinstance(raw["rows"], list):
        packages = raw["rows"]
    else:
        # Wrap as list for consistent return type
        packages = [raw]

    logger.info("Listed %d installed packages", len(packages))
    return packages
