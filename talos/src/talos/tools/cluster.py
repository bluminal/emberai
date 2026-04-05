"""MCP tools for Talos cluster lifecycle operations.

Provides cluster bootstrap, config application, kubeconfig retrieval,
health checks, version info, endpoint configuration, and talosconfig
merging.  Write operations use the safety gate pattern (env var +
--apply flag).

All tools communicate via the ``TalosCtlClient`` async subprocess
wrapper around ``talosctl``.
"""

from __future__ import annotations

import logging
from typing import Any

from talos.api.talosctl_client import TalosCtlClient
from talos.errors import TalosCtlError, ValidationError
from talos.safety import bootstrap_gate, write_gate
from talos.server import mcp_server

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Shared client helper
# ---------------------------------------------------------------------------


def _get_client() -> TalosCtlClient:
    """Return a TalosCtlClient with default configuration."""
    return TalosCtlClient()


# ---------------------------------------------------------------------------
# 1. apply-config
# ---------------------------------------------------------------------------


@mcp_server.tool()
@write_gate("TALOS")
async def talos__cluster__apply_config(
    node: str,
    config_file: str,
    *,
    insecure: bool = False,
    mode: str = "auto",
    dry_run: bool = False,
    apply: bool = False,
) -> dict[str, Any]:
    """Apply a machine configuration to a Talos node.

    Validates the config file first via ``talosctl validate``, then
    executes ``talosctl apply-config``.  Use ``insecure=True`` for
    first-time apply to unconfigured nodes (before mTLS is established).

    Parameters
    ----------
    node:
        Target node IP or hostname.
    config_file:
        Path to the machine configuration YAML file.
    insecure:
        Use insecure (maintenance) mode for first-time apply.
    mode:
        Apply mode: ``"auto"``, ``"interactive"``, ``"no-reboot"``,
        ``"reboot"``, ``"staged"``.
    dry_run:
        If ``True``, validate only -- do not apply.
    apply:
        Must be ``True`` to execute the write operation.
    """
    client = _get_client()

    # Validate the config file first
    try:
        validate_args = ["validate", "--file", config_file]
        if mode in ("controlplane", "worker"):
            validate_args.extend(["--mode", mode])
        await client.run(validate_args, json_output=False, use_cache=False)
    except TalosCtlError as exc:
        return {
            "status": "error",
            "operation": "validate",
            "node": node,
            "config_file": config_file,
            "error": f"Config validation failed: {exc.message}",
            "stderr": exc.stderr or "",
        }

    if dry_run:
        return {
            "status": "ok",
            "operation": "dry_run",
            "node": node,
            "config_file": config_file,
            "message": "Config validation passed. Dry run -- no changes applied.",
        }

    # Build apply-config command
    args = ["apply-config", "--file", config_file]

    valid_modes = ("auto", "interactive", "no-reboot", "reboot", "staged")
    if mode not in valid_modes:
        return {
            "status": "error",
            "operation": "apply_config",
            "node": node,
            "error": f"Invalid mode: {mode!r}. Must be one of: {', '.join(valid_modes)}",
        }

    if mode != "auto":
        args.extend(["--mode", mode])

    # Execute apply
    try:
        if insecure:
            result = await client.run_insecure(
                args, nodes=node, json_output=False, timeout=60.0
            )
        else:
            result = await client.run(
                args, nodes=node, json_output=False, use_cache=False, timeout=60.0
            )

        await client.flush_cache()

        return {
            "status": "ok",
            "operation": "apply_config",
            "node": node,
            "config_file": config_file,
            "insecure": insecure,
            "mode": mode,
            "message": result.stdout.strip() or "Configuration applied successfully.",
        }
    except TalosCtlError as exc:
        return {
            "status": "error",
            "operation": "apply_config",
            "node": node,
            "config_file": config_file,
            "error": exc.message,
            "stderr": exc.stderr or "",
        }


# ---------------------------------------------------------------------------
# 2. bootstrap
# ---------------------------------------------------------------------------


