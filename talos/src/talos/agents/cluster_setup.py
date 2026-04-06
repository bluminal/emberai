"""Guided cluster setup orchestration for Talos Linux.

Composes the existing MCP tools into a multi-phase workflow that
walks the operator through provisioning a new Talos Kubernetes cluster:

    Phase 1 -- Gather:  Validate cluster parameters
    Phase 2 -- Plan:    Build an ordered list of execution steps
    Phase 3 -- Execute: Run each step, verify success, report progress

This module is NOT an MCP tool itself -- it is an internal helper that
the ``talos__cluster__setup`` MCP tool delegates to.  The three-phase
design allows callers to inspect the plan before committing to execution,
supporting the human-in-the-loop safety model.

Usage::

    plan = validate_cluster_inputs(
        cluster_name="prod",
        control_plane_ips=["10.0.0.11", "10.0.0.12", "10.0.0.13"],
        worker_ips=["10.0.0.21", "10.0.0.22"],
        vip="10.0.0.10",
    )
    steps = build_setup_plan(plan)
    result = await execute_setup_plan(steps, plan)
"""

from __future__ import annotations

import asyncio
import ipaddress
import logging
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from talos.api.talosctl_client import TalosCtlClient
from talos.errors import TalosCtlError, ValidationError

logger = logging.getLogger("talos.agents.cluster_setup")


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


class StepStatus(StrEnum):
    """Execution status of a single setup step."""

    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass
class ClusterSetupPlan:
    """Validated cluster setup parameters (Phase 1 output).

    All fields are validated before this dataclass is constructed.
    """

    cluster_name: str
    control_plane_ips: list[str]
    worker_ips: list[str]
    vip: str | None = None
    install_disk: str = "/dev/sda"
    kubernetes_version: str = ""
    enable_kubespan: bool = False
    endpoint: str = ""  # Computed: https://<vip_or_cp1>:6443

    def __post_init__(self) -> None:
        """Compute the Kubernetes API endpoint if not already set."""
        if not self.endpoint:
            target = self.vip if self.vip else self.control_plane_ips[0]
            self.endpoint = f"https://{target}:6443"


@dataclass
class SetupStep:
    """A single step in the cluster setup plan (Phase 2 output)."""

    step_number: int
    description: str
    tool_name: str
    args: dict[str, Any] = field(default_factory=dict)
    status: StepStatus = StepStatus.PENDING
    result: dict[str, Any] | None = None
    error: str | None = None


@dataclass
class SetupResult:
    """Final result of executing the setup plan (Phase 3 output)."""

    status: str  # "success", "partial", or "failed"
    completed_steps: list[SetupStep] = field(default_factory=list)
    failed_step: SetupStep | None = None
    cluster_summary: dict[str, Any] = field(default_factory=dict)
    recovery_guidance: str = ""


# ---------------------------------------------------------------------------
# Phase 1: Gather -- validate cluster inputs
# ---------------------------------------------------------------------------


def _validate_ip(ip: str) -> bool:
    """Return True if *ip* is a valid IPv4 or IPv6 address."""
    try:
        ipaddress.ip_address(ip)
        return True
    except ValueError:
        return False


