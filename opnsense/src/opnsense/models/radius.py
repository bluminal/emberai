# SPDX-License-Identifier: MIT
"""Pydantic models for OPNsense FreeRADIUS data.

Maps from OPNsense FreeRADIUS API responses for RADIUS clients and
users (MAC-based VLAN assignment via MAB) to normalized Python
representations.
"""

from pydantic import BaseModel, ConfigDict


class RadiusClient(BaseModel):
    """A FreeRADIUS client (NAS device allowed to send RADIUS requests).

    Returned by ``opnsense__services__get_radius_status()`` and
    ``opnsense__services__add_radius_client()``.

    API source: ``/api/freeradius/client/searchClient``
    """

    model_config = ConfigDict(populate_by_name=True)

    uuid: str = ""
    name: str = ""
    ip: str = ""
    enabled: str = "1"
    description: str = ""


class RadiusUser(BaseModel):
    """A FreeRADIUS user entry for MAC Authentication Bypass (MAB).

    Each user represents a MAC-to-VLAN mapping: the username and
    password are both the MAC address (lowercase, no separators),
    and the ``vlan`` field controls VLAN assignment.

    Returned by ``opnsense__services__list_radius_mac_vlans()`` and
    ``opnsense__services__add_radius_mac_vlan()``.

    API source: ``/api/freeradius/user/searchUser``
    """

    model_config = ConfigDict(populate_by_name=True)

    uuid: str = ""
    username: str = ""
    vlan: str = ""
    enabled: str = "1"
    description: str = ""
