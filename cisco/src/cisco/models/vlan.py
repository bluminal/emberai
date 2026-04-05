"""VLAN model for Cisco SG-300."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class VLAN(BaseModel):
    """A VLAN configured on the switch.

    Populated from ``show vlan`` CLI output.
    """

    model_config = ConfigDict(strict=True)

    id: int
    name: str
    ports: list[str]
    tagged_ports: list[str]