def validate_cluster_inputs(
    cluster_name: str,
    control_plane_ips: list[str],
    worker_ips: list[str],
    *,
    vip: str | None = None,
    install_disk: str = "/dev/sda",
    kubernetes_version: str = "",
    enable_kubespan: bool = False,
) -> ClusterSetupPlan:
    """Validate cluster parameters and return a ``ClusterSetupPlan``.

    Raises :class:`ValidationError` for any invalid input:

    - Cluster name must be non-empty
    - At least 3 control plane IPs required for HA
    - All IPs must be valid format
    - VIP must not collide with any node IP
    - No duplicate IPs across all nodes

    Parameters
    ----------
    cluster_name:
        Name of the Kubernetes cluster.
    control_plane_ips:
        List of control plane node IP addresses.
    worker_ips:
        List of worker node IP addresses.
    vip:
        Optional Virtual IP for the Kubernetes API.
    install_disk:
        Target disk for Talos installation.
    kubernetes_version:
        Pin a specific Kubernetes version.
    enable_kubespan:
        Enable KubeSpan (WireGuard mesh) between nodes.
    """
    errors: list[str] = []

    # --- cluster name ---
    if not cluster_name or not cluster_name.strip():
        errors.append("cluster_name must be a non-empty string")

    # --- control plane node count ---
    if len(control_plane_ips) < 3:
        errors.append(
            f"At least 3 control plane IPs required for HA, got {len(control_plane_ips)}"
        )

    # --- validate all IP formats ---
    all_ips = list(control_plane_ips) + list(worker_ips)
    invalid_ips: list[str] = []
    for ip in all_ips:
        if not _validate_ip(ip):
            invalid_ips.append(ip)
    if invalid_ips:
        errors.append(f"Invalid IP address format: {', '.join(invalid_ips)}")

    # --- VIP validation ---
    if vip:
        if not _validate_ip(vip):
            errors.append(f"VIP is not a valid IP address: {vip}")
        elif vip in all_ips:
            errors.append(
                f"VIP {vip} must not be the same as any node IP. "
                f"VIP collides with: {vip}"
            )

    # --- duplicate detection ---
    seen: set[str] = set()
    duplicates: set[str] = set()
    for ip in all_ips:
        if ip in seen:
            duplicates.add(ip)
        seen.add(ip)
    if duplicates:
        errors.append(f"Duplicate IP addresses found: {', '.join(sorted(duplicates))}")

    # --- raise all at once ---
    if errors:
        raise ValidationError(
            "Cluster input validation failed:\n- " + "\n- ".join(errors),
            details={"errors": errors},
        )

    return ClusterSetupPlan(
        cluster_name=cluster_name.strip(),
        control_plane_ips=list(control_plane_ips),
        worker_ips=list(worker_ips),
        vip=vip,
        install_disk=install_disk,
        kubernetes_version=kubernetes_version,
        enable_kubespan=enable_kubespan,
    )


# ---------------------------------------------------------------------------
# Config file path constants (relative to a working dir)
# ---------------------------------------------------------------------------

_SECRETS_FILE = "secrets.yaml"
_OUTPUT_DIR = "."
_CP_CONFIG = "controlplane.yaml"
_WORKER_CONFIG = "worker.yaml"
_TALOSCONFIG = "talosconfig"


# ---------------------------------------------------------------------------
# Standalone config generation helper
# ---------------------------------------------------------------------------


def _is_result_success(result: dict[str, Any]) -> bool:
    """Return True if a tool result dict indicates success."""
    status = result.get("status", "")
    return status in ("success", "ok", "pass")


