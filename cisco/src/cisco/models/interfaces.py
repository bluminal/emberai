"""Port and interface models for Cisco SG-300."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class Port(BaseModel):
    """A physical or logical port on the switch.

    Populated from ``show interfaces status`` CLI output.
    """

    model_config = ConfigDict(strict=True)

    id: str
    name: str
    status: str  # "up", "down", "disabled"
    speed: str  # "1000M", "100M", "10M", "auto", ""
    duplex: str  # "full", "half", "auto", ""
    vlan_id: int | None = None
    mode: str  # "access", "trunk", "general", "hybrid"
    description: str = ""


class PortDetail(Port):
    """Extended port information including trunk membership.

    Populated from ``show interfaces switchport <port>`` CLI output.
    Extends :class:`Port` with VLAN trunk details.
    """

    trunk_allowed_vlans: list[int] = []
    native_vlan: int | None = None
