"""Service model for Talos Linux."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class Service(BaseModel):
    """A system service running on a Talos node.

    Populated from ``talosctl services``.
    """

    model_config = ConfigDict(strict=True)

    id: str
    state: str
    health: str
    events_count: int
