"""Netex MCP server entry point.

Initializes the MCP server with environment-based configuration,
CLI-selectable transport (stdio or Streamable HTTP), and a startup
health probe (--check).

Unlike vendor plugins, netex has no required API credentials -- it
discovers and coordinates installed vendor plugins via the Plugin
Registry.

Entry points (defined in pyproject.toml):
    netex-server       -> main()
    netex.plugins.netex -> plugin_info()
"""

from __future__ import annotations

import argparse
import json
import logging
import os
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
    """Set up structured JSON logging on the root ``netex`` logger.

    Returns the configured logger for convenience.
    """
    logger = logging.getLogger("netex")
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

# Netex has no required env vars -- it discovers plugins dynamically.
_REQUIRED_ENV_VARS: list[tuple[str, str]] = []

_OPTIONAL_ENV_VARS: list[tuple[str, str, str]] = [
    ("NETEX_WRITE_ENABLED", "false", "Enable cross-vendor write operations (true/false)"),
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


def _run_check() -> int:
    """Execute the ``--check`` startup health probe and return an exit code.

    Steps:
    1. Verify env vars are set.
    2. Attempt to discover installed vendor plugins.
    3. Print a human-readable status report.
    """
    from netex.registry.plugin_registry import PluginRegistry

    print("netex: running startup health check ...\n")

    # --- env var validation ---
    all_ok = True
    load_dotenv()

    for var_name, default, _description in _OPTIONAL_ENV_VARS:
        value = os.environ.get(var_name, "").strip()
        status = value if value else f"(default: {default})"
        print(f"  [INFO] {var_name} = {status}")

    print()

    # --- plugin discovery probe ---
    print("  Discovering installed vendor plugins ...")
    try:
        registry = PluginRegistry()
        plugins = registry.list_plugins()
        if plugins:
            for p in plugins:
                print(f"  [PASS] Found plugin: {p['name']} (roles: {p['roles']})")
        else:
            print(
                "  [WARN] No vendor plugins found -- install at least one (e.g., unifi, opnsense)"
            )
            all_ok = False
    except Exception as exc:
        print(f"  [FAIL] Plugin discovery failed: {exc}")
        all_ok = False

    print()
    if all_ok:
        print("netex: health check PASSED")
        return 0
    else:
        print("netex: health check FAILED (see above)")
        return 1


# ---------------------------------------------------------------------------
# MCP server
# ---------------------------------------------------------------------------

# The server instance is created at module level so that tool modules
# (imported in later tasks) can decorate their handlers with @mcp.tool().
mcp_server = FastMCP(
    name="netex",
    instructions=(
        "Cross-vendor network orchestration umbrella. Coordinates installed "
        "vendor plugins (unifi, opnsense, and future vendors) to perform "
        "operations that span multiple network systems. Provides unified "
        "topology, health, VLAN provisioning, cross-vendor security audits, "
        "and policy synchronization."
    ),
)


# ---------------------------------------------------------------------------
# Plugin Registry entry point
# ---------------------------------------------------------------------------


def plugin_info() -> dict[str, Any]:
    """Return plugin metadata for Netex Plugin Registry discovery.

    Called via the ``netex.plugins`` entry-point group defined in
    ``pyproject.toml``.  Unlike vendor plugins, netex is the orchestrator --
    it does not declare vendor, roles, or skills.  It discovers and
    orchestrates any plugin that conforms to the Vendor Plugin Contract.
    """
    return {
        "name": "netex",
        "version": "0.3.0",
        "description": (
            "Cross-vendor network orchestration umbrella -- topology, "
            "health, VLAN provisioning, security audits, policy sync"
        ),
        "contract_version": "1.0.0",
        "is_orchestrator": True,
        "server_factory": lambda: mcp_server,
    }


# ---------------------------------------------------------------------------
# CLI & main
# ---------------------------------------------------------------------------


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="netex-server",
        description="Netex cross-vendor orchestration MCP server",
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
    """Entry point for the ``netex-server`` console script.

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
    import netex.tools  # noqa: F401

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

    write_enabled = config.get("NETEX_WRITE_ENABLED", "false").lower() == "true"
    cache_ttl = int(config.get("NETEX_CACHE_TTL", "300"))

    logger.info(
        "Starting Netex MCP server",
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
