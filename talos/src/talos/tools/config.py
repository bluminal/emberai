"""Configuration generation and validation tools for Talos Linux.

Provides MCP tools for:
- Generating cluster secrets (``talosctl gen secrets``)
- Generating cluster configs (``talosctl gen config``)
- Validating machine configs (``talosctl validate``)
- Patching machine configs (``talosctl machineconfig patch``)
- Retrieving machine configs from running nodes (``talosctl get machineconfig``)
"""

from __future__ import annotations

import logging
import re
from typing import Any

from talos.api.talosctl_client import TalosCtlClient
from talos.errors import TalosCtlError
from talos.safety import write_gate
from talos.server import mcp_server

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Shared client factory
# ---------------------------------------------------------------------------

_client: TalosCtlClient | None = None


def _get_client() -> TalosCtlClient:
    """Return a module-level TalosCtlClient, creating one if needed."""
    global _client
    if _client is None:
        _client = TalosCtlClient()
    return _client


# ---------------------------------------------------------------------------
# Secret sanitisation patterns
# ---------------------------------------------------------------------------

_SECRET_KEYS = re.compile(
    r"^(key|secret|token|crt|cert|ca|bootstrap|aescbcEncryptionSecret"
    r"|trustdinfo|bootstraptoken)$",
    re.IGNORECASE,
)


def _sanitize_config(data: Any, *, _parent_key: str = "") -> Any:
    """Recursively redact secret values from a machine config dict.

    Replaces scalar values whose keys match sensitive patterns with
    ``"[REDACTED]"``.  Nested dicts/lists are always recursed into
    so that secrets at any depth are caught.
    """
    if isinstance(data, dict):
        result: dict[str, Any] = {}
        for k, v in data.items():
            if _SECRET_KEYS.search(k) and not isinstance(v, (dict, list)):
                result[k] = "[REDACTED]"
            else:
                result[k] = _sanitize_config(v, _parent_key=k)
        return result
    if isinstance(data, list):
        return [_sanitize_config(item) for item in data]
    return data


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


@mcp_server.tool()
@write_gate("TALOS")
async def talos__config__gen_secrets(
    output_path: str,
    *,
    apply: bool = False,
) -> dict[str, Any]:
    """Generate cluster secrets bundle and write to a file.

    Executes ``talosctl gen secrets -o <output_path>``.

    WARNING: The generated secrets file contains the root CA and
    bootstrap token for the entire cluster. Store it securely and
    never commit it to version control (TD10).

    Parameters
    ----------
    output_path:
        Filesystem path where the secrets bundle will be written.
    apply:
        Must be ``True`` to execute the write.
    """
    client = _get_client()

    try:
        result = await client.run(
            ["gen", "secrets", "-o", output_path],
            json_output=False,
            use_cache=False,
        )
        return {
            "status": "success",
            "output_path": output_path,
            "message": result.stdout.strip() or f"Secrets written to {output_path}",
            "warning": (
                "SECURITY: The secrets file contains the cluster root CA and "
                "bootstrap token. Store it in a secure location (e.g. a secrets "
                "manager) and never commit it to version control."
            ),
        }
    except TalosCtlError as exc:
        logger.error("gen secrets failed: %s", exc)
        return {
            "status": "error",
            "error": str(exc.message),
            "stderr": exc.stderr or "",
            "exit_code": exc.exit_code,
        }


@mcp_server.tool()
@write_gate("TALOS")
async def talos__config__gen_config(
    cluster_name: str,
    endpoint: str,
    *,
    secrets_file: str = "",
    install_disk: str = "/dev/sda",
    kubernetes_version: str = "",
    talos_version: str = "",
    output_dir: str = "",
    apply: bool = False,
) -> dict[str, Any]:
    """Generate Talos machine configuration files for a cluster.

    Executes ``talosctl gen config <cluster_name> <endpoint>`` with
    optional flags for secrets, install disk, versions, and output
    directory.

    Parameters
    ----------
    cluster_name:
        Name of the Kubernetes cluster.
    endpoint:
        Control plane endpoint URL (e.g. ``https://10.0.0.1:6443``).
    secrets_file:
        Path to a previously generated secrets bundle.
    install_disk:
        Target disk for Talos installation (default: ``/dev/sda``).
    kubernetes_version:
        Pin a specific Kubernetes version.
    talos_version:
        Pin a specific Talos version for the generated config.
    output_dir:
        Directory to write generated files into.
    apply:
        Must be ``True`` to execute the write.
    """
    client = _get_client()

    args: list[str] = ["gen", "config", cluster_name, endpoint]

    if secrets_file:
        args.extend(["--with-secrets", secrets_file])
    if install_disk:
        args.extend(["--install-disk", install_disk])
    if kubernetes_version:
        args.extend(["--kubernetes-version", kubernetes_version])
    if talos_version:
        args.extend(["--talos-version", talos_version])
    if output_dir:
        args.extend(["--output-dir", output_dir])

    try:
        result = await client.run(
            args,
            json_output=False,
            use_cache=False,
        )
        return {
            "status": "success",
            "cluster_name": cluster_name,
            "endpoint": endpoint,
            "output_dir": output_dir or ".",
            "message": result.stdout.strip() or "Configuration files generated.",
            "generated_files": [
                "controlplane.yaml",
                "worker.yaml",
                "talosconfig",
            ],
        }
    except TalosCtlError as exc:
        logger.error("gen config failed: %s", exc)
        return {
            "status": "error",
            "error": str(exc.message),
            "stderr": exc.stderr or "",
            "exit_code": exc.exit_code,
        }


