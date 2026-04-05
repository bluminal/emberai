"""System information model for Cisco SG-300."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, field_validator

from cisco.models.validators import MACAddress, normalize_mac


class SwitchInfo(BaseModel):
    """System information for a Cisco SG-300 switch.

    Populated from ``show version`` and optionally ``show running-config``
    (for hostname extraction).
    """

    model_config = ConfigDict(strict=True)

    hostname: str
    model: str
    firmware_version: str
    serial_number: str
    uptime_seconds: int
    mac_address: MACAddress

    @field_validator("mac_address", mode="before")
    @classmethod
    def _normalize_mac(cls, v: str) -> str:
        return normalize_mac(v)
