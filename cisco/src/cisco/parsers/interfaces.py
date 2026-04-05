# SPDX-License-Identifier: MIT
"""Parsers for interface and switchport CLI output on Cisco SG-300.

``show interfaces status`` format::

                                              Flow Link          Back   Mdx
    Port     Type         Duplex  Speed Neg      ctrl State       Pressure Mode
    -------- ------------ ------  ----- -------- ---- ----------- -------- ----
    gi1      1G-Copper    Full    1000  Enabled  Off  Up          Disabled Auto
    gi2      1G-Copper    Full    1000  Enabled  Off  Up          Disabled Auto
    gi3      1G-Copper      --      --     --     --  Down           --     --

``show interfaces switchport <port>`` format::

    Port : gi1
    Port Mode: Trunk
    Gvrp Status: disabled
    Ingress Filtering: true
    Acceptable Frame Type: admitAll
    Ingress UnTagged VLAN ( NATIVE ): 1

    Port is member in:

    Vlan               Name               Egress rule Port Membership Type
    ---- -------------------------------- ----------- --------------------
     1   default                          Untagged    System
     10  Admin                            Tagged      Static
     30  Trusted                          Tagged      Static
"""

from __future__ import annotations

import re

from cisco.models.interfaces import Port, PortDetail


def parse_show_interfaces_status(raw: str) -> list[Port]:
    """Parse ``show interfaces status`` CLI output.

    Parameters
    ----------
    raw:
        Raw text output from the ``show interfaces status`` command.

    Returns
    -------
    list[Port]
        One :class:`Port` per physical/logical interface line.
    """
    ports: list[Port] = []

    # Match lines like:
    # gi1      1G-Copper    Full    1000  Enabled  Off  Up          Disabled Auto
    # gi3      1G-Copper      --      --     --     --  Down           --     --
    port_re = re.compile(
        r"^(gi\d+|fa\d+|Po\d+|te\d+)\s+"  # Port ID
        r"(\S+)\s+"                         # Type (1G-Copper, 10G-Fiber, etc.)
        r"(\S+)\s+"                         # Duplex (Full, Half, --)
        r"(\S+)\s+"                         # Speed (1000, 100, --)
        r"(\S+)\s+"                         # Negotiation (Enabled, Disabled, --)
        r"(\S+)\s+"                         # Flow control (Off, On, --)
        r"(\S+)"                            # Link State (Up, Down)
        r"(?:\s+(\S+))?"                    # Back Pressure (optional, may be --)
        r"(?:\s+(\S+))?\s*$",               # MDI/MDIX Mode (optional)
        re.IGNORECASE,
    )

    for line in raw.splitlines():
        match = port_re.match(line.strip())
        if not match:
            continue

        port_id = match.group(1)
        speed = match.group(4)
        duplex = match.group(3)
        status = match.group(7)

        ports.append(
            Port(
                id=port_id,
                name=port_id,
                status=status,
                speed=speed if speed != "--" else "unknown",
                duplex=duplex if duplex != "--" else "unknown",
                vlan_id=None,  # Not available in show interfaces status
                mode="",       # Not available in show interfaces status
                description="",
            )
        )

    return ports


def parse_show_switchport(raw: str) -> PortDetail:
    """Parse ``show interfaces switchport <port>`` CLI output.

    Parameters
    ----------
    raw:
        Raw text output from the ``show interfaces switchport <port>`` command.

    Returns
    -------
    PortDetail
        Detailed port information including VLAN membership.

    Raises
    ------
    ValueError
        If the port ID cannot be extracted from the output.
    """
    # Extract port ID
    port_match = re.search(r"Port\s*:\s*(\S+)", raw)
    if not port_match:
        raise ValueError("Could not extract port ID from switchport output")
    port_id = port_match.group(1)

    # Extract port mode (Access, Trunk, General, etc.)
    mode_match = re.search(r"Port Mode:\s*(\S+)", raw)
    mode = mode_match.group(1) if mode_match else "unknown"

    # Extract native VLAN
    native_vlan: int | None = None
    native_match = re.search(
        r"Ingress UnTagged VLAN\s*\(\s*NATIVE\s*\)\s*:\s*(\d+)", raw
    )
    if native_match:
        native_vlan = int(native_match.group(1))

    # Parse VLAN membership table
    trunk_allowed_vlans: list[int] = []
    tagged_vlans: list[int] = []
    untagged_vlan_id: int | None = None

    # Match VLAN membership lines:
    #  1   default                          Untagged    System
    #  10  Admin                            Tagged      Static
    vlan_member_re = re.compile(
        r"^\s*(\d+)\s+"           # VLAN ID
        r"(\S+(?:\s+\S+)*?)\s+"  # Name
        r"(Tagged|Untagged)\s+"   # Egress rule
        r"(\S+)\s*$",            # Membership type
    )

    in_member_table = False
    for line in raw.splitlines():
        stripped = line.strip()

        # Detect start of membership table (after "Port is member in:" header)
        if "Port is member in:" in stripped:
            in_member_table = True
            continue

        if not in_member_table:
            continue

        # Skip header and separator lines within the table
        if stripped.startswith("Vlan") or stripped.startswith("----"):
            continue

        match = vlan_member_re.match(line)
        if not match:
            continue

        vlan_id = int(match.group(1))
        egress_rule = match.group(3)

        trunk_allowed_vlans.append(vlan_id)
        if egress_rule == "Tagged":
            tagged_vlans.append(vlan_id)
        elif egress_rule == "Untagged":
            untagged_vlan_id = vlan_id

    return PortDetail(
        id=port_id,
        name=port_id,
        status="",        # Not available in switchport output
        speed="",         # Not available in switchport output
        duplex="",        # Not available in switchport output
        vlan_id=untagged_vlan_id,
        mode=mode,
        description="",
        trunk_allowed_vlans=trunk_allowed_vlans,
        native_vlan=native_vlan,
    )
