"""Talos resource model."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict


class TalosResource(BaseModel):
    """A generic Talos resource.

    Populated from ``talosctl get`` commands for arbitrary resource types.
    """

    model_config = ConfigDict(strict=True)

    namespace: str
    type: str
    id: str
    spec: dict[str, Any]
    metadata: dict[str, Any]