async def build_cluster_config(
    cluster_name: str,
    endpoint: str,
    control_plane_ips: list[str],
    worker_ips: list[str],
    *,
    vip: str | None = None,
    install_disk: str = "/dev/sda",
    secrets_file: str | None = None,
    kubernetes_version: str = "",
    enable_kubespan: bool = False,
    patches: list[str] | None = None,
    output_dir: str = "",
) -> dict[str, Any]:
    """Orchestrate config generation for a new Talos cluster.

    This is an internal helper (NOT an MCP tool) that composes the
    existing config tools into a single end-to-end workflow:

        1. Generate secrets bundle (if no ``secrets_file`` provided)
        2. Generate cluster configs from secrets
        3. Apply VIP patch to controlplane config (if ``vip`` specified)
        4. Apply KubeSpan patch to both configs (if ``enable_kubespan``)
        5. Apply any additional ``patches`` to both configs
        6. Validate all generated configs
        7. Return file paths and summary

    Parameters
    ----------
    cluster_name:
        Name of the Kubernetes cluster.
    endpoint:
        Control plane endpoint URL (e.g. ``https://10.0.0.10:6443``).
    control_plane_ips:
        Control plane node IP addresses.
    worker_ips:
        Worker node IP addresses.
    vip:
        Optional Virtual IP for the Kubernetes API load balancer.
    install_disk:
        Target disk for Talos installation (default: ``/dev/sda``).
    secrets_file:
        Path to an existing secrets bundle.  When ``None``, a new
        secrets bundle is generated.
    kubernetes_version:
        Pin a specific Kubernetes version.
    enable_kubespan:
        Enable KubeSpan (WireGuard mesh) between nodes.
    patches:
        Additional JSON patch strings to apply to **both**
        controlplane and worker configs.
    output_dir:
        Directory for generated config files.  Defaults to the
        current directory.

    Returns
    -------
    dict
        On success::

            {
                "status": "success",
                "secrets_file": "<path>",
                "controlplane_config": "<path>",
                "worker_config": "<path>",
                "talosconfig": "<path>",
                "cluster_name": "...",
                "endpoint": "...",
                "control_plane_ips": [...],
                "worker_ips": [...],
                "vip": "..." | None,
                "patches_applied": [...],
            }

        On failure::

            {
                "status": "error",
                "phase": "<phase name>",
                "error": "<message>",
                "details": { ... },
            }
    """
    from talos.tools.config import (
        talos__config__gen_config,
        talos__config__gen_secrets,
        talos__config__patch_machineconfig,
        talos__config__validate,
    )

    work_dir = output_dir or _OUTPUT_DIR
    secrets_path = (
        secrets_file
        if secrets_file
        else (f"{work_dir}/{_SECRETS_FILE}" if work_dir != "." else _SECRETS_FILE)
    )
    cp_config = f"{work_dir}/{_CP_CONFIG}" if work_dir != "." else _CP_CONFIG
    worker_config = f"{work_dir}/{_WORKER_CONFIG}" if work_dir != "." else _WORKER_CONFIG
    talosconfig = f"{work_dir}/{_TALOSCONFIG}" if work_dir != "." else _TALOSCONFIG

    patches_applied: list[str] = []

    # ------------------------------------------------------------------
    # Step 1: Generate secrets (if not provided)
    # ------------------------------------------------------------------
    if not secrets_file:
        logger.info(
            "Generating cluster secrets bundle",
            extra={"component": "build_cluster_config"},
        )
        result = await talos__config__gen_secrets(secrets_path, apply=True)
        if not _is_result_success(result):
            return {
                "status": "error",
                "phase": "gen_secrets",
                "error": result.get("error", "Failed to generate secrets"),
                "details": result,
            }

    # ------------------------------------------------------------------
    # Step 2: Generate cluster configs
    # ------------------------------------------------------------------
    logger.info(
        "Generating cluster configs for '%s'",
        cluster_name,
        extra={"component": "build_cluster_config"},
    )
    gen_kwargs: dict[str, Any] = {
        "cluster_name": cluster_name,
        "endpoint": endpoint,
        "secrets_file": secrets_path,
        "install_disk": install_disk,
        "output_dir": work_dir if work_dir != "." else "",
        "apply": True,
    }
    if kubernetes_version:
        gen_kwargs["kubernetes_version"] = kubernetes_version

    result = await talos__config__gen_config(**gen_kwargs)
    if not _is_result_success(result):
        return {
            "status": "error",
            "phase": "gen_config",
            "error": result.get("error", "Failed to generate configs"),
            "details": result,
        }

    # ------------------------------------------------------------------
    # Step 3: Apply VIP patch to controlplane config
    # ------------------------------------------------------------------
    if vip:
        vip_patch = (
            '[{"op": "add", "path": "/machine/network/interfaces/-", "value": '
            '{"interface": "eth0", "vip": {"ip": "' + vip + '"}}}]'
        )
        logger.info(
            "Applying VIP patch (%s) to controlplane config",
            vip,
            extra={"component": "build_cluster_config"},
        )
        result = await talos__config__patch_machineconfig(
            cp_config,
            vip_patch,
            output_file=cp_config,
            apply=True,
        )
        if not _is_result_success(result):
            return {
                "status": "error",
                "phase": "patch_vip",
                "error": result.get("error", "Failed to apply VIP patch"),
                "details": result,
            }
        patches_applied.append(f"VIP {vip}")

    # ------------------------------------------------------------------
    # Step 4: Apply KubeSpan patch to both configs
    # ------------------------------------------------------------------
    if enable_kubespan:
        kubespan_patch = (
            '[{"op": "add", "path": "/machine/network/kubespan", "value": '
            '{"enabled": true}}]'
        )
        for label, cfg_path in [
            ("controlplane", cp_config),
            ("worker", worker_config),
        ]:
            logger.info(
                "Applying KubeSpan patch to %s config",
                label,
                extra={"component": "build_cluster_config"},
            )
            result = await talos__config__patch_machineconfig(
                cfg_path,
                kubespan_patch,
                output_file=cfg_path,
                apply=True,
            )
            if not _is_result_success(result):
                return {
                    "status": "error",
                    "phase": f"patch_kubespan_{label}",
                    "error": result.get(
                        "error", f"Failed to apply KubeSpan patch to {label}"
                    ),
                    "details": result,
                }
        patches_applied.append("KubeSpan enabled")

    # ------------------------------------------------------------------
    # Step 5: Apply additional patches to both configs
    # ------------------------------------------------------------------
    if patches:
        for i, patch_str in enumerate(patches):
            for label, cfg_path in [
                ("controlplane", cp_config),
                ("worker", worker_config),
            ]:
                logger.info(
                    "Applying custom patch %d to %s config",
                    i + 1,
                    label,
                    extra={"component": "build_cluster_config"},
                )
                result = await talos__config__patch_machineconfig(
                    cfg_path,
                    patch_str,
                    output_file=cfg_path,
                    apply=True,
                )
                if not _is_result_success(result):
                    return {
                        "status": "error",
                        "phase": f"patch_custom_{i + 1}_{label}",
                        "error": result.get(
                            "error",
                            f"Failed to apply custom patch {i + 1} to {label}",
                        ),
                        "details": result,
                    }
            patches_applied.append(f"custom patch {i + 1}")

    # ------------------------------------------------------------------
    # Step 6: Validate all generated configs
    # ------------------------------------------------------------------
    configs_to_validate = [("controlplane", cp_config)]
    if worker_ips:
        configs_to_validate.append(("worker", worker_config))

    for label, cfg_path in configs_to_validate:
        logger.info(
            "Validating %s config",
            label,
            extra={"component": "build_cluster_config"},
        )
        result = await talos__config__validate(cfg_path, mode="metal")
        if not _is_result_success(result):
            return {
                "status": "error",
                "phase": f"validate_{label}",
                "error": result.get(
                    "errors", result.get("error", f"Validation failed for {label}")
                ),
                "details": result,
            }

    # ------------------------------------------------------------------
    # Step 7: Return summary
    # ------------------------------------------------------------------
    return {
        "status": "success",
        "secrets_file": secrets_path,
        "controlplane_config": cp_config,
        "worker_config": worker_config,
        "talosconfig": talosconfig,
        "cluster_name": cluster_name,
        "endpoint": endpoint,
        "control_plane_ips": control_plane_ips,
        "worker_ips": worker_ips,
        "vip": vip,
        "patches_applied": patches_applied,
    }


