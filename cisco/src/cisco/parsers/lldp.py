# SPDX-License-Identifier: MIT
"""Parser for ``show lldp neighbors`` output on Cisco SG-300.

Expected format::

      System capability supported: Bridge, Router
      Port ID subtype: Local
      Port ID: gi1

        Device ID         Local Intf     Hold-time  Capability      Port ID
        ---------------   ----------     ---------  ----------      ----------
        USW-Pro-24-PoE    gi24           120        B               52
        OPNsense.local    gi23           120        R               igb2
"""

from __future__ import annotations

import re

from cisco.models.lldp import LLDPNeighbor


def parse_show_lldp_neighbors(raw: str) -> list[LLDPNeighbor]:
    """Parse ``show lldp neighbors`` CLI output.

    Parameters
    ----------
    raw:
        Raw text output from the ``show lldp neighbors`` command.

    Returns
    -------
    list[LLDPNeighbor]
        Parsed LLDP neighbor entries.

    Notes
    -----
    The SG-300 ``show lldp neighbors`` table does not include remote IP
    addresses.  The ``remote_ip`` field is always ``None`` in the returned
    models.  To obtain remote IPs, use ``show lldp neighbors <port>`` for
    per-port detail (which would require a separate parser).
    """
    neighbors: list[LLDPNeighbor] = []

    # Match table rows like:
    # USW-Pro-24-PoE    gi24           120        B               52
    # OPNsense.local    gi23           120        R               igb2
    neighbor_re = re.compile(
        r"^\s*"
        r"(\S+)\s+"          # Device ID
        r"(gi\d+|fa\d+|Po\d+|te\d+)\s+"  # Local Interface
        r"(\d+)\s+"          # Hold-time
        r"(\S+)\s+"          # Capability (B, R, B/R, etc.)
        r"(\S+)\s*$",        # Port ID (remote)
    )

    in_table = False
    for line in raw.splitlines():
        stripped = line.strip()

        # Detect the table header or separator to know we're in the table
        if stripped.startswith("Device ID") or stripped.startswith("---------------"):
            in_table = True
            continue

        if not in_table:
            continue

        # Stop at blank lines after the table
        if not stripped:
            # Could be end of table, but could also be spacing -- keep going
            continue

        match = neighbor_re.match(line)
        if not match:
            continue

        device_id = match.group(1)
        local_port = match.group(2)
        capabilities = match.group(4)
        remote_port = match.group(5)

        neighbors.append(
            LLDPNeighbor(
                local_port=local_port,
                remote_device=device_id,
                remote_port=remote_port,
                capabilities=capabilities,
                remote_ip=None,  # Not available in summary table
            )
        )

    return neighbors
