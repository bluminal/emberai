"""LLDP neighbor model for Cisco SG-300."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class LLDPNeighbor(BaseModel):
    """An LLDP neighbor discovered by the switch.

    Populated from ``show lldp neighbors`` CLI output.
    """

    model_config = ConfigDict(strict=True)

    local_port: str
    remote_device: str
    remote_port: str
    capabilities: str
    remote_ip: str | None = None