# ---------------------------------------------------------------------------
# Phase 2: Plan -- build the ordered execution steps
# ---------------------------------------------------------------------------


def build_setup_plan(
    plan: ClusterSetupPlan,
    *,
    output_dir: str = "",
) -> list[SetupStep]:
    """Generate the ordered list of execution steps for a cluster setup.

    Steps:
        1. Generate secrets bundle
        2. Generate cluster configs (with VIP patch if specified)
        3. Validate controlplane config
        4. Validate worker config
        5..N. Apply config to each CP node (insecure)
        N+1..M. Apply config to each worker node (insecure)
        M+1. Set talosctl endpoints to CP IPs
        M+2. Merge talosconfig
        M+3. Bootstrap etcd on CP1
        M+4. Wait for cluster health
        M+5. Retrieve kubeconfig

    Parameters
    ----------
    plan:
        Validated :class:`ClusterSetupPlan`.
    output_dir:
        Directory for generated config files. Defaults to current dir.
    """
    work_dir = output_dir or _OUTPUT_DIR
    secrets_path = f"{work_dir}/{_SECRETS_FILE}" if work_dir != "." else _SECRETS_FILE
    cp_config = f"{work_dir}/{_CP_CONFIG}" if work_dir != "." else _CP_CONFIG
    worker_config = f"{work_dir}/{_WORKER_CONFIG}" if work_dir != "." else _WORKER_CONFIG
    talosconfig = f"{work_dir}/{_TALOSCONFIG}" if work_dir != "." else _TALOSCONFIG

    steps: list[SetupStep] = []
    step_num = 0

    # Step 1: Generate secrets
    step_num += 1
    steps.append(SetupStep(
        step_number=step_num,
        description="Generate cluster secrets bundle",
        tool_name="talos__config__gen_secrets",
        args={
            "output_path": secrets_path,
            "apply": True,
        },
    ))

    # Step 2: Generate cluster configs
    step_num += 1
    gen_config_args: dict[str, Any] = {
        "cluster_name": plan.cluster_name,
        "endpoint": plan.endpoint,
        "secrets_file": secrets_path,
        "install_disk": plan.install_disk,
        "output_dir": work_dir if work_dir != "." else "",
        "apply": True,
    }
    if plan.kubernetes_version:
        gen_config_args["kubernetes_version"] = plan.kubernetes_version

    steps.append(SetupStep(
        step_number=step_num,
        description=f"Generate cluster configs for '{plan.cluster_name}'",
        tool_name="talos__config__gen_config",
        args=gen_config_args,
    ))

    # Step 2.5: Patch controlplane config with VIP (if specified)
    if plan.vip:
        step_num += 1
        vip_patch = (
            '[{"op": "add", "path": "/machine/network/interfaces/-", "value": '
            '{"interface": "eth0", "vip": {"ip": "' + plan.vip + '"}}}]'
        )
        steps.append(SetupStep(
            step_number=step_num,
            description=f"Patch controlplane config with VIP {plan.vip}",
            tool_name="talos__config__patch_machineconfig",
            args={
                "config_file": cp_config,
                "patches": vip_patch,
                "output_file": cp_config,
                "apply": True,
            },
        ))

    # Step 2.75: Patch with KubeSpan (if enabled)
    if plan.enable_kubespan:
        step_num += 1
        kubespan_patch = (
            '[{"op": "add", "path": "/machine/network/kubespan", "value": '
            '{"enabled": true}}]'
        )
        # Patch both controlplane and worker configs
        steps.append(SetupStep(
            step_number=step_num,
            description="Enable KubeSpan on controlplane config",
            tool_name="talos__config__patch_machineconfig",
            args={
                "config_file": cp_config,
                "patches": kubespan_patch,
                "output_file": cp_config,
                "apply": True,
            },
        ))
        step_num += 1
        steps.append(SetupStep(
            step_number=step_num,
            description="Enable KubeSpan on worker config",
            tool_name="talos__config__patch_machineconfig",
            args={
                "config_file": worker_config,
                "patches": kubespan_patch,
                "output_file": worker_config,
                "apply": True,
            },
        ))

    # Step 3: Validate controlplane config
    step_num += 1
    steps.append(SetupStep(
        step_number=step_num,
        description="Validate controlplane configuration",
        tool_name="talos__config__validate",
        args={
            "config_file": cp_config,
            "mode": "metal",
        },
    ))

    # Step 4: Validate worker config (only if there are workers)
    if plan.worker_ips:
        step_num += 1
        steps.append(SetupStep(
            step_number=step_num,
            description="Validate worker configuration",
            tool_name="talos__config__validate",
            args={
                "config_file": worker_config,
                "mode": "metal",
            },
        ))

    # Steps 5..N: Apply config to each control plane node (insecure)
    for i, cp_ip in enumerate(plan.control_plane_ips, 1):
        step_num += 1
        steps.append(SetupStep(
            step_number=step_num,
            description=f"Apply controlplane config to CP{i} ({cp_ip})",
            tool_name="talos__cluster__apply_config",
            args={
                "node": cp_ip,
                "config_file": cp_config,
                "insecure": True,
                "apply": True,
            },
        ))

    # Steps N+1..M: Apply config to each worker node (insecure)
    for i, worker_ip in enumerate(plan.worker_ips, 1):
        step_num += 1
        steps.append(SetupStep(
            step_number=step_num,
            description=f"Apply worker config to Worker{i} ({worker_ip})",
            tool_name="talos__cluster__apply_config",
            args={
                "node": worker_ip,
                "config_file": worker_config,
                "insecure": True,
                "apply": True,
            },
        ))

    # Step M+1: Set talosctl endpoints to CP IPs
    step_num += 1
    steps.append(SetupStep(
        step_number=step_num,
        description="Set talosctl endpoints to control plane IPs",
        tool_name="talos__cluster__set_endpoints",
        args={
            "endpoints": " ".join(plan.control_plane_ips),
            "apply": True,
        },
    ))

    # Step M+2: Merge talosconfig
    step_num += 1
    steps.append(SetupStep(
        step_number=step_num,
        description="Merge generated talosconfig into local config",
        tool_name="talos__cluster__merge_talosconfig",
        args={
            "talosconfig_path": talosconfig,
            "apply": True,
        },
    ))

    # Step M+3: Bootstrap etcd on CP1
    step_num += 1
    steps.append(SetupStep(
        step_number=step_num,
        description=f"Bootstrap etcd on first control plane ({plan.control_plane_ips[0]})",
        tool_name="talos__cluster__bootstrap",
        args={
            "node": plan.control_plane_ips[0],
            "etcd_members_count": 0,
            "apply": True,
        },
    ))

    # Step M+4: Wait for cluster health
    step_num += 1
    steps.append(SetupStep(
        step_number=step_num,
        description="Wait for cluster to become healthy",
        tool_name="talos__cluster__health",
        args={
            "node": plan.control_plane_ips[0],
            "wait_timeout": "5m",
        },
    ))

    # Step M+5: Retrieve kubeconfig
    step_num += 1
    steps.append(SetupStep(
        step_number=step_num,
        description="Retrieve admin kubeconfig",
        tool_name="talos__cluster__kubeconfig",
        args={
            "node": plan.control_plane_ips[0],
        },
    ))

    return steps


