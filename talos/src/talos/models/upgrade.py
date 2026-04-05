"""Upgrade status model for Talos Linux."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class UpgradeStatus(BaseModel):
    """Status of a Talos OS upgrade on a node.

    Tracks upgrade progress during a rolling upgrade operation.
    """

    model_config = ConfigDict(strict=True)

    node: str
    current_version: str
    target_version: str
    stage: str
    progress: str
