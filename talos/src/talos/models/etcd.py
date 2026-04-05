"""Etcd member model for Talos Linux."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class EtcdMember(BaseModel):
    """An etcd cluster member.

    Populated from ``talosctl etcd members``.
    """

    model_config = ConfigDict(strict=True)

    id: str
    hostname: str
    peer_urls: list[str]
    client_urls: list[str]
    is_leader: bool
    db_size: int
    raft_term: int
    raft_index: int