# ---------------------------------------------------------------------------
# Phase 3: Execute -- run the setup plan step by step
# ---------------------------------------------------------------------------

# Maps tool names to the actual async functions in the tools modules.
# Populated lazily to avoid circular imports at module load time.
_TOOL_REGISTRY: dict[str, Any] | None = None


def _get_tool_registry() -> dict[str, Any]:
    """Lazily import and cache the tool function registry."""
    global _TOOL_REGISTRY
    if _TOOL_REGISTRY is not None:
        return _TOOL_REGISTRY

    from talos.tools.cluster import (
        talos__cluster__apply_config,
        talos__cluster__bootstrap,
        talos__cluster__health,
        talos__cluster__kubeconfig,
        talos__cluster__merge_talosconfig,
        talos__cluster__set_endpoints,
    )
    from talos.tools.config import (
        talos__config__gen_config,
        talos__config__gen_secrets,
        talos__config__patch_machineconfig,
        talos__config__validate,
    )

    _TOOL_REGISTRY = {
        "talos__config__gen_secrets": talos__config__gen_secrets,
        "talos__config__gen_config": talos__config__gen_config,
        "talos__config__patch_machineconfig": talos__config__patch_machineconfig,
        "talos__config__validate": talos__config__validate,
        "talos__cluster__apply_config": talos__cluster__apply_config,
        "talos__cluster__bootstrap": talos__cluster__bootstrap,
        "talos__cluster__health": talos__cluster__health,
        "talos__cluster__kubeconfig": talos__cluster__kubeconfig,
        "talos__cluster__set_endpoints": talos__cluster__set_endpoints,
        "talos__cluster__merge_talosconfig": talos__cluster__merge_talosconfig,
    }
    return _TOOL_REGISTRY


