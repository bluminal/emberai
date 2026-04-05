# SPDX-License-Identifier: MIT
"""Parser for ``show mac address-table`` output on Cisco SG-300.

Expected format::

              Aging Time: 300 sec

        Vlan    Mac Address         Type        Port
        ----    -----------         ----        ----
         1      00:08:a2:09:78:fa   Dynamic     gi24
         10     1c:0b:8b:70:ae:b4   Dynamic     gi3
         30     28:70:4e:26:e1:85   Dynamic     gi1
"""

from __future__ import annotations

import re

from cisco.models.mac_table import MACEntry


def _normalize_mac(mac: str) -> str:
    """Normalize a MAC address to lowercase colon-separated format.

    Handles common formats:
    - ``00:08:A2:09:78:FA`` -> ``00:08:a2:09:78:fa``
    - ``0008.a209.78fa`` -> ``00:08:a2:09:78:fa``
    - ``00-08-A2-09-78-FA`` -> ``00:08:a2:09:78:fa``

    Parameters
    ----------
    mac:
        MAC address in any common format.

    Returns
    -------
    str
        Lowercase colon-separated MAC address.
    """
    # Strip all separators, lowercase
    clean = re.sub(r"[.:\-]", "", mac).lower()
    # Insert colons every 2 characters
    return ":".join(clean[i : i + 2] for i in range(0, 12, 2))


def parse_show_mac_address_table(raw: str) -> list[MACEntry]:
    """Parse ``show mac address-table`` CLI output.

    Parameters
    ----------
    raw:
        Raw text output from the ``show mac address-table`` command.

    Returns
    -------
    list[MACEntry]
        Parsed MAC address table entries.  Header lines, separator lines,
        and footer summary lines are ignored.
    """
    entries: list[MACEntry] = []

    # Match lines like:
    #  1      00:08:a2:09:78:fa   Dynamic     gi24
    mac_line_re = re.compile(
        r"^\s*(\d+)\s+"                            # VLAN ID
        r"([0-9a-fA-F]{2}[:\.\-]"                  # MAC address start
        r"[0-9a-fA-F]{2}[:\.\-]?"                  # ...
        r"[0-9a-fA-F]{2}[:\.\-]?"                  # ...
        r"[0-9a-fA-F]{2}[:\.\-]?"                  # ...
        r"[0-9a-fA-F]{2}[:\.\-]?"                  # ...
        r"[0-9a-fA-F]{2})\s+"                      # MAC address end
        r"(\S+)\s+"                                  # Type (Dynamic, Static, etc.)
        r"(\S+)\s*$",                                # Port
    )

    # Also handle dot-separated MACs like 0008.a209.78fa
    mac_line_dot_re = re.compile(
        r"^\s*(\d+)\s+"                              # VLAN ID
        r"([0-9a-fA-F]{4}\.[0-9a-fA-F]{4}"          # MAC dot format
        r"\.[0-9a-fA-F]{4})\s+"
        r"(\S+)\s+"                                  # Type
        r"(\S+)\s*$",                                # Port
    )

    for line in raw.splitlines():
        stripped = line.strip()

        # Skip empty lines, headers, separators, and footer lines
        if not stripped:
            continue
        if stripped.startswith("Vlan") or stripped.startswith("----"):
            continue
        if "Aging Time" in stripped:
            continue
        if "Total Mac Addresses" in stripped or "Total" in stripped.split()[0:1]:
            continue

        match = mac_line_re.match(line) or mac_line_dot_re.match(line)
        if not match:
            continue

        vlan_id = int(match.group(1))
        mac = _normalize_mac(match.group(2))
        entry_type = match.group(3)
        interface = match.group(4)

        entries.append(
            MACEntry(
                mac=mac,
                vlan_id=vlan_id,
                interface=interface,
                entry_type=entry_type,
            )
        )

    return entries