@mcp_server.tool()
@bootstrap_gate
@write_gate("TALOS")
async def talos__cluster__bootstrap(
    node: str,
    *,
    etcd_members_count: int = 0,
    apply: bool = False,
) -> dict[str, Any]:
    """Bootstrap etcd on the first control plane node.

    **WARNING: This is a ONE-TIME operation.** Running bootstrap on a
    cluster that already has etcd members will corrupt the cluster and
    cause data loss.  The ``bootstrap_gate`` blocks execution if
    ``etcd_members_count > 0``.

    The caller MUST query ``talosctl etcd members`` beforehand and pass
    the result count as ``etcd_members_count``.

    Parameters
    ----------
    node:
        The first control plane node to bootstrap etcd on.
    etcd_members_count:
        Number of existing etcd members (0 = safe to bootstrap).
    apply:
        Must be ``True`` to execute the write operation.
    """
    client = _get_client()

    try:
        result = await client.run(
            ["bootstrap"], nodes=node, json_output=False, use_cache=False, timeout=120.0
        )

        await client.flush_cache()

        return {
            "status": "ok",
            "operation": "bootstrap",
            "node": node,
            "message": (
                result.stdout.strip()
                or "etcd bootstrap initiated successfully."
            ),
            "warning": (
                "Bootstrap is a ONE-TIME operation. Do NOT run this again. "
                "Monitor cluster health with talos__cluster__health."
            ),
        }
    except TalosCtlError as exc:
        return {
            "status": "error",
            "operation": "bootstrap",
            "node": node,
            "error": exc.message,
            "stderr": exc.stderr or "",
        }


# ---------------------------------------------------------------------------
# 3. kubeconfig
# ---------------------------------------------------------------------------


@mcp_server.tool()
async def talos__cluster__kubeconfig(
    *,
    node: str = "",
    output_path: str = "",
) -> dict[str, Any]:
    """Retrieve the admin kubeconfig from the Talos cluster.

    If ``output_path`` is provided, the kubeconfig is written to that
    file.  Otherwise the kubeconfig content is returned in the response.

    Parameters
    ----------
    node:
        Target node to retrieve kubeconfig from.  Uses default node
        if empty.
    output_path:
        File path to write the kubeconfig to.  If empty, returns
        the content directly.
    """
    client = _get_client()

    args: list[str] = ["kubeconfig"]
    if output_path:
        args.append(output_path)
    else:
        args.append("-")  # stdout

    try:
        result = await client.run(
            args,
            nodes=node if node else None,
            json_output=False,
            timeout=30.0,
        )

        if output_path:
            return {
                "status": "ok",
                "operation": "kubeconfig",
                "output_path": output_path,
                "message": f"Kubeconfig written to {output_path}",
            }
        else:
            return {
                "status": "ok",
                "operation": "kubeconfig",
                "kubeconfig": result.stdout,
                "message": "Kubeconfig retrieved successfully.",
            }
    except TalosCtlError as exc:
        return {
            "status": "error",
            "operation": "kubeconfig",
            "error": exc.message,
            "stderr": exc.stderr or "",
        }


# ---------------------------------------------------------------------------
# 4. health
# ---------------------------------------------------------------------------


@mcp_server.tool()
async def talos__cluster__health(
    *,
    node: str = "",
    wait_timeout: str = "",
) -> dict[str, Any]:
    """Run a cluster health check and return a severity-tiered report.

    Executes ``talosctl health`` and categorizes results into
    CRITICAL, WARNING, and OK tiers.

    Parameters
    ----------
    node:
        Target node to check health from.  Uses default if empty.
    wait_timeout:
        Timeout to wait for cluster to be healthy (e.g. ``"5m"``).
        If empty, uses talosctl default.
    """
    client = _get_client()

    args: list[str] = ["health"]
    if wait_timeout:
        args.extend(["--wait-timeout", wait_timeout])

    try:
        result = await client.run(
            args,
            nodes=node if node else None,
            json_output=True,
            timeout=300.0,
        )

        parsed = result.parsed
        if isinstance(parsed, dict):
            return _build_health_report(parsed)
        else:
            # Fallback for text output
            return {
                "status": "ok",
                "operation": "health",
                "severity": "OK",
                "raw_output": result.stdout.strip(),
                "message": "Cluster health check completed.",
            }
    except TalosCtlError as exc:
        # A non-zero exit from health often means the cluster is unhealthy
        return {
            "status": "error",
            "operation": "health",
            "severity": "CRITICAL",
            "error": exc.message,
            "stderr": exc.stderr or "",
            "message": "Cluster health check failed -- cluster may be unhealthy.",
        }