def _recovery_guidance_for_step(step: SetupStep, plan: ClusterSetupPlan) -> str:
    """Return operator-facing recovery guidance based on which step failed."""
    tool = step.tool_name

    if tool == "talos__config__gen_secrets":
        return (
            "Secret generation failed. Check filesystem permissions for the "
            "output path and ensure talosctl is installed."
        )
    if tool == "talos__config__gen_config":
        return (
            "Config generation failed. Verify the cluster name and endpoint are valid. "
            "Check that the secrets file was generated in the previous step."
        )
    if tool == "talos__config__validate":
        return (
            "Config validation failed. The generated config may have incompatible "
            "patches. Review the error output and regenerate configs."
        )
    if tool == "talos__config__patch_machineconfig":
        return (
            "Config patching failed. Verify the patch JSON is valid and the "
            "config file exists from the gen_config step."
        )
    if tool == "talos__cluster__apply_config":
        node = step.args.get("node", "unknown")
        return (
            f"Config apply failed for node {node}. Verify the node is booted into "
            f"Talos maintenance mode and is reachable at that IP address. "
            f"Previously configured nodes do not need to be re-applied."
        )
    if tool == "talos__cluster__bootstrap":
        return (
            "etcd bootstrap failed. Verify the first control plane node has "
            "accepted its config and is running. Wait 30-60 seconds after "
            "apply-config before bootstrapping. You can retry this step safely "
            "if etcd was not partially initialized."
        )
    if tool == "talos__cluster__health":
        return (
            "Cluster health check failed or timed out. This may be transient -- "
            "Kubernetes components can take several minutes to start. Try running "
            "talos__cluster__health manually with a longer timeout."
        )
    if tool == "talos__cluster__kubeconfig":
        return (
            "Kubeconfig retrieval failed. The cluster may still be initializing. "
            "Wait for the health check to pass, then retry kubeconfig retrieval."
        )
    return "Review the error output and retry the failed step manually."


