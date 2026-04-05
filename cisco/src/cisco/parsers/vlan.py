# SPDX-License-Identifier: MIT
"""Parser for ``show vlan`` output on Cisco SG-300.

Expected format::

    VLAN    Name                             Ports                       Type     Authorization
    ----    -------------------------------- --------------------------- -------- -------------
     1      default                          gi1-2,gi4-24,Po1-8          Default  Required
     10     Admin                            gi3                         Static   Required
     30     Trusted                                                      Static   Required
     40     Streaming                        gi1                         Static   Required
"""

from __future__ import annotations

import re

from cisco.models.vlan import VLAN


def _expand_port_range(port_spec: str) -> list[str]:
    """Expand a port range like ``gi1-8`` into individual ports.

    Handles formats:
    - ``gi1`` -> ``["gi1"]``
    - ``gi1-8`` -> ``["gi1", "gi2", ..., "gi8"]``
    - ``Po1-8`` -> ``["Po1", "Po2", ..., "Po8"]``

    Parameters
    ----------
    port_spec:
        A single port or port range string.

    Returns
    -------
    list[str]
        Expanded list of individual port identifiers.
    """
    match = re.match(r"^([A-Za-z]+)(\d+)-(\d+)$", port_spec)
    if match:
        prefix = match.group(1)
        start = int(match.group(2))
        end = int(match.group(3))
        return [f"{prefix}{i}" for i in range(start, end + 1)]
    return [port_spec]


def _parse_port_list(ports_str: str) -> list[str]:
    """Parse a comma-separated port list with possible ranges.

    Parameters
    ----------
    ports_str:
        Comma-separated port list (e.g. ``gi1-2,gi4-24,Po1-8``).

    Returns
    -------
    list[str]
        Flat list of individual port identifiers.
    """
    if not ports_str or not ports_str.strip():
        return []

    ports: list[str] = []
    for part in ports_str.split(","):
        part = part.strip()
        if part:
            ports.extend(_expand_port_range(part))
    return ports


def parse_show_vlan(raw: str) -> list[VLAN]:
    """Parse ``show vlan`` CLI output into a list of VLAN models.

    Parameters
    ----------
    raw:
        Raw text output from the ``show vlan`` command.

    Returns
    -------
    list[VLAN]
        Parsed VLAN entries.  Empty port lists are preserved as ``[]``.
    """
    vlans: list[VLAN] = []

    # Match VLAN table rows:
    #   Leading whitespace, VLAN ID (1-4094), name, optional ports, type, authorization
    # The name column is up to 32 chars, ports up to ~27 chars, type and auth follow.
    # We use a regex that captures the VLAN ID, name, and ports fields.
    #
    # Line format (fixed-width columns):
    #  <space><VLAN><spaces><Name (up to 32)><spaces><Ports (up to 27)><spaces><Type><spaces><Auth>
    vlan_line_re = re.compile(
        r"^\s*(\d+)\s+"           # VLAN ID
        r"(\S+(?:\s+\S+)*?)\s+"  # Name (may contain spaces, non-greedy)
        r"("                      # Ports group start
        r"(?:[A-Za-z]+\d+"        # Port prefix + number
        r"(?:-\d+)?"              # Optional range end
        r"(?:,[A-Za-z]+\d+"       # Additional ports
        r"(?:-\d+)?)*"            # With optional ranges
        r")?"                     # Ports are optional (VLAN may have no members)
        r")\s+"
        r"(\S+)\s+"              # Type (Default, Static, etc.)
        r"(\S+)\s*$",            # Authorization
    )

    for line in raw.splitlines():
        line_stripped = line.strip()

        # Skip header lines, separator lines, and empty lines
        if not line_stripped:
            continue
        if line_stripped.startswith("VLAN") or line_stripped.startswith("----"):
            continue

        match = vlan_line_re.match(line)
        if not match:
            continue

        vlan_id = int(match.group(1))
        name = match.group(2).strip()
        ports_str = match.group(3).strip() if match.group(3) else ""

        ports = _parse_port_list(ports_str)

        vlans.append(
            VLAN(
                id=vlan_id,
                name=name,
                ports=ports,
                tagged_ports=[],  # show vlan doesn't distinguish tagged/untagged
            )
        )

    return vlans
