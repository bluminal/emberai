"""UniFi MCP server entry point.

Initializes the MCP server with environment-based configuration,
CLI-selectable transport (stdio or Streamable HTTP), and a startup
health probe (--check).

Entry points (defined in pyproject.toml):
    unifi-server       -> main()
    netex.plugins.unifi -> plugin_info()
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sys
from typing import Any

import httpx
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
    """Set up structured JSON logging on the root ``unifi`` logger.

    Returns the configured logger for convenience.
    """
    logger = logging.getLogger("unifi")
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
    ("UNIFI_LOCAL_HOST", "IP or hostname of the UniFi local gateway"),
    ("UNIFI_LOCAL_KEY", "API key for the local gateway"),
]

_OPTIONAL_ENV_VARS: list[tuple[str, str, str]] = [
    ("UNIFI_WRITE_ENABLED", "false", "Enable write operations (true/false)"),
    ("UNIFI_VERIFY_SSL", "true", "Verify TLS certificates (true/false)"),
    ("UNIFI_API_KEY", "", "API key for Cloud V1 / Site Manager (Phase 2)"),
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


def _mask_key(key: str) -> str:
    """Mask API key for safe logging -- shows only last 4 characters."""
    if len(key) > 4:
        return "****" + key[-4:]
    return "****"


async def _check_connectivity(host: str, verify_ssl: bool) -> tuple[bool, str]:
    """Attempt a lightweight GET to *host* and return (ok, detail).

    Uses a short timeout to avoid blocking the health probe.  SSL
    verification is controlled by the ``UNIFI_VERIFY_SSL`` setting.
    """
    # Normalise: ensure scheme is present
    url = host if host.startswith(("http://", "https://")) else f"https://{host}"
    masked_url = _mask_host(url)

    try:
        async with httpx.AsyncClient(verify=verify_ssl, timeout=10.0) as client:
            response = await client.get(url)
            return True, f"HTTP {response.status_code} from {masked_url}"
    except httpx.ConnectError as exc:
        return False, f"Connection refused or unreachable: {masked_url} ({exc})"
    except httpx.TimeoutException:
        return False, f"Connection timed out after 10 s: {masked_url}"
    except Exception as exc:
        return False, f"Unexpected error connecting to {masked_url}: {exc}"


def _run_check() -> int:
    """Execute the ``--check`` startup health probe and return an exit code.

    Steps:
    1. Verify required env vars are set and non-empty.
    2. Attempt a lightweight HTTP GET to ``UNIFI_LOCAL_HOST``.
    3. Print a human-readable status report.
    """
    import asyncio

    print("unifi: running startup health check ...\n")

    # --- env var validation ---
    all_ok = True
    load_dotenv()

    for var_name, description in _REQUIRED_ENV_VARS:
        value = os.environ.get(var_name, "").strip()
        if value:
            # Mask all values: IPs get octet-masked, keys get fully masked
            display = _mask_host(value) if var_name == "UNIFI_LOCAL_HOST" else _mask_key(value)
            print(f"  [PASS] {var_name} = {display}")
        else:
            print(f"  [FAIL] {var_name} is not set -- {description}")
            all_ok = False

    for var_name, default, _description in _OPTIONAL_ENV_VARS:
        value = os.environ.get(var_name, "").strip()
        status = value if value else f"(default: {default})"
        # Mask API keys/secrets
        if "KEY" in var_name and value:
            status = _mask_key(value)
        print(f"  [INFO] {var_name} = {status}")

    print()

    # --- connectivity probe ---
    host = os.environ.get("UNIFI_LOCAL_HOST", "").strip()
    verify_ssl = os.environ.get("UNIFI_VERIFY_SSL", "true").strip().lower() != "false"
    if host:
        masked_host = _mask_host(host)
        print(f"  Probing gateway at {masked_host} ...")
        ok, detail = asyncio.run(_check_connectivity(host, verify_ssl))
        if ok:
            print(f"  [PASS] Gateway reachable: {detail}")
        else:
            print(f"  [FAIL] Gateway unreachable: {detail}")
            all_ok = False
    else:
        print("  [SKIP] Gateway probe skipped (UNIFI_LOCAL_HOST not set)")
        all_ok = False

    print()
    if all_ok:
        print("unifi: health check PASSED")
        return 0
    else:
        print("unifi: health check FAILED (see above)")
        return 1


# ---------------------------------------------------------------------------
# MCP server
# ---------------------------------------------------------------------------

# The server instance is created at module level so that tool modules
# (imported in later tasks) can decorate their handlers with @mcp.tool().
mcp_server = FastMCP(
    name="unifi",
    instructions=(
        "UniFi network intelligence plugin. Provides topology discovery, "
        "health monitoring, WiFi analysis, client management, traffic "
        "inspection, security audit, and configuration management for "
        "UniFi deployments via the Local Gateway API."
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
        "name": "unifi",
        "version": "0.1.0",
        "vendor": "unifi",
        "description": (
            "UniFi network intelligence -- topology, health, WiFi, "
            "clients, traffic, security, config, multi-site"
        ),
        "roles": ["edge", "wireless"],
        "skills": [
            "topology",
            "health",
            "wifi",
            "clients",
            "traffic",
            "security",
            "config",
            "multisite",
        ],
        "write_flag": "UNIFI_WRITE_ENABLED",
        "contract_version": "1.0.0",
        "server_factory": lambda: mcp_server,
    }


# ---------------------------------------------------------------------------
# CLI & main
# ---------------------------------------------------------------------------


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="unifi-server",
        description="UniFi MCP server for network intelligence",
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
    """Entry point for the ``unifi-server`` console script.

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
    import unifi.tools  # noqa: F401

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

    write_enabled = config.get("UNIFI_WRITE_ENABLED", "false").lower() == "true"
    cache_ttl = int(config.get("NETEX_CACHE_TTL", "300"))

    logger.info(
        "Starting UniFi MCP server",
        extra={
            "component": "startup",
            "detail": {
                "transport": args.transport,
                "host": config.get("UNIFI_LOCAL_HOST", ""),
                "write_enabled": write_enabled,
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