async def _execute_step(
    step: SetupStep,
    tool_registry: dict[str, Any],
) -> dict[str, Any]:
    """Execute a single setup step and return the tool result dict."""
    tool_fn = tool_registry.get(step.tool_name)
    if tool_fn is None:
        raise ValueError(f"Unknown tool: {step.tool_name}")

    # Call the tool function with the step's arguments
    result: dict[str, Any] = await tool_fn(**step.args)
    return result


def _is_step_success(result: dict[str, Any]) -> bool:
    """Determine if a step result indicates success."""
    status = result.get("status", "")
    return status in ("success", "ok", "pass")


async def _poll_etcd_members(
    client: TalosCtlClient,
    node: str,
    expected_count: int,
    *,
    timeout: float = 180.0,
    poll_interval: float = 10.0,
) -> dict[str, Any]:
    """Poll etcd members until all control plane nodes appear.

    Returns a dict with the final member list, or timeout information.
    """
    deadline = asyncio.get_event_loop().time() + timeout
    last_count = 0

    while asyncio.get_event_loop().time() < deadline:
        try:
            result = await client.run(
                ["etcd", "members"],
                nodes=node,
                json_output=True,
                use_cache=False,
                timeout=15.0,
            )
            # Count members from the parsed output
            parsed = result.parsed
            if isinstance(parsed, dict):
                messages = parsed.get("messages", [])
                members: list[Any] = []
                for msg in messages:
                    members.extend(msg.get("members", []))
                last_count = len(members)
            elif isinstance(parsed, list):
                last_count = len(parsed)

            logger.info(
                "etcd members: %d/%d",
                last_count,
                expected_count,
                extra={"component": "cluster_setup"},
            )

            if last_count >= expected_count:
                return {
                    "status": "ok",
                    "member_count": last_count,
                    "expected_count": expected_count,
                }

        except TalosCtlError:
            # etcd may not be ready yet; keep polling
            logger.debug(
                "etcd members query failed, retrying...",
                extra={"component": "cluster_setup"},
            )

        await asyncio.sleep(poll_interval)

    return {
        "status": "timeout",
        "member_count": last_count,
        "expected_count": expected_count,
        "message": (
            f"etcd member count ({last_count}) did not reach expected "
            f"({expected_count}) within {timeout}s. The cluster may still "
            f"be converging -- check health manually."
        ),
    }