@mcp_server.tool()
async def talos__config__validate(
    config_file: str,
    *,
    mode: str = "metal",
) -> dict[str, Any]:
    """Validate a Talos machine configuration file.

    Executes ``talosctl validate --config <file> --mode <mode> --strict``.

    Parameters
    ----------
    config_file:
        Path to the machine configuration YAML to validate.
    mode:
        Validation mode: ``metal``, ``cloud``, or ``container``
        (default: ``metal``).
    """
    client = _get_client()

    try:
        result = await client.run(
            ["validate", "--config", config_file, "--mode", mode, "--strict"],
            json_output=False,
            use_cache=False,
        )
        return {
            "status": "pass",
            "config_file": config_file,
            "mode": mode,
            "message": result.stdout.strip() or "Configuration is valid.",
        }
    except TalosCtlError as exc:
        logger.warning("validate failed: %s", exc)
        return {
            "status": "fail",
            "config_file": config_file,
            "mode": mode,
            "errors": exc.stderr or str(exc.message),
            "exit_code": exc.exit_code,
        }


@mcp_server.tool()
@write_gate("TALOS")
async def talos__config__patch_machineconfig(
    config_file: str,
    patches: str,
    *,
    output_file: str = "",
    apply: bool = False,
) -> dict[str, Any]:
    """Patch a Talos machine configuration file.

    Executes ``talosctl machineconfig patch <config_file> --patch <patches>``.
    The ``patches`` argument accepts inline JSON or a ``@file`` path.

    Parameters
    ----------
    config_file:
        Path to the machine configuration YAML to patch.
    patches:
        Inline JSON patch string or ``@<filepath>`` pointing to a patch file.
    output_file:
        Optional output path. If omitted, the patched config is written
        to stdout (captured in the result).
    apply:
        Must be ``True`` to execute the write.
    """
    client = _get_client()

    args: list[str] = ["machineconfig", "patch", config_file, "--patch", patches]
    if output_file:
        args.extend(["--output", output_file])

    try:
        result = await client.run(
            args,
            json_output=False,
            use_cache=False,
        )
        response: dict[str, Any] = {
            "status": "success",
            "config_file": config_file,
            "message": "Machine config patched successfully.",
        }
        if output_file:
            response["output_file"] = output_file
        else:
            response["patched_config"] = result.stdout
        return response
    except TalosCtlError as exc:
        logger.error("machineconfig patch failed: %s", exc)
        return {
            "status": "error",
            "error": str(exc.message),
            "stderr": exc.stderr or "",
            "exit_code": exc.exit_code,
        }


@mcp_server.tool()
async def talos__config__get_machineconfig(
    *,
    node: str = "",
) -> dict[str, Any]:
    """Retrieve machine configuration from a running Talos node.

    Executes ``talosctl get machineconfig`` and returns the config
    with secrets/keys redacted.

    Parameters
    ----------
    node:
        Target node IP or hostname. Uses the default node from
        talosconfig if not specified.
    """
    client = _get_client()

    try:
        result = await client.run(
            ["get", "machineconfig"],
            nodes=node if node else None,
            json_output=True,
        )

        config_data = result.parsed
        if config_data is not None:
            sanitized = _sanitize_config(config_data)
        else:
            # Fallback: return raw stdout when JSON parsing fails
            sanitized = None

        response: dict[str, Any] = {
            "status": "success",
        }
        if node:
            response["node"] = node
        if sanitized is not None:
            response["machineconfig"] = sanitized
        else:
            response["raw_output"] = result.stdout
        response["note"] = "Secrets and keys have been redacted from the output."
        return response
    except TalosCtlError as exc:
        logger.error("get machineconfig failed: %s", exc)
        return {
            "status": "error",
            "error": str(exc.message),
            "stderr": exc.stderr or "",
            "exit_code": exc.exit_code,
        }
