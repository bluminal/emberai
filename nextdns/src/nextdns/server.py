"""NextDNS MCP server entry point.

Initializes the MCP server with environment-based configuration,
CLI-selectable transport (stdio or Streamable HTTP), and a startup
health probe (--check).

Entry points (defined in pyproject.toml):
    nextdns-server        -> main()
    netex.plugins.nextdns -> plugin_info()
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
    """Set up structured JSON logging on the root ``nextdns`` logger.

    Returns the configured logger for convenience.
    """
    logger = logging.getLogger("nextdns")
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
    ("NEXTDNS_API_KEY", "API key for NextDNS API"),
]

_OPTIONAL_ENV_VARS: list[tuple[str, str, str]] = [
    ("NEXTDNS_WRITE_ENABLED", "false", "Enable write operations (true/false)"),
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


def _mask_key(key: str) -> str:
    """Mask API key for safe logging -- shows only last 4 characters."""
    if len(key) > 4:
        return "****" + key[-4:]
    return "****"


async def _check_connectivity(api_key: str) -> tuple[bool, str]:
    """Attempt a lightweight GET to the NextDNS API and return (ok, detail).

    Uses a short timeout to avoid blocking the health probe.
    """
    url = "https://api.nextdns.io/profiles"

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(
                url,
                headers={"X-Api-Key": api_key},
            )
            if response.status_code == 200:
                return True, f"HTTP {response.status_code} from api.nextdns.io"
            if response.status_code == 401:
                return False, "HTTP 401 Unauthorized -- API key is invalid"
            if response.status_code == 403:
                return False, "HTTP 403 Forbidden -- API key lacks required permissions"
            return False, f"HTTP {response.status_code} from api.nextdns.io"
    except httpx.ConnectError as exc:
        return False, f"Connection refused or unreachable: api.nextdns.io ({exc})"
    except httpx.TimeoutException:
        return False, "Connection timed out after 10 s: api.nextdns.io"
    except Exception as exc:
        return False, f"Unexpected error connecting to api.nextdns.io: {exc}"


def _run_check() -> int:
    """Execute the ``--check`` startup health probe and return an exit code.

    Steps:
    1. Verify required env vars are set and non-empty.
    2. Attempt a lightweight HTTP GET to the NextDNS API.
    3. Print a human-readable status report.
    """
    import asyncio

    print("nextdns: running startup health check ...\n")

    # --- env var validation ---
    all_ok = True
    load_dotenv()

    for var_name, description in _REQUIRED_ENV_VARS:
        value = os.environ.get(var_name, "").strip()
        if value:
            print(f"  [PASS] {var_name} = {_mask_key(value)}")
        else:
            print(f"  [FAIL] {var_name} is not set -- {description}")
            all_ok = False

    for var_name, default, _description in _OPTIONAL_ENV_VARS:
        value = os.environ.get(var_name, "").strip()
        status = value if value else f"(default: {default})"
        print(f"  [INFO] {var_name} = {status}")

    print()

    # --- connectivity probe ---
    api_key = os.environ.get("NEXTDNS_API_KEY", "").strip()
    if api_key:
        print("  Probing NextDNS API at api.nextdns.io ...")
        ok, detail = asyncio.run(_check_connectivity(api_key))
        if ok:
            print(f"  [PASS] API reachable: {detail}")
        else:
            print(f"  [FAIL] API unreachable: {detail}")
            all_ok = False
    else:
        print("  [SKIP] API probe skipped (NEXTDNS_API_KEY not set)")
        all_ok = False

    print()
    if all_ok:
        print("nextdns: health check PASSED")
        return 0
    else:
        print("nextdns: health check FAILED (see above)")
        return 1


# ---------------------------------------------------------------------------
# MCP server
# ---------------------------------------------------------------------------

# The server instance is created at module level so that tool modules
# (imported in later tasks) can decorate their handlers with @mcp_server.tool().
mcp_server = FastMCP(
    name="nextdns",
    instructions=(
        "NextDNS intelligence plugin. Provides DNS profile management, "
        "security posture auditing, analytics dashboards, query log "
        "analysis, and parental control configuration across NextDNS "
        "profiles via the NextDNS API."
    ),
)

# Import tool modules to register @mcp_server.tool() decorators.
# These imports must happen after mcp_server is created.
import nextdns.tools.analytics  # noqa: E402
import nextdns.tools.profiles  # noqa: E402
import nextdns.tools.security_posture  # noqa: F401, E402

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
        "name": "nextdns",
        "version": "0.1.0",
        "description": "NextDNS intelligence plugin for EmberAI",
        "vendor": "nextdns",
        "roles": ["dns"],
        "skills": ["profiles", "analytics", "logs", "security-posture"],
        "write_flag": "NEXTDNS_WRITE_ENABLED",
        "contract_version": "1.0.0",
        "server_factory": lambda: mcp_server,
        "is_orchestrator": False,
    }


# ---------------------------------------------------------------------------
# CLI & main
# ---------------------------------------------------------------------------


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="nextdns-server",
        description="NextDNS MCP server for DNS intelligence",
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
        "--host",
        default="0.0.0.0",
        help="Host to bind HTTP transport (default: 0.0.0.0)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8000,
        help="Port to bind HTTP transport (default: 8000)",
    )
    parser.add_argument(
        "--log-level",
        choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
        default=None,
        help="Override log level (default: INFO)",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    """Entry point for the ``nextdns-server`` console script.

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

    # --- Register MCP tools before starting the server ---
    # Tool modules will be imported here once they are implemented.
    # Example: import nextdns.tools

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

    write_enabled = config.get("NEXTDNS_WRITE_ENABLED", "false").lower() == "true"
    cache_ttl = int(config.get("NETEX_CACHE_TTL", "300"))

    logger.info(
        "Starting NextDNS MCP server",
        extra={
            "component": "startup",
            "detail": {
                "transport": args.transport,
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
