"""Interface traffic counters model for Cisco SG-300."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class InterfaceCounters(BaseModel):
    """Interface traffic counters from ``show interfaces counters``.

    Tracks per-port byte/packet/error/discard counts for monitoring
    and anomaly detection.
    """

    model_config = ConfigDict(strict=True)

    port: str
    rx_bytes: int
    tx_bytes: int
    rx_packets: int
    tx_packets: int
    rx_errors: int
    tx_errors: int
    rx_discards: int
    tx_discards: int
