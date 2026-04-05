# SPDX-License-Identifier: MIT
"""Parsers for system information on Cisco SG-300.

``show version`` format::

    SW version    3.0.0.37 ( date  30-Jun-2019 time  18:28:24 )
    Boot version  1.4.1.1 ( date  10-Jun-2018 time  15:29:39 )
    HW version    V01

    Unit    MAC Address
    ----    -----------------
    1       d8:b3:70:c9:e9:07

    Active-image: flash://system/images/simage2.bin

``show running-config`` hostname extraction::

    hostname SG300-28
"""

from __future__ import annotations

import re

from cisco.models.system import SwitchInfo


def parse_show_version(raw: str, hostname: str = "unknown") -> SwitchInfo:
    """Parse ``show version`` CLI output into a :class:`SwitchInfo` model.

    Parameters
    ----------
    raw:
        Raw text output from the ``show version`` command.
    hostname:
        The switch hostname, typically extracted separately from
        ``show running-config`` via :func:`parse_hostname_from_config`.
        Defaults to ``"unknown"`` since ``show version`` on the SG-300
        does not always include the hostname.

    Returns
    -------
    SwitchInfo
        Parsed system information.

    Notes
    -----
    The SG-300 ``show version`` output does not include a serial number or
    uptime.  These fields are set to ``""`` and ``0`` respectively.  To get
    uptime, use ``show system`` or SNMP.  The model field is derived from the
    HW version line or defaults to ``"SG-300"`` if not parseable.
    """
    # Extract firmware version: "SW version    3.0.0.37 ( date ...)"
    firmware_version = ""
    sw_match = re.search(r"SW version\s+([\d.]+)", raw)
    if sw_match:
        firmware_version = sw_match.group(1)

    # Extract HW version: "HW version    V01"
    model = "SG-300"
    hw_match = re.search(r"HW version\s+(\S+)", raw)
    if hw_match:
        model = f"SG-300 {hw_match.group(1)}"

    # Extract MAC address from the unit table:
    # 1       d8:b3:70:c9:e9:07
    mac_address = ""
    mac_match = re.search(
        r"^\s*\d+\s+([0-9a-fA-F]{2}:[0-9a-fA-F]{2}:[0-9a-fA-F]{2}:"
        r"[0-9a-fA-F]{2}:[0-9a-fA-F]{2}:[0-9a-fA-F]{2})\s*$",
        raw,
        re.MULTILINE,
    )
    if mac_match:
        mac_address = mac_match.group(1).lower()

    # Serial number is not available in show version on SG-300
    serial_number = ""

    # Uptime is not available in show version on SG-300
    # Use show system or SNMP sysUpTime for actual uptime
    uptime_seconds = 0

    return SwitchInfo(
        hostname=hostname,
        model=model,
        firmware_version=firmware_version,
        serial_number=serial_number,
        uptime_seconds=uptime_seconds,
        mac_address=mac_address,
    )


def parse_hostname_from_config(raw: str) -> str:
    """Extract the hostname from ``show running-config`` output.

    Parameters
    ----------
    raw:
        Raw text output from the ``show running-config`` command.

    Returns
    -------
    str
        The configured hostname, or ``"unknown"`` if not found.

    Notes
    -----
    Looks for the ``hostname <name>`` directive in the running configuration.
    """
    match = re.search(r"^hostname\s+(\S+)", raw, re.MULTILINE)
    if match:
        return match.group(1)
    return "unknown"
