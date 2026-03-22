"""OPNsense MCP server entry point.

Initializes the MCP server with environment-based configuration,
CLI-selectable transport (stdio or Streamable HTTP), and a startup
health probe (--check).

Entry points (defined in pyproject.toml):
    opnsense-server        -> main()
    netex.plugins.opnsense -> plugin_info()
"""

from __future__ import annotations

import argparse
import json
import logging
import os
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
    """Set up structured JSON logging on the root ``opnsense`` logger.

    Returns the configured logger for convenience.
    """
    logger = logging.getLogger("opnsense")
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
    ("OPNSENSE_HOST", "IP or hostname of the OPNsense instance (e.g., https://192.168.1.1)"),
    ("OPNSENSE_API_KEY", "API key (Basic Auth username)"),
    ("OPNSENSE_API_SECRET", "API secret (Basic Auth password)"),
]

_OPTIONAL_ENV_VARS: list[tuple[str, str, str]] = [
    ("OPNSENSE_WRITE_ENABLED", "false", "Enable write operations (true/false)"),
    ("OPNSENSE_VERIFY_SSL", "true", "Verify TLS certificates (true/false)"),
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
        raise ConfigError(
            "Required environment variables are not set:\n" + "\n".join(missing)
        )

    for var_name, default, _description in _OPTIONAL_ENV_VARS:
        config[var_name] = os.environ.get(var_name, default).strip() or default

    return config


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------


async def _check_connectivity(host: str, api_key: str, api_secret: str,
                              verify_ssl: bool) -> tuple[bool, str]:
    """Attempt a lightweight GET to *host* using Basic Auth and return (ok, detail).

    Uses a short timeout to avoid blocking the health probe.  OPNsense
    instances commonly use self-signed certificates, so SSL verification
    is controlled by the OPNSENSE_VERIFY_SSL configuration.
    """
    # Normalise: ensure scheme is present
    url = host if host.startswith(("http://", "https://")) else f"https://{host}"
    # Use a lightweight API endpoint for the health probe
    probe_url = f"{url}/api/core/firmware/status"

    try:
        async with httpx.AsyncClient(
            verify=verify_ssl,
            timeout=10.0,
            auth=(api_key, api_secret),
        ) as client:
            response = await client.get(probe_url)
            return True, f"HTTP {response.status_code} from {probe_url}"
    except httpx.ConnectError as exc:
        return False, f"Connection refused or unreachable: {url} ({exc})"
    except httpx.TimeoutException:
        return False, f"Connection timed out after 10 s: {url}"
    except Exception as exc:  # noqa: BLE001
        return False, f"Unexpected error connecting to {url}: {exc}"


def _run_check() -> int:
    """Execute the ``--check`` startup health probe and return an exit code.

    Steps:
    1. Verify required env vars are set and non-empty.
    2. Attempt a lightweight HTTP GET to ``OPNSENSE_HOST`` with Basic Auth.
    3. Print a human-readable status report.
    """
    import asyncio

    print("opnsense: running startup health check ...\n")

    # --- env var validation ---
    all_ok = True
    load_dotenv()

    for var_name, description in _REQUIRED_ENV_VARS:
        value = os.environ.get(var_name, "").strip()
        if value:
            # Mask sensitive values
            if var_name == "OPNSENSE_HOST":
                display = value
            else:
                display = f"{value[:4]}****"
            print(f"  [PASS] {var_name} = {display}")
        else:
            print(f"  [FAIL] {var_name} is not set -- {description}")
            all_ok = False

    for var_name, default, description in _OPTIONAL_ENV_VARS:
        value = os.environ.get(var_name, "").strip()
        status = value if value else f"(default: {default})"
        # Mask API keys/secrets
        if ("KEY" in var_name or "SECRET" in var_name) and value:
            status = f"{value[:4]}****"
        print(f"  [INFO] {var_name} = {status}")

    print()

    # --- connectivity probe ---
    host = os.environ.get("OPNSENSE_HOST", "").strip()
    api_key = os.environ.get("OPNSENSE_API_KEY", "").strip()
    api_secret = os.environ.get("OPNSENSE_API_SECRET", "").strip()
    verify_ssl = os.environ.get("OPNSENSE_VERIFY_SSL", "true").strip().lower() != "false"

    if host and api_key and api_secret:
        print(f"  Probing OPNsense at {host} ...")
        ok, detail = asyncio.run(_check_connectivity(host, api_key, api_secret, verify_ssl))
        if ok:
            print(f"  [PASS] OPNsense reachable: {detail}")
        else:
            print(f"  [FAIL] OPNsense unreachable: {detail}")
            all_ok = False
    else:
        print("  [SKIP] Connectivity probe skipped (credentials incomplete)")
        all_ok = False

    print()
    if all_ok:
        print("opnsense: health check PASSED")
        return 0
    else:
        print("opnsense: health check FAILED (see above)")
        return 1


# ---------------------------------------------------------------------------
# MCP server
# ---------------------------------------------------------------------------

# The server instance is created at module level so that tool modules
# (imported in later tasks) can decorate their handlers with @mcp.tool().
mcp_server = FastMCP(
    name="opnsense",
    instructions=(
        "OPNsense gateway intelligence plugin. Provides interface and VLAN "
        "management, firewall rule analysis, static routing, VPN tunnel "
        "status, DNS (Unbound), DHCP (Kea), IDS/IPS (Suricata), traffic "
        "shaping, live diagnostics, and firmware management via the "
        "OPNsense REST API."
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
        "name": "opnsense",
        "version": "0.1.0",
        "vendor": "opnsense",
        "description": (
            "OPNsense gateway intelligence -- interfaces, firewall, "
            "routing, VPN, security, services, diagnostics, firmware"
        ),
        "roles": ["gateway"],
        "skills": [
            "interfaces",
            "firewall",
            "routing",
            "vpn",
            "security",
            "services",
            "diagnostics",
            "firmware",
        ],
        "write_flag": "OPNSENSE_WRITE_ENABLED",
        "contract_version": "1.0.0",
        "server_factory": lambda: mcp_server,
    }


# ---------------------------------------------------------------------------
# CLI & main
# ---------------------------------------------------------------------------


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="opnsense-server",
        description="OPNsense MCP server for gateway intelligence",
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
    """Entry point for the ``opnsense-server`` console script.

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
    import opnsense.tools  # noqa: F401

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

    write_enabled = config.get("OPNSENSE_WRITE_ENABLED", "false").lower() == "true"
    verify_ssl = config.get("OPNSENSE_VERIFY_SSL", "true").lower() != "false"
    cache_ttl = int(config.get("NETEX_CACHE_TTL", "300"))

    logger.info(
        "Starting OPNsense MCP server",
        extra={
            "component": "startup",
            "detail": {
                "transport": args.transport,
                "host": config["OPNSENSE_HOST"],
                "write_enabled": write_enabled,
                "verify_ssl": verify_ssl,
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
