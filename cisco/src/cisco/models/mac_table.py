"""MAC address table model for Cisco SG-300."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, field_validator

from cisco.models.validators import MACAddress, normalize_mac


class MACEntry(BaseModel):
    """A MAC address table entry.

    Populated from ``show mac address-table`` CLI output.
    """

    model_config = ConfigDict(strict=True)

    mac: MACAddress
    vlan_id: int
    interface: str
    entry_type: str  # "dynamic" or "static"

    @field_validator("mac", mode="before")
    @classmethod
    def _normalize_mac(cls, v: str) -> str:
        return normalize_mac(v)
