"""Shared validators and type aliases for Cisco models."""

from __future__ import annotations

import re
from typing import Annotated

# Type alias for MAC address fields
MACAddress = Annotated[str, "Colon-separated lowercase MAC address"]


def normalize_mac(mac: str) -> str:
    """Normalize a MAC address to lowercase colon-separated format.

    Accepts formats:
    - aa:bb:cc:dd:ee:ff (colon-separated)
    - aa-bb-cc-dd-ee-ff (dash-separated)
    - aabb.ccdd.eeff (Cisco dot notation)
    - aabbccddeeff (bare hex)

    Returns:
        Lowercase colon-separated MAC (e.g. ``"aa:bb:cc:dd:ee:ff"``).

    Raises:
        ValueError: If the input is not a valid MAC address.
    """
    # Strip all separators to get bare hex
    bare = re.sub(r"[:\-.]", "", mac.strip())
    if len(bare) != 12 or not all(c in "0123456789abcdefABCDEF" for c in bare):
        raise ValueError(f"Invalid MAC address: {mac!r}")
    bare = bare.lower()
    return ":".join(bare[i : i + 2] for i in range(0, 12, 2))
