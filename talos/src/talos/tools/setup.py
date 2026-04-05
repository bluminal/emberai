"""MCP tool for guided Talos cluster setup.

Wraps the three-phase orchestration from ``talos.agents.cluster_setup``
into a single write-gated MCP tool: ``talos__cluster__setup``.

The tool validates inputs, builds a plan, executes it step-by-step, and
returns a complete result with cluster summary or failure recovery guidance.
"""

from __future__ import annotations

import logging
from typing import Any

from talos.agents.cluster_setup import (
    build_setup_plan,
    execute_setup_plan,
    validate_cluster_inputs,
)
from talos.errors import ValidationError
from talos.safety import write_gate
from talos.server import mcp_server

logger = logging.getLogger(__name__)


@mcp_server.tool()
@write_gate("TALOS")
async def talos__cluster__setup(
    cluster_name: str,
    control_plane_ips: str,
    worker_ips: str = "",
    *,
    vip: str = "",
    install_disk: str = "/dev/sda",
    kubernetes_version: str = "",
    enable_kubespan: bool = False,
    output_dir: str = "",
    apply: bool = False,
) -> dict[str, Any]:
    """Run the full guided cluster setup workflow.

    Orchestrates the complete Talos Linux cluster provisioning process:

    1. **Gather** -- Validate all cluster parameters
    2. **Plan** -- Build ordered execution steps (gen secrets, gen config,
       apply to nodes, bootstrap etcd, health check, kubeconfig)
    3. **Execute** -- Run each step, verify success, report progress

    The workflow applies configs in insecure (maintenance) mode for
    first-time node setup, bootstraps etcd on the first control plane
    node, waits for cluster health, and retrieves the admin kubeconfig.

    **WARNING:** This is a write-heavy operation that provisions an
    entire cluster. Ensure all nodes are booted into Talos maintenance
    mode and reachable at the specified IPs before running.

    Parameters
    ----------
    cluster_name:
        Name of the Kubernetes cluster.
    control_plane_ips:
        Comma-separated list of control plane node IPs.
        Minimum 3 for HA.
    worker_ips:
        Comma-separated list of worker node IPs. Empty for
        control-plane-only clusters.
    vip:
        Virtual IP for the Kubernetes API endpoint. Must not
        collide with any node IP.
    install_disk:
        Target disk for Talos installation (default: ``/dev/sda``).
    kubernetes_version:
        Pin a specific Kubernetes version.
    enable_kubespan:
        Enable KubeSpan (WireGuard mesh) between nodes.
    output_dir:
        Directory for generated config files.
    apply:
        Must be ``True`` to execute the setup.
    """
    # Parse comma-separated IP lists
    cp_ips = [ip.strip() for ip in control_plane_ips.split(",") if ip.strip()]
    w_ips = [ip.strip() for ip in worker_ips.split(",") if ip.strip()] if worker_ips else []

    # Phase 1: Validate inputs
    try:
        plan = validate_cluster_inputs(
            cluster_name=cluster_name,
            control_plane_ips=cp_ips,
            worker_ips=w_ips,
            vip=vip or None,
            install_disk=install_disk,
            kubernetes_version=kubernetes_version,
            enable_kubespan=enable_kubespan,
        )
    except ValidationError as exc:
        return {
            "status": "error",
            "phase": "gather",
            "error": str(exc.message),
            "details": exc.details,
        }

    # Phase 2: Build plan
    steps = build_setup_plan(plan, output_dir=output_dir)

    logger.info(
        "Cluster setup plan: %d steps for '%s' (%d CP + %d worker nodes)",
        len(steps),
        cluster_name,
        len(cp_ips),
        len(w_ips),
        extra={"component": "cluster_setup"},
    )

    # Phase 3: Execute
    result = await execute_setup_plan(steps, plan)

    # Format response
    response: dict[str, Any] = {
        "status": result.status,
        "cluster_name": cluster_name,
        "steps_completed": len(result.completed_steps),
        "steps_total": len(steps),
    }

    if result.status == "success":
        response["cluster_summary"] = result.cluster_summary
        response["message"] = (
            f"Cluster '{cluster_name}' setup completed successfully. "
            f"All {len(steps)} steps passed."
        )
    else:
        response["failed_step"] = {
            "step_number": result.failed_step.step_number if result.failed_step else None,
            "description": result.failed_step.description if result.failed_step else None,
            "tool_name": result.failed_step.tool_name if result.failed_step else None,
            "error": result.failed_step.error if result.failed_step else None,
        }
        response["recovery_guidance"] = result.recovery_guidance
        response["completed_steps"] = [
            {
                "step_number": s.step_number,
                "description": s.description,
            }
            for s in result.completed_steps
        ]

    return response
