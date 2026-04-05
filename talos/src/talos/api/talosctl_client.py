"""Async subprocess wrapper for the ``talosctl`` CLI.

Unlike other EmberAI plugins that use ``httpx`` to call REST APIs, the Talos
plugin wraps ``talosctl`` via ``asyncio.create_subprocess_exec``.  Talos
communicates over gRPC + mTLS, and ``talosctl`` is the canonical management
interface.

Usage::

    client = TalosCtlClient()
    result = await client.run(["version"], nodes="192.168.100.10")
    print(result.parsed)  # parsed JSON output
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from talos.cache import TTLCache
from talos.errors import (
    AuthenticationError,
    ConfigParseError,
    NetworkError,
    TalosCtlError,
    TalosCtlNotFoundError,
)

logger = logging.getLogger("talos.api")

# ---------------------------------------------------------------------------
# Result container
# ---------------------------------------------------------------------------


@dataclass
class TalosCtlResult:
    """Container for the result of a ``talosctl`` subprocess invocation.

    Attributes:
        stdout: Raw standard output from the process.
        stderr: Raw standard error from the process.
        exit_code: Process exit code (0 = success).
        parsed: Parsed JSON output, or ``None`` if output was not JSON.
    """

    stdout: str
    stderr: str
    exit_code: int
    parsed: dict[str, Any] | list[Any] | None = None


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------


class TalosCtlClient:
    """Async wrapper for ``talosctl`` CLI commands.

    Handles:
    - Command construction with talosconfig, context, nodes, endpoints
    - JSON / NDJSON output parsing with text fallback
    - Talosconfig context management
    - Node targeting priority (explicit > env var > talosconfig)
    - TTL cache integration for read-only commands
    - Binary validation on init

    Args:
        config_path: Path to the talosconfig file.  Falls back to
            ``TALOS_CONFIG`` env var, then ``~/.talos/config``.
        context: Named context within the talosconfig.  Falls back to
            ``TALOS_CONTEXT`` env var, then the file's current context.
        cache: Optional TTL cache instance for caching read results.
    """

    def __init__(
        self,
        config_path: str | None = None,
        context: str | None = None,
        cache: TTLCache | None = None,
    ) -> None:
        self._config_path = (
            config_path
            or os.environ.get("TALOS_CONFIG", "")
            or str(Path.home() / ".talos" / "config")
        )
        self._context = context or os.environ.get("TALOS_CONTEXT", "")
        self._cache = cache
        self._binary_path: str | None = None
        self._client_version: str | None = None
        self._talosconfig_data: dict[str, Any] | None = None

    # ------------------------------------------------------------------
    # Binary validation
    # ------------------------------------------------------------------

    def _find_binary(self) -> str:
        """Locate the ``talosctl`` binary on PATH.

        Raises :class:`TalosCtlNotFoundError` if not found.
        """
        if self._binary_path is not None:
            return self._binary_path

        path = shutil.which("talosctl")
        if path is None:
            raise TalosCtlNotFoundError()
        self._binary_path = path
        return path

    async def validate_binary(self) -> str:
        """Verify ``talosctl`` is installed and return the client version.

        Runs ``talosctl version --client --short`` and caches the result.

        Returns:
            The talosctl client version string.

        Raises:
            TalosCtlNotFoundError: If the binary is not on PATH.
            TalosCtlError: If the version command fails.
        """
        if self._client_version is not None:
            return self._client_version

        binary = self._find_binary()
        proc = await asyncio.create_subprocess_exec(
            binary, "version", "--client", "--short",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout_bytes, stderr_bytes = await asyncio.wait_for(proc.communicate(), timeout=10)
        stdout = stdout_bytes.decode().strip()
        stderr = stderr_bytes.decode().strip()

        if proc.returncode != 0:
            raise TalosCtlError(
                f"talosctl version check failed: {stderr}",
                command=["talosctl", "version", "--client", "--short"],
                stderr=stderr,
                exit_code=proc.returncode,
            )

        self._client_version = stdout
        return stdout

    # ------------------------------------------------------------------
    # Talosconfig management
    # ------------------------------------------------------------------

    def _load_talosconfig(self) -> dict[str, Any]:
        """Parse the talosconfig YAML file and cache the result."""
        if self._talosconfig_data is not None:
            return self._talosconfig_data

        path = Path(self._config_path)
        if not path.exists():
            raise AuthenticationError(
                f"talosconfig not found at {self._config_path}",
                config_path=self._config_path,
            )

        try:
            data = yaml.safe_load(path.read_text())
        except Exception as exc:
            raise AuthenticationError(
                f"Failed to parse talosconfig: {exc}",
                config_path=self._config_path,
            ) from exc

        if not isinstance(data, dict):
            raise AuthenticationError(
                "talosconfig is not a valid YAML mapping",
                config_path=self._config_path,
            )

        self._talosconfig_data = data
        return data

    def get_contexts(self) -> list[str]:
        """Return the list of available context names in the talosconfig."""
        data = self._load_talosconfig()
        contexts = data.get("contexts", {})
        return list(contexts.keys()) if isinstance(contexts, dict) else []

    def get_current_context(self) -> str:
        """Return the active context name.

        Priority: explicit context > TALOS_CONTEXT env var > talosconfig default.
        """
        if self._context:
            return self._context
        data = self._load_talosconfig()
        return str(data.get("context", ""))

    # ------------------------------------------------------------------
    # Node targeting
    # ------------------------------------------------------------------

    def get_default_nodes(self) -> list[str]:
        """Resolve default target nodes.

        Priority:
        1. ``TALOS_NODES`` env var (comma-separated)
        2. Nodes from the current talosconfig context
        """
        env_nodes = os.environ.get("TALOS_NODES", "").strip()
        if env_nodes:
            return [n.strip() for n in env_nodes.split(",") if n.strip()]

        try:
            data = self._load_talosconfig()
            ctx_name = self.get_current_context()
            contexts = data.get("contexts", {})
            if isinstance(contexts, dict) and ctx_name in contexts:
                ctx = contexts[ctx_name]
                nodes = ctx.get("nodes", [])
                if isinstance(nodes, list):
                    return [str(n) for n in nodes]
        except AuthenticationError:
            pass

        return []

    # ------------------------------------------------------------------
    # JSON parsing
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_json_output(stdout: str) -> dict[str, Any] | list[Any] | None:
        """Parse talosctl JSON output.

        Handles three output formats:
        1. Single JSON object
        2. JSON array
        3. Newline-delimited JSON (NDJSON) -- one object per node

        Returns ``None`` if parsing fails (caller should use raw text).
        """
        text = stdout.strip()
        if not text:
            return None

        # Try standard JSON first (object or array)
        try:
            parsed = json.loads(text)
            if isinstance(parsed, (dict, list)):
                return parsed
        except json.JSONDecodeError:
            pass

        # Try NDJSON (one JSON object per line)
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        if len(lines) > 1:
            objects: list[Any] = []
            for line in lines:
                try:
                    objects.append(json.loads(line))
                except json.JSONDecodeError:
                    return None  # Not valid NDJSON either
            return objects

        return None

    # ------------------------------------------------------------------
    # Core run method
    # ------------------------------------------------------------------

    async def run(
        self,
        args: list[str],
        *,
        nodes: str | list[str] | None = None,
        endpoints: str | list[str] | None = None,
        json_output: bool = True,
        timeout: float = 30.0,
        use_cache: bool = True,
    ) -> TalosCtlResult:
        """Execute a ``talosctl`` command and return the result.

        Constructs the full command with talosconfig, context, nodes,
        endpoints, and optional JSON output flag.

        Args:
            args: Command arguments (e.g. ``["version"]``, ``["get", "members"]``).
            nodes: Target node(s).  Falls back to default nodes.
            endpoints: Override talosconfig endpoints.
            json_output: Request JSON output via ``-o json`` (default True).
            timeout: Subprocess timeout in seconds (default 30).
            use_cache: Check/populate the TTL cache for read commands (default True).

        Returns:
            A :class:`TalosCtlResult` with stdout, stderr, exit code, and
            parsed JSON (if available).

        Raises:
            TalosCtlNotFoundError: If ``talosctl`` is not on PATH.
            TalosCtlError: If the command exits with a non-zero code.
            NetworkError: If the subprocess times out.
        """
        binary = self._find_binary()

        # Build node list
        node_list: list[str] = []
        if isinstance(nodes, str):
            node_list = [nodes]
        elif isinstance(nodes, list):
            node_list = nodes

        # Build full command
        cmd: list[str] = [binary]

        if self._config_path:
            cmd.extend(["--talosconfig", self._config_path])

        effective_context = self.get_current_context() if self._context else ""
        if effective_context:
            cmd.extend(["--context", effective_context])

        if node_list:
            cmd.extend(["--nodes", ",".join(node_list)])

        if endpoints:
            ep_list = [endpoints] if isinstance(endpoints, str) else endpoints
            cmd.extend(["--endpoints", ",".join(ep_list)])

        if json_output:
            cmd.extend(["-o", "json"])

        cmd.extend(args)

        # Cache check (read-only commands only)
        cache_key: str | None = None
        is_write_cmd = any(
            w in args for w in [
                "apply-config", "bootstrap", "reboot", "shutdown", "reset",
                "upgrade", "patch", "edit", "etcd", "rotate-ca", "wipe",
            ]
        )
        # Also skip cache for streaming flags
        has_streaming = any(f in args for f in ["--follow", "-f", "--tail"])

        if self._cache and use_cache and not is_write_cmd and not has_streaming:
            cache_key = f"talosctl:{':'.join(args)}:{':'.join(node_list)}"
            cached = await self._cache.get(cache_key)
            if cached is not None:
                return cached

        # Execute subprocess
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                proc.communicate(), timeout=timeout
            )
        except asyncio.TimeoutError:
            raise NetworkError(
                f"talosctl command timed out after {timeout}s",
                endpoint=",".join(node_list) if node_list else None,
                retry_hint=f"Command timed out: {' '.join(cmd[:6])}... "
                f"Try increasing timeout or check node connectivity.",
            )

        stdout = stdout_bytes.decode() if stdout_bytes else ""
        stderr = stderr_bytes.decode() if stderr_bytes else ""
        exit_code = proc.returncode or 0

        # Handle non-zero exit
        if exit_code != 0:
            raise TalosCtlError(
                f"talosctl command failed: {stderr.strip() or 'unknown error'}",
                command=cmd,
                stderr=stderr,
                exit_code=exit_code,
                endpoint=",".join(node_list) if node_list else None,
            )

        # Parse JSON output
        parsed: dict[str, Any] | list[Any] | None = None
        if json_output and stdout.strip():
            parsed = self._parse_json_output(stdout)
            if parsed is None:
                logger.debug(
                    "JSON parse failed for command %s, falling back to raw text",
                    " ".join(args),
                )

        result = TalosCtlResult(
            stdout=stdout,
            stderr=stderr,
            exit_code=exit_code,
            parsed=parsed,
        )

        # Cache the result
        if self._cache and cache_key is not None:
            await self._cache.set(cache_key, result)

        return result

    # ------------------------------------------------------------------
    # Post-write cache flush
    # ------------------------------------------------------------------

    async def flush_cache(self, prefix: str | None = None) -> None:
        """Flush cached results after a write operation.

        Args:
            prefix: If provided, only flush keys starting with this prefix.
                If ``None``, flush all cached talosctl results.
        """
        if self._cache is None:
            return
        if prefix:
            await self._cache.flush_by_prefix(f"talosctl:{prefix}")
        else:
            await self._cache.flush_by_prefix("talosctl:")

    # ------------------------------------------------------------------
    # Convenience methods
    # ------------------------------------------------------------------

    async def run_insecure(
        self,
        args: list[str],
        *,
        nodes: str | list[str] | None = None,
        json_output: bool = True,
        timeout: float = 30.0,
    ) -> TalosCtlResult:
        """Execute a talosctl command in insecure (maintenance) mode.

        Used for first-time connections to unconfigured nodes where
        mTLS has not been established yet.
        """
        full_args = ["--insecure"] + args if "--insecure" not in args else args
        # Insecure mode bypasses talosconfig auth
        binary = self._find_binary()

        cmd: list[str] = [binary]

        if nodes:
            node_list = [nodes] if isinstance(nodes, str) else nodes
            cmd.extend(["--nodes", ",".join(node_list)])

        if json_output:
            cmd.extend(["-o", "json"])

        cmd.extend(full_args)

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                proc.communicate(), timeout=timeout
            )
        except asyncio.TimeoutError:
            node_str = ",".join([nodes] if isinstance(nodes, str) else nodes or [])
            raise NetworkError(
                f"talosctl insecure command timed out after {timeout}s",
                endpoint=node_str or None,
            )

        stdout = stdout_bytes.decode() if stdout_bytes else ""
        stderr = stderr_bytes.decode() if stderr_bytes else ""
        exit_code = proc.returncode or 0

        if exit_code != 0:
            raise TalosCtlError(
                f"talosctl command failed: {stderr.strip() or 'unknown error'}",
                command=cmd,
                stderr=stderr,
                exit_code=exit_code,
            )

        parsed = self._parse_json_output(stdout) if json_output and stdout.strip() else None

        return TalosCtlResult(
            stdout=stdout,
            stderr=stderr,
            exit_code=exit_code,
            parsed=parsed,
        )
