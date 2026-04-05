"""Cisco SG-300 MCP server entry point.

Initializes the MCP server with environment-based configuration,
CLI-selectable transport (stdio or Streamable HTTP), and a startup
health probe (--check).

Entry points (defined in pyproject.toml):
    cisco-server           -> main()
    netex.plugins.cisco    -> plugin_info()
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sys
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
        # Merge any extra fields attached via `extra=`
        for key in ("component", "detail"):
            value = getattr(record, key, None)
            if value is not None:
                log_entry[key] = value
        return json.dumps(log_entry, default=str)


def _configure_logging(level: str = _LOG_LEVEL_DEFAULT) -> logging.Logger:
    """Set up structured JSON logging on the root ``cisco`` logger.

    Returns the configured logger for convenience.
    """
    logger = logging.getLogger("cisco")
    logger.setLevel(getattr(logging, level.upper(), logging.INFO))

    if not logger.handlers:
        handler = logging.StreamHandler(sys.stderr)
        handler.setFormatter(JSONFormatter())
        logger.addHandler(handler)

    # Prevent duplicate messages if root logger also has handlers
    logger.propagate = False
    return logger


logger = _configure_logging()

# ---------------------------------------------------------------------------
# Environment helpers
# ---------------------------------------------------------------------------

_REQUIRED_ENV_VARS: list[tuple[str, str]] = [
    ("CISCO_HOST", "IP or hostname of the Cisco SG-300 switch"),
    ("CISCO_SSH_USERNAME", "SSH username for CLI access"),
    ("CISCO_SSH_PASSWORD", "SSH password for CLI access"),
]

_OPTIONAL_ENV_VARS: list[tuple[str, str, str]] = [
    ("CISCO_ENABLE_PASSWORD", "", "Enable password for privileged EXEC mode (if configured)"),
    ("CISCO_SNMP_COMMUNITY", "public", "SNMP v2c community string for monitoring"),
    ("CISCO_WRITE_ENABLED", "false", "Enable write operations (true/false)"),
    ("CISCO_VERIFY_SSH_HOST_KEY", "true", "Verify SSH host key (true/false)"),
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


def _mask_host(host: str) -> str:
    """Mask internal IP/hostname for safe logging.

    Replaces all but the last octet of IPv4 addresses with ``*``.
    Non-IP hostnames are returned unchanged.
    """
    return re.sub(r"\d+\.\d+\.\d+\.(\d+)", r"*.*.*.\1", host)


def _mask_password(password: str) -> str:
    """Mask SSH password for safe logging -- shows only last 2 characters."""
    if len(password) > 2:
        return "****" + password[-2:]
    return "****"


async def _check_connectivity(
    host: str,
    username: str,
    password: str,
    enable_password: str,
    verify_host_key: bool,
) -> tuple[bool, str]:
    """Attempt an SSH connection to *host* with ``show version`` and return (ok, detail).

    Uses Netmiko with a short timeout to avoid blocking the health probe.
    """
    import asyncio

    masked_host = _mask_host(host)

    def _ssh_probe() -> tuple[bool, str]:
        try:
            from netmiko import ConnectHandler

            device: dict[str, Any] = {
                "device_type": "cisco_s300",
                "host": host,
                "username": username,
                "password": password,
                "timeout": 10,
                "conn_timeout": 10,
            }
            if enable_password:
                device["secret"] = enable_password
            if not verify_host_key:
                device["ssh_config_file"] = None

            with ConnectHandler(**device) as conn:
                output = conn.send_command("show version", read_timeout=10)
                # Extract first line for summary
                first_line = output.strip().split("\n")[0] if output.strip() else "Connected"
                return True, f"SSH OK to {masked_host}: {first_line}"
        except Exception as exc:
            return False, f"SSH connection failed to {masked_host}: {exc}"

    # Run the blocking SSH call in a thread pool
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, _ssh_probe)


def _run_check() -> int:
    """Execute the ``--check`` startup health probe and return an exit code.

    Steps:
    1. Verify required env vars are set and non-empty.
    2. Attempt an SSH connection to ``CISCO_HOST`` with ``show version``.
    3. Print a human-readable status report.
    """
    import asyncio

    print("cisco: running startup health check ...\n")

    # --- env var validation ---
    all_ok = True
    load_dotenv()

    for var_name, description in _REQUIRED_ENV_VARS:
        value = os.environ.get(var_name, "").strip()
        if value:
            # Mask all values: hosts get octet-masked, passwords get fully masked
            if var_name == "CISCO_HOST":
                display = _mask_host(value)
            elif "PASSWORD" in var_name:
                display = _mask_password(value)
            else:
                display = value
            print(f"  [PASS] {var_name} = {display}")
        else:
            print(f"  [FAIL] {var_name} is not set -- {description}")
            all_ok = False

    for var_name, default, _description in _OPTIONAL_ENV_VARS:
        value = os.environ.get(var_name, "").strip()
        status = value if value else f"(default: {default})"
        # Mask passwords and community strings
        if ("PASSWORD" in var_name and value) or ("COMMUNITY" in var_name and value):
            status = _mask_password(value)
        print(f"  [INFO] {var_name} = {status}")

    print()

    # --- connectivity probe ---
    host = os.environ.get("CISCO_HOST", "").strip()
    username = os.environ.get("CISCO_SSH_USERNAME", "").strip()
    password = os.environ.get("CISCO_SSH_PASSWORD", "").strip()
    enable_password = os.environ.get("CISCO_ENABLE_PASSWORD", "").strip()
    verify_host_key = (
        os.environ.get("CISCO_VERIFY_SSH_HOST_KEY", "true").strip().lower() != "false"
    )

    if host and username and password:
        masked_host = _mask_host(host)
        print(f"  Probing Cisco SG-300 at {masked_host} via SSH ...")
        ok, detail = asyncio.run(
            _check_connectivity(host, username, password, enable_password, verify_host_key)
        )
        if ok:
            print(f"  [PASS] Cisco SG-300 reachable: {detail}")
        else:
            print(f"  [FAIL] Cisco SG-300 unreachable: {detail}")
            all_ok = False
    else:
        print("  [SKIP] Connectivity probe skipped (credentials incomplete)")
        all_ok = False

    print()
    if all_ok:
        print("cisco: health check PASSED")
        return 0
    else:
        print("cisco: health check FAILED (see above)")
        return 1


# ---------------------------------------------------------------------------
# MCP server
# ---------------------------------------------------------------------------

# The server instance is created at module level so that tool modules
# (imported in later tasks) can decorate their handlers with @mcp.tool().
mcp_server = FastMCP(
    name="cisco",
    instructions=(
        "Cisco SG-300 managed switch plugin. Provides VLAN management, "
        "port configuration, MAC address table lookup, LLDP topology "
        "discovery, interface counters, spanning tree status, and health "
        "monitoring via SSH CLI (Netmiko) and SNMP."
    ),
)


# ---------------------------------------------------------------------------
# Plugin Registry entry point
# ---------------------------------------------------------------------------


def plugin_info() -> dict[str, Any]:
    """Return plugin metadata for Netex Plugin Registry discovery.

    Called via the ``netex.plugins`` entry-point group defined in
    ``pyproject.toml``.  The registry uses this to discover installed
    vendor plugins at runtime (Decision D12).
    """
    return {
        "name": "cisco",
        "version": "0.1.0",
        "vendor": "cisco",
        "description": (
            "Cisco SG-300 managed switch intelligence -- VLANs, ports, "
            "MAC table, LLDP topology, interface counters, health monitoring"
        ),
        "roles": ["edge"],
        "skills": [
            "topology",
            "interfaces",
            "clients",
            "health",
            "config",
        ],
        "write_flag": "CISCO_WRITE_ENABLED",
        "contract_version": "1.0.0",
        "server_factory": lambda: mcp_server,
    }


# ---------------------------------------------------------------------------
# CLI & main
# ---------------------------------------------------------------------------


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="cisco-server",
        description="Cisco SG-300 MCP server for managed switch intelligence",
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
    """Entry point for the ``cisco-server`` console script.

    Parses CLI arguments, loads environment configuration, and starts
    the MCP server with the selected transport.
    """
    args = _parse_args(argv)

    # Reconfigure logging if --log-level was provided
    if args.log_level:
        _configure_logging(args.log_level)

    # --- health check mode ---
    if args.check:
        raise SystemExit(_run_check())

    # Register MCP tools before starting the server
    import cisco.tools  # noqa: F401

    # --- normal startup ---
    try:
        config = _load_env()
    except ConfigError as exc:
        logger.warning(
            "Configuration incomplete: %s. "
            "Server will start but tools will fail until env vars are set. "
            "See: https://bluminal.github.io/emberai/getting-started/authentication/",
            str(exc),
            extra={"component": "startup"},
        )
        config = {}

    write_enabled = config.get("CISCO_WRITE_ENABLED", "false").lower() == "true"
    verify_host_key = config.get("CISCO_VERIFY_SSH_HOST_KEY", "true").lower() != "false"
    cache_ttl = int(config.get("NETEX_CACHE_TTL", "300"))

    logger.info(
        "Starting Cisco SG-300 MCP server",
        extra={
            "component": "startup",
            "detail": {
                "transport": args.transport,
                "host": _mask_host(config.get("CISCO_HOST", "")),
                "write_enabled": write_enabled,
                "verify_host_key": verify_host_key,
                "cache_ttl": cache_ttl,
            },
        },
    )

    # Map CLI transport names to FastMCP transport identifiers
    transport_map: dict[str, str] = {
        "stdio": "stdio",
        "http": "streamable-http",
    }

    mcp_server.run(transport=transport_map[args.transport])  # type: ignore[arg-type]


if __name__ == "__main__":
    main()
