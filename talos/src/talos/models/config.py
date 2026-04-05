"""Configuration models for Talos Linux."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict


class MachineConfig(BaseModel):
    """Machine configuration for a Talos node.

    Populated from ``talosctl get machineconfig`` with secrets redacted.
    """

    model_config = ConfigDict(strict=True)

    cluster_name: str
    endpoint: str
    install_disk: str
    network_config: dict[str, Any]
    patches: list[str]


class SecretsBundle(BaseModel):
    """Metadata about a Talos secrets bundle.

    Contains only metadata -- NEVER actual secret material (certificates,
    keys, tokens).  Populated from secrets bundle file header.
    """

    model_config = ConfigDict(strict=True)

    cluster_name: str
    generated_at: str