def _build_health_report(data: dict[str, Any]) -> dict[str, Any]:
    """Build a severity-tiered health report from parsed health JSON."""
    cluster_info = data.get("cluster_info", {})
    messages = data.get("messages", [])

    nodes_healthy = cluster_info.get("nodes_healthy", 0)
    nodes_total = cluster_info.get("nodes_total", 0)
    etcd_healthy = cluster_info.get("etcd_healthy", False)
    k8s_healthy = cluster_info.get("kubernetes_healthy", False)
    all_services = cluster_info.get("all_services_healthy", False)

    # Determine severity
    if nodes_healthy == 0 or not etcd_healthy:
        severity = "CRITICAL"
    elif nodes_healthy < nodes_total or not k8s_healthy or not all_services:
        severity = "WARNING"
    else:
        severity = "OK"

    # Collect node-level details
    node_reports: list[dict[str, Any]] = []
    for msg in messages:
        meta = msg.get("metadata", {})
        health = msg.get("health", {})
        hostname = meta.get("hostname", "unknown")
        error = meta.get("error", "")
        ready = health.get("ready", False)
        unmet = health.get("unmet_conditions", [])

        node_report: dict[str, Any] = {
            "hostname": hostname,
            "ready": ready,
        }
        if error:
            node_report["error"] = error
        if unmet:
            node_report["unmet_conditions"] = unmet

        node_reports.append(node_report)

    return {
        "status": "ok",
        "operation": "health",
        "severity": severity,
        "cluster": {
            "nodes_healthy": nodes_healthy,
            "nodes_total": nodes_total,
            "etcd_healthy": etcd_healthy,
            "kubernetes_healthy": k8s_healthy,
            "all_services_healthy": all_services,
        },
        "nodes": node_reports,
        "message": (
            f"Cluster health: {severity} -- "
            f"{nodes_healthy}/{nodes_total} nodes healthy, "
            f"etcd={'healthy' if etcd_healthy else 'UNHEALTHY'}, "
            f"k8s={'healthy' if k8s_healthy else 'UNHEALTHY'}"
        ),
    }


# ---------------------------------------------------------------------------
# 5. get_version
# ---------------------------------------------------------------------------


@mcp_server.tool()
async def talos__cluster__get_version(
    *,
    node: str = "",
) -> dict[str, Any]:
    """Get talosctl client and server version information.

    Executes ``talosctl version -o json`` and returns both client
    and server version details.

    Parameters
    ----------
    node:
        Target node to query.  Uses default if empty.
    """
    client = _get_client()

    try:
        result = await client.run(
            ["version"],
            nodes=node if node else None,
            json_output=True,
            timeout=15.0,
        )

        parsed = result.parsed
        if isinstance(parsed, dict):
            return {
                "status": "ok",
                "operation": "version",
                "client_version": parsed.get("client_version", {}),
                "server_versions": [
                    {
                        "hostname": msg.get("metadata", {}).get("hostname", "unknown"),
                        "version": msg.get("version", {}),
                    }
                    for msg in parsed.get("messages", [])
                ],
            }
        else:
            return {
                "status": "ok",
                "operation": "version",
                "raw_output": result.stdout.strip(),
            }
    except TalosCtlError as exc:
        return {
            "status": "error",
            "operation": "version",
            "error": exc.message,
            "stderr": exc.stderr or "",
        }


# ---------------------------------------------------------------------------
# 6. set_endpoints
# ---------------------------------------------------------------------------


