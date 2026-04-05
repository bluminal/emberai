"""Talos Linux MCP server entry point.

Initializes the MCP server with environment-based configuration,
CLI-selectable transport (stdio or Streamable HTTP), and a startup
health probe (--check).

Entry points (defined in pyproject.toml):
    talos-server           -> main()
    netex.plugins.talos    -> plugin_info()
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP

# ---------------------------------------------------------------------------
# Structured JSON log formatter
# ---------------------------------------------------------------------------

_LOG_LEVEL_DEFAULT = "INFO"


class JSONFormatter(logging.Formatter):
    """Emit log records as single-line JSON objects."""

    def format(self, record: logging.LogRecord) -> str:
        log_entry: dict[str, Any] = {
            "timestamp": self.formatTime(record, self.datefmt),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info and record.exc_info[0] is not None:
            log_entry["exception"] = self.formatException(record.exc_info)
        for key in ("component", "detail"):
            value = getattr(record, key, None)
            if value is not None:
                log_entry[key] = value
        return json.dumps(log_entry, default=str)


def _configure_logging(level: str = _LOG_LEVEL_DEFAULT) -> logging.Logger:
    """Set up structured JSON logging on the root ``talos`` logger."""
    logger = logging.getLogger("talos")
    logger.setLevel(getattr(logging, level.upper(), logging.INFO))

    if not logger.handlers:
        handler = logging.StreamHandler(sys.stderr)
        handler.setFormatter(JSONFormatter())
        logger.addHandler(handler)

    logger.propagate = False
    return logger


logger = _configure_logging()

# ---------------------------------------------------------------------------
# Environment helpers
# ---------------------------------------------------------------------------

_REQUIRED_ENV_VARS: list[tuple[str, str]] = [
    ("TALOS_CONFIG", "Path to talosconfig file (contains mTLS credentials)"),
]

_OPTIONAL_ENV_VARS: list[tuple[str, str, str]] = [
    ("TALOS_CONTEXT", "", "Named context within the talosconfig file"),
    ("TALOS_WRITE_ENABLED", "false", "Enable write operations (true/false)"),
    ("TALOS_NODES", "", "Default target node IPs (comma-separated)"),
    ("NETEX_CACHE_TTL", "300", "TTL in seconds for cached responses"),
]


class ConfigError(Exception):
    """Raised when required configuration is missing or invalid."""


def _load_env() -> dict[str, str]:
    """Load ``.env`` file and return validated configuration dict.

    Raises :class:`ConfigError` if any required variable is unset or empty.
    """
    load_dotenv()

    missing: list[str] = []
    config: dict[str, str] = {}

    for var_name, description in _REQUIRED_ENV_VARS:
        value = os.environ.get(var_name, "").strip()
        if not value:
            missing.append(f"  {var_name} -- {description}")
        config[var_name] = value

    if missing:
        raise ConfigError("Required environment variables are not set:\n" + "\n".join(missing))

    for var_name, default, _description in _OPTIONAL_ENV_VARS:
        config[var_name] = os.environ.get(var_name, default).strip() or default

    return config


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------


def _check_talosctl_binary() -> tuple[bool, str]:
    """Verify that talosctl is installed and return version info."""
    talosctl_path = shutil.which("talosctl")
    if talosctl_path is None:
        return False, (
            "talosctl binary not found on PATH. "
            "Install: brew install siderolabs/tap/talosctl"
        )

    try:
        result = subprocess.run(
            [talosctl_path, "version", "--client", "--short"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        version = result.stdout.strip() or "unknown"
        return True, f"talosctl found at {talosctl_path} (version: {version})"
    except (subprocess.TimeoutExpired, OSError) as exc:
        return False, f"talosctl found at {talosctl_path} but failed to run: {exc}"


def _check_talosconfig(config_path: str) -> tuple[bool, str]:
    """Verify that the talosconfig file exists and is readable."""
    path = Path(config_path)
    if not path.exists():
        return False, f"talosconfig not found at {config_path}"
    if not path.is_file():
        return False, f"talosconfig path is not a file: {config_path}"
    try:
        content = path.read_text()
        if not content.strip():
            return False, f"talosconfig is empty: {config_path}"
        return True, f"talosconfig found at {config_path} ({len(content)} bytes)"
    except PermissionError:
        return False, f"talosconfig not readable (permission denied): {config_path}"


def _run_check() -> int:
    """Execute the ``--check`` startup health probe and return an exit code."""
    print("talos: running startup health check ...\n")

    all_ok = True
    load_dotenv()

    # --- env var validation ---
    for var_name, description in _REQUIRED_ENV_VARS:
        value = os.environ.get(var_name, "").strip()
        if value:
            print(f"  [PASS] {var_name} = {value}")
        else:
            print(f"  [FAIL] {var_name} is not set -- {description}")
            all_ok = False

    for var_name, default, _description in _OPTIONAL_ENV_VARS:
        value = os.environ.get(var_name, "").strip()
        status = value if value else f"(default: {default})"
        print(f"  [INFO] {var_name} = {status}")

    print()

    # --- talosctl binary check ---
    ok, detail = _check_talosctl_binary()
    if ok:
        print(f"  [PASS] {detail}")
    else:
        print(f"  [FAIL] {detail}")
        all_ok = False

    # --- talosconfig check ---
    config_path = os.environ.get("TALOS_CONFIG", "").strip()
    if config_path:
        ok, detail = _check_talosconfig(config_path)
        if ok:
            print(f"  [PASS] {detail}")
        else:
            print(f"  [FAIL] {detail}")
            all_ok = False
    else:
        print("  [SKIP] talosconfig check skipped (TALOS_CONFIG not set)")
        all_ok = False

    print()
    if all_ok:
        print("talos: health check PASSED")
        return 0
    else:
        print("talos: health check FAILED (see above)")
        return 1


# ---------------------------------------------------------------------------
# MCP server
# ---------------------------------------------------------------------------

mcp_server = FastMCP(
    name="talos",
    instructions=(
        "Talos Linux Kubernetes cluster intelligence plugin. Provides "
        "cluster lifecycle management (bootstrap, health, kubeconfig), "
        "node operations (reboot, shutdown, reset, upgrade), etcd management "
        "(members, snapshots, defrag), configuration generation and validation, "
        "diagnostics (logs, events, services), and security operations "
        "(CA rotation, SecureBoot). Communicates via talosctl CLI over "
        "gRPC + mTLS."
    ),
)


# ---------------------------------------------------------------------------
# Plugin Registry entry point
# ---------------------------------------------------------------------------


def plugin_info() -> dict[str, Any]:
    """Return plugin metadata for Netex Plugin Registry discovery.

    Called via the ``netex.plugins`` entry-point group defined in
    ``pyproject.toml``.
    """
    return {
        "name": "talos",
        "version": "0.1.0",
        "vendor": "talos",
        "description": (
            "Talos Linux Kubernetes cluster intelligence -- cluster lifecycle, "
            "node management, etcd operations, diagnostics, security"
        ),
        "roles": ["compute"],
        "skills": [
            "cluster",
            "nodes",
            "etcd",
            "kubernetes",
            "diagnostics",
            "config",
            "security",
            "images",
        ],
        "write_flag": "TALOS_WRITE_ENABLED",
        "contract_version": "1.0.0",
        "server_factory": lambda: mcp_server,
    }


# ---------------------------------------------------------------------------
# CLI & main
# ---------------------------------------------------------------------------


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="talos-server",
        description="Talos Linux MCP server for Kubernetes cluster intelligence",
    )
    parser.add_argument(
        "--transport",
        choices=["stdio", "http"],
        default="stdio",
        help="MCP transport mode (default: stdio)",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Run startup health probe and exit",
    )
    parser.add_argument(
        "--log-level",
        choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
        default=None,
        help="Override log level (default: INFO)",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    """Entry point for the ``talos-server`` console script."""
    args = _parse_args(argv)

    if args.log_level:
        _configure_logging(args.log_level)

    # --- health check mode ---
    if args.check:
        raise SystemExit(_run_check())

    # Register MCP tools before starting the server
    import talos.tools  # noqa: F401

    # --- normal startup ---
    try:
        config = _load_env()
    except ConfigError as exc:
        logger.warning(
            "Configuration incomplete: %s. "
            "Server will start but tools will fail until env vars are set.",
            str(exc),
            extra={"component": "startup"},
        )
        config = {}

    write_enabled = config.get("TALOS_WRITE_ENABLED", "false").lower() == "true"
    talos_config = config.get("TALOS_CONFIG", "")
    talos_context = config.get("TALOS_CONTEXT", "")
    talos_nodes = config.get("TALOS_NODES", "")
    cache_ttl = int(config.get("NETEX_CACHE_TTL", "300"))

    logger.info(
        "Starting Talos Linux MCP server",
        extra={
            "component": "startup",
            "detail": {
                "transport": args.transport,
                "talos_config": talos_config,
                "talos_context": talos_context or "(default)",
                "talos_nodes": talos_nodes or "(none)",
                "write_enabled": write_enabled,
                "cache_ttl": cache_ttl,
            },
        },
    )

    transport_map: dict[str, str] = {
        "stdio": "stdio",
        "http": "streamable-http",
    }

    mcp_server.run(transport=transport_map[args.transport])  # type: ignore[arg-type]


if __name__ == "__main__":
    main()