async def execute_setup_plan(
    steps: list[SetupStep],
    plan: ClusterSetupPlan,
    *,
    client: TalosCtlClient | None = None,
    tool_registry: dict[str, Any] | None = None,
) -> SetupResult:
    """Execute the setup plan step-by-step and return the result.

    On failure, execution stops immediately. The result includes
    which steps completed, which step failed, and recovery guidance.

    After bootstrap, polls etcd members until all CPs appear (timeout 3 min).

    Parameters
    ----------
    steps:
        Ordered list of :class:`SetupStep` from :func:`build_setup_plan`.
    plan:
        The validated :class:`ClusterSetupPlan`.
    client:
        Optional TalosCtlClient for etcd polling. Created if not provided.
    tool_registry:
        Optional tool function registry. Loaded lazily if not provided.
    """
    registry = tool_registry or _get_tool_registry()
    talos_client = client or TalosCtlClient()
    completed: list[SetupStep] = []

    for step in steps:
        logger.info(
            "Step %d/%d: %s",
            step.step_number,
            len(steps),
            step.description,
            extra={"component": "cluster_setup"},
        )

        step.status = StepStatus.RUNNING

        try:
            result = await _execute_step(step, registry)
        except Exception as exc:
            step.status = StepStatus.FAILED
            step.error = str(exc)
            return SetupResult(
                status="failed",
                completed_steps=completed,
                failed_step=step,
                recovery_guidance=_recovery_guidance_for_step(step, plan),
            )

        step.result = result

        if not _is_step_success(result):
            step.status = StepStatus.FAILED
            step.error = result.get("error", result.get("errors", "Unknown error"))
            return SetupResult(
                status="failed",
                completed_steps=completed,
                failed_step=step,
                recovery_guidance=_recovery_guidance_for_step(step, plan),
            )

        step.status = StepStatus.SUCCESS
        completed.append(step)

        logger.info(
            "Step %d completed: %s",
            step.step_number,
            step.description,
            extra={"component": "cluster_setup"},
        )

        # Post-bootstrap: poll for etcd member convergence
        if step.tool_name == "talos__cluster__bootstrap":
            logger.info(
                "Polling for etcd member convergence (%d expected)...",
                len(plan.control_plane_ips),
                extra={"component": "cluster_setup"},
            )
            etcd_result = await _poll_etcd_members(
                talos_client,
                node=plan.control_plane_ips[0],
                expected_count=len(plan.control_plane_ips),
            )
            if etcd_result["status"] == "timeout":
                logger.warning(
                    "etcd convergence timeout: %s",
                    etcd_result.get("message", ""),
                    extra={"component": "cluster_setup"},
                )

    # Build cluster summary
    total_nodes = len(plan.control_plane_ips) + len(plan.worker_ips)
    cluster_summary: dict[str, Any] = {
        "cluster_name": plan.cluster_name,
        "endpoint": plan.endpoint,
        "control_plane_nodes": plan.control_plane_ips,
        "worker_nodes": plan.worker_ips,
        "total_nodes": total_nodes,
        "vip": plan.vip,
        "steps_completed": len(completed),
        "steps_total": len(steps),
    }

    # Extract kubeconfig from the last step's result if available
    kubeconfig_step = next(
        (s for s in completed if s.tool_name == "talos__cluster__kubeconfig"),
        None,
    )
    if kubeconfig_step and kubeconfig_step.result:
        if "kubeconfig" in kubeconfig_step.result:
            cluster_summary["kubeconfig_retrieved"] = True
        elif "output_path" in kubeconfig_step.result:
            cluster_summary["kubeconfig_path"] = kubeconfig_step.result["output_path"]

    return SetupResult(
        status="success",
        completed_steps=completed,
        cluster_summary=cluster_summary,
    )