@mcp_server.tool()
@write_gate("TALOS")
async def talos__cluster__set_endpoints(
    endpoints: str,
    *,
    apply: bool = False,
) -> dict[str, Any]:
    """Set the talosctl config endpoints.

    Updates the talosconfig to point at the specified endpoints.
    Endpoints should be control plane node IPs.

    **Warning:** Do not use a VIP (Virtual IP) as an endpoint.
    VIPs are for Kubernetes API access; talosctl needs direct
    node IPs for gRPC communication.

    Parameters
    ----------
    endpoints:
        Space-separated list of control plane node IPs
        (e.g. ``"192.168.30.10 192.168.30.11 192.168.30.12"``).
    apply:
        Must be ``True`` to execute the write operation.
    """
    if not endpoints.strip():
        return {
            "status": "error",
            "operation": "set_endpoints",
            "error": "No endpoints provided. Supply space-separated IP addresses.",
        }

    client = _get_client()

    # Build command: talosctl config endpoint <ip1> <ip2> ...
    endpoint_list = endpoints.strip().split()
    args = ["config", "endpoint"] + endpoint_list

    try:
        result = await client.run(
            args, json_output=False, use_cache=False, timeout=10.0
        )

        # Warn about VIP usage
        warnings: list[str] = []
        for ep in endpoint_list:
            if "vip" in ep.lower():
                warnings.append(
                    f"Endpoint {ep!r} may be a VIP. Use direct node IPs for "
                    f"talosctl endpoints, not VIPs. VIPs are for Kubernetes "
                    f"API access only."
                )

        response: dict[str, Any] = {
            "status": "ok",
            "operation": "set_endpoints",
            "endpoints": endpoint_list,
            "message": (
                result.stdout.strip()
                or f"Endpoints set to: {', '.join(endpoint_list)}"
            ),
        }
        if warnings:
            response["warnings"] = warnings
            response["warning"] = (
                "Do NOT use VIP addresses as talosctl endpoints. "
                "VIPs are for Kubernetes API access. Use direct "
                "control plane node IPs instead."
            )

        return response
    except TalosCtlError as exc:
        return {
            "status": "error",
            "operation": "set_endpoints",
            "error": exc.message,
            "stderr": exc.stderr or "",
        }


# ---------------------------------------------------------------------------
# 7. merge_talosconfig
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# 8. cluster_status (read-only unified overview)
# ---------------------------------------------------------------------------


