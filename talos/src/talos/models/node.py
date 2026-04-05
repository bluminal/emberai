"""Node information model for Talos Linux."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict


class NodeInfo(BaseModel):
    """Information about a Talos Linux node.

    Populated from ``talosctl get machinestatus`` and ``talosctl get members``.
    """

    model_config = ConfigDict(strict=True)

    ip: str
    hostname: str
    role: Literal["controlplane", "worker"]
    machine_type: str
    talos_version: str
    kubernetes_version: str
    ready: bool
