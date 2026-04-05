"""Cluster health model for Talos Linux."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict

from talos.models.etcd import EtcdMember
from talos.models.node import NodeInfo


class ComponentStatus(BaseModel):
    """Health status of a single Kubernetes component."""

    model_config = ConfigDict(strict=True)

    healthy: bool
    message: str


class KubernetesComponents(BaseModel):
    """Health status of core Kubernetes components."""

    model_config = ConfigDict(strict=True)

    apiserver: ComponentStatus
    controller_manager: ComponentStatus
    scheduler: ComponentStatus
    etcd: ComponentStatus


class ClusterHealth(BaseModel):
    """Composite health report for a Talos Linux cluster.

    Aggregates node status, etcd membership, and Kubernetes component health
    from ``talosctl health``.
    """

    model_config = ConfigDict(strict=True)

    nodes: list[NodeInfo]
    etcd_members: list[EtcdMember]
    k8s_components: KubernetesComponents
    overall_status: Literal["healthy", "degraded", "critical"]