@mcp_server.tool()
async def talos__cluster__status(
    *,
    node: str = "",
) -> dict[str, Any]:
    """Get a unified cluster status overview in a single call.

    Combines health, version, and node membership data into one
    structured report.  Each sub-call is independent -- if one fails,
    the remaining results are still returned with the failure noted.

    The report includes:
    - **Overall severity**: OK, WARNING, or CRITICAL
    - **Node inventory**: count by role (control plane vs worker),
      per-node hostname, IP, role, and ready status
    - **Version info**: Talos and Kubernetes versions
    - **etcd health**: from the cluster health check

    Parameters
    ----------
    node:
        Target node to query.  Uses default if empty.
    """
    report: dict[str, Any] = {
        "status": "ok",
        "operation": "cluster_status",
    }
    errors: list[dict[str, str]] = []

    # --- 1. Health check ---------------------------------------------------
    health_data: dict[str, Any] | None = None
    try:
        health_data = await talos__cluster__health(node=node)
    except Exception as exc:
        errors.append({"component": "health", "error": str(exc)})

    # --- 2. Version info ---------------------------------------------------
    version_data: dict[str, Any] | None = None
    try:
        version_data = await talos__cluster__get_version(node=node)
    except Exception as exc:
        errors.append({"component": "version", "error": str(exc)})

    # --- 3. Node membership via `talosctl get members` ---------------------
    members_data: dict[str, Any] | list[Any] | None = None
    try:
        client = _get_client()
        members_result = await client.run(
            ["get", "members"],
            nodes=node if node else None,
            json_output=True,
            timeout=15.0,
        )
        members_data = members_result.parsed
    except Exception as exc:
        errors.append({"component": "members", "error": str(exc)})

    # --- Compose the unified report ----------------------------------------

    # Severity: derive from health data, or CRITICAL if health failed
    if health_data is not None and health_data.get("status") == "ok":
        report["severity"] = health_data.get("severity", "UNKNOWN")
        report["health"] = health_data.get("cluster", {})
    elif health_data is not None and health_data.get("status") == "error":
        report["severity"] = health_data.get("severity", "CRITICAL")
        report["health"] = {"error": health_data.get("error", "health check failed")}
    else:
        report["severity"] = "UNKNOWN"
        report["health"] = {"error": "health data unavailable"}

    # Versions
    if version_data is not None and version_data.get("status") == "ok":
        # Extract Talos version from server_versions if available
        server_versions = version_data.get("server_versions", [])
        talos_version = None
        if server_versions:
            talos_version = server_versions[0].get("version", {}).get("tag")

        report["versions"] = {
            "talos_client": version_data.get("client_version", {}).get("tag"),
            "talos_server": talos_version,
        }
    elif version_data is not None and version_data.get("status") == "error":
        report["versions"] = {"error": version_data.get("error", "version check failed")}
    else:
        report["versions"] = {"error": "version data unavailable"}

    # Node inventory from members
    nodes_summary: list[dict[str, Any]] = []
    control_plane_count = 0
    worker_count = 0

    if isinstance(members_data, dict):
        for msg in members_data.get("messages", []):
            for member in msg.get("members", []):
                spec = member.get("spec", {})
                hostname = spec.get("hostname", member.get("id", "unknown"))
                machine_type = spec.get("machine_type", "unknown")
                addresses = spec.get("addresses", [])

                if machine_type == "controlplane":
                    control_plane_count += 1
                elif machine_type == "worker":
                    worker_count += 1

                node_entry: dict[str, Any] = {
                    "hostname": hostname,
                    "role": machine_type,
                    "addresses": addresses,
                }

                # Merge ready status from health data if available
                if health_data and health_data.get("status") == "ok":
                    health_nodes = health_data.get("nodes", [])
                    for hn in health_nodes:
                        if hn.get("hostname") == hostname:
                            node_entry["ready"] = hn.get("ready", False)
                            if hn.get("error"):
                                node_entry["error"] = hn["error"]
                            break

                nodes_summary.append(node_entry)

    report["nodes"] = {
        "total": control_plane_count + worker_count,
        "control_plane": control_plane_count,
        "workers": worker_count,
        "details": nodes_summary,
    }

    # If members data was unavailable, note it
    if members_data is None and not any(
        e["component"] == "members" for e in errors
    ):
        report["nodes"] = {"error": "member data unavailable"}

    # Attach errors if any sub-call failed
    if errors:
        report["errors"] = errors
        # If all three failed, mark the overall status as error
        if len(errors) == 3:
            report["status"] = "error"
            report["severity"] = "UNKNOWN"
            report["message"] = "All status sub-queries failed."
        else:
            report["message"] = (
                f"Partial status: {len(errors)} of 3 sub-queries failed."
            )
    else:
        report["message"] = (
            f"Cluster status: {report['severity']} -- "
            f"{control_plane_count} control plane, {worker_count} worker(s)"
        )

    return report


@mcp_server.tool()
@write_gate("TALOS")
async def talos__cluster__merge_talosconfig(
    talosconfig_path: str,
    *,
    apply: bool = False,
) -> dict[str, Any]:
    """Merge a talosconfig file into the current talosconfig.

    Executes ``talosctl config merge`` to merge contexts from
    the specified talosconfig into the default talosconfig file.

    Parameters
    ----------
    talosconfig_path:
        Path to the talosconfig file to merge.
    apply:
        Must be ``True`` to execute the write operation.
    """
    if not talosconfig_path.strip():
        return {
            "status": "error",
            "operation": "merge_talosconfig",
            "error": "No talosconfig path provided.",
        }

    client = _get_client()

    args = ["config", "merge", talosconfig_path.strip()]

    try:
        result = await client.run(
            args, json_output=False, use_cache=False, timeout=10.0
        )

        return {
            "status": "ok",
            "operation": "merge_talosconfig",
            "talosconfig_path": talosconfig_path.strip(),
            "message": (
                result.stdout.strip()
                or f"Talosconfig merged from {talosconfig_path.strip()}"
            ),
        }
    except TalosCtlError as exc:
        return {
            "status": "error",
            "operation": "merge_talosconfig",
            "talosconfig_path": talosconfig_path.strip(),
            "error": exc.message,
            "stderr": exc.stderr or "",
        }
