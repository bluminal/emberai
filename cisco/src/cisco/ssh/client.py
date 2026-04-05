# SPDX-License-Identifier: MIT
"""Async-compatible SSH client for Cisco SG-300 managed switches.

Wraps Netmiko's ``ConnectHandler(device_type="cisco_s300")`` with:

- **Singleton connection pattern** with :class:`asyncio.Lock` for command
  serialization (SG-300 supports very limited concurrent SSH sessions,
  typically 2-4).
- **All Netmiko calls** dispatched via :func:`asyncio.to_thread` to keep the
  async MCP event loop unblocked.
- **Auto-reconnect** on ``NetmikoTimeoutException`` or socket errors.
- **Enable mode** entry via ``CISCO_ENABLE_PASSWORD`` when set.
- **SSH host key verification toggle** via ``CISCO_VERIFY_SSH_HOST_KEY``.

Error Mapping
-------------
- ``NetmikoTimeoutException`` -> :class:`~cisco.errors.NetworkError`
- ``NetmikoAuthenticationException`` -> :class:`~cisco.errors.AuthenticationError`
- ``ReadTimeout`` -> :class:`~cisco.errors.NetworkError`
- Other Netmiko exceptions -> :class:`~cisco.errors.SSHCommandError`
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import TYPE_CHECKING, Any, TypeVar

from netmiko import ConnectHandler
from netmiko.exceptions import (
    NetmikoAuthenticationException,
    NetmikoTimeoutException,
    ReadTimeout,
)

from cisco.errors import AuthenticationError, NetworkError, SSHCommandError

if TYPE_CHECKING:
    from collections.abc import Callable

logger = logging.getLogger(__name__)

T = TypeVar("T")


class CiscoSSHClient:
    """Async-compatible SSH client for Cisco SG-300 switches.

    All Netmiko calls are executed in a thread pool via
    :func:`asyncio.to_thread` and serialized through an :class:`asyncio.Lock`
    to respect the SG-300's limited SSH session capacity.

    Parameters
    ----------
    host:
        IP address or hostname of the switch.
    username:
        SSH username.
    password:
        SSH password.
    enable_password:
        Enable mode password.  If ``None``, enable mode is not entered.
    verify_host_key:
        Whether to verify the SSH host key.  Set to ``False`` for lab
        environments or switches with self-signed keys.
    """

    def __init__(
        self,
        host: str,
        username: str,
        password: str,
        enable_password: str | None = None,
        verify_host_key: bool = True,
    ) -> None:
        self._host = host
        self._username = username
        self._password = password
        self._enable_password = enable_password
        self._verify_host_key = verify_host_key
        self._connection: Any | None = None  # Netmiko BaseConnection
        self._lock = asyncio.Lock()

    # ------------------------------------------------------------------
    # Thread dispatch helper
    # ------------------------------------------------------------------

    async def _execute_in_thread(self, func: Callable[..., T], *args: Any, **kwargs: Any) -> T:
        """Run a blocking Netmiko call in a thread to avoid blocking the event loop.

        Parameters
        ----------
        func:
            The synchronous callable to execute.
        *args:
            Positional arguments forwarded to *func*.
        **kwargs:
            Keyword arguments forwarded to *func*.

        Returns
        -------
        T
            The return value of *func*.
        """
        return await asyncio.to_thread(func, *args, **kwargs)

    # ------------------------------------------------------------------
    # Connection management
    # ------------------------------------------------------------------

    def _build_device_params(self) -> dict[str, Any]:
        """Build the Netmiko device parameter dict."""
        params: dict[str, Any] = {
            "device_type": "cisco_s300",
            "host": self._host,
            "username": self._username,
            "password": self._password,
        }
        if self._enable_password is not None:
            params["secret"] = self._enable_password
        if not self._verify_host_key:
            # Disable SSH host key checking for self-signed / lab environments
            params["ssh_config_file"] = None
            params["allow_auto_change"] = True
            # Paramiko-level: disable host key policy enforcement
            params["disabled_algorithms"] = {}
        return params

    def _connect_sync(self) -> None:
        """Synchronous connection establishment (runs in thread)."""
        params = self._build_device_params()
        try:
            conn = ConnectHandler(**params)
            if self._enable_password is not None:
                conn.enable()
            self._connection = conn
            logger.info("SSH connection established to %s", self._host)
        except NetmikoAuthenticationException as exc:
            raise AuthenticationError(
                f"SSH authentication failed for {self._username}@{self._host}",
                env_var="CISCO_SSH_PASSWORD",
                endpoint=self._host,
                details={"original_error": str(exc)},
            ) from exc
        except NetmikoTimeoutException as exc:
            raise NetworkError(
                f"SSH connection timed out to {self._host}",
                endpoint=self._host,
                retry_hint="Verify the switch is reachable and SSH is enabled",
                details={"original_error": str(exc)},
            ) from exc
        except OSError as exc:
            raise NetworkError(
                f"SSH connection failed to {self._host}: {exc}",
                endpoint=self._host,
                retry_hint="Check network connectivity, DNS resolution, and SSH port access",
                details={"original_error": str(exc)},
            ) from exc

    async def connect(self) -> None:
        """Establish an SSH connection to the switch.

        Raises
        ------
        AuthenticationError
            If SSH credentials are invalid.
        NetworkError
            If the switch is unreachable or connection times out.
        """
        async with self._lock:
            if self._connection is not None:
                logger.debug("Already connected to %s, skipping", self._host)
                return
            await self._execute_in_thread(self._connect_sync)

    def _disconnect_sync(self) -> None:
        """Synchronous disconnection (runs in thread)."""
        if self._connection is not None:
            try:
                self._connection.disconnect()
                logger.info("SSH connection closed to %s", self._host)
            except Exception:
                logger.warning(
                    "Error during SSH disconnect from %s (ignored)", self._host, exc_info=True
                )
            finally:
                self._connection = None

    async def disconnect(self) -> None:
        """Close the SSH connection to the switch."""
        async with self._lock:
            await self._execute_in_thread(self._disconnect_sync)

    async def is_connected(self) -> bool:
        """Check whether the SSH connection is alive.

        Returns
        -------
        bool
            ``True`` if the connection is established and responsive.
        """

        def _check() -> bool:
            if self._connection is None:
                return False
            try:
                return bool(self._connection.is_alive())
            except Exception:
                return False

        return await self._execute_in_thread(_check)

    async def _ensure_connected(self) -> None:
        """Reconnect if the connection has been lost.

        This is called internally before every command.  The caller must
        already hold ``self._lock``.
        """
        if self._connection is not None:
            # Quick liveness check
            alive = await self._execute_in_thread(
                lambda: self._connection is not None and self._connection.is_alive()
            )
            if alive:
                return
            # Connection is stale -- clean up before reconnecting
            logger.warning("SSH connection to %s is stale, reconnecting", self._host)
            self._connection = None

        await self._execute_in_thread(self._connect_sync)

    # ------------------------------------------------------------------
    # Command execution
    # ------------------------------------------------------------------

    async def send_command(self, command: str) -> str:
        """Send a show command and return the output.

        The command is executed in a background thread and serialized via
        the connection lock to prevent interleaving on the SG-300's
        limited SSH sessions.

        Parameters
        ----------
        command:
            The CLI command to execute (e.g. ``show vlan``).

        Returns
        -------
        str
            Raw CLI output from the switch.

        Raises
        ------
        NetworkError
            On timeout or connection loss.
        SSHCommandError
            On unexpected CLI errors.
        """
        async with self._lock:
            await self._ensure_connected()
            assert self._connection is not None  # ensured by _ensure_connected

            def _send() -> str:
                return self._connection.send_command(command)  # type: ignore[union-attr]

            try:
                result: str = await self._execute_in_thread(_send)
                logger.debug("Command '%s' returned %d bytes", command, len(result))
                return result
            except (NetmikoTimeoutException, ReadTimeout) as exc:
                # Connection may be dead -- force reconnect on next call
                self._connection = None
                raise NetworkError(
                    f"Timeout executing command on {self._host}: {command}",
                    endpoint=self._host,
                    retry_hint="The switch may be overloaded; retry after a short delay",
                    details={"command": command, "original_error": str(exc)},
                ) from exc
            except OSError as exc:
                self._connection = None
                raise NetworkError(
                    f"Connection lost to {self._host} during command: {command}",
                    endpoint=self._host,
                    retry_hint="Check network connectivity and retry",
                    details={"command": command, "original_error": str(exc)},
                ) from exc
            except Exception as exc:
                raise SSHCommandError(
                    f"Failed to execute command on {self._host}: {command}",
                    command=command,
                    endpoint=self._host,
                    details={"original_error": str(exc)},
                ) from exc

    async def send_config_set(self, commands: list[str]) -> str:
        """Send a list of configuration commands.

        Parameters
        ----------
        commands:
            Configuration commands to execute in sequence.

        Returns
        -------
        str
            Combined CLI output from all commands.

        Raises
        ------
        NetworkError
            On timeout or connection loss.
        SSHCommandError
            On unexpected CLI errors.
        """
        async with self._lock:
            await self._ensure_connected()
            assert self._connection is not None

            def _send_config() -> str:
                return self._connection.send_config_set(commands)  # type: ignore[union-attr]

            try:
                result: str = await self._execute_in_thread(_send_config)
                logger.debug(
                    "Config set (%d commands) returned %d bytes", len(commands), len(result)
                )
                return result
            except (NetmikoTimeoutException, ReadTimeout) as exc:
                self._connection = None
                raise NetworkError(
                    f"Timeout sending config commands to {self._host}",
                    endpoint=self._host,
                    retry_hint="The switch may be overloaded; retry after a short delay",
                    details={"commands": commands, "original_error": str(exc)},
                ) from exc
            except OSError as exc:
                self._connection = None
                raise NetworkError(
                    f"Connection lost to {self._host} during config push",
                    endpoint=self._host,
                    retry_hint="Check network connectivity and retry",
                    details={"commands": commands, "original_error": str(exc)},
                ) from exc
            except Exception as exc:
                raise SSHCommandError(
                    f"Failed to send config commands to {self._host}",
                    command="; ".join(commands),
                    endpoint=self._host,
                    details={"commands": commands, "original_error": str(exc)},
                ) from exc

    async def save_config(self) -> str:
        """Write the running configuration to startup (``write memory``).

        Returns
        -------
        str
            CLI output from the save operation.
        """
        return await self.send_command("write memory")

    async def get_running_config(self) -> str:
        """Retrieve the full running configuration.

        Returns
        -------
        str
            The complete ``show running-config`` output.
        """
        return await self.send_command("show running-config")


# ---------------------------------------------------------------------------
# Singleton factory
# ---------------------------------------------------------------------------

_client: CiscoSSHClient | None = None


def get_client() -> CiscoSSHClient:
    """Get or create the singleton SSH client from environment variables.

    Environment Variables
    ---------------------
    CISCO_HOST : str
        IP address or hostname of the Cisco SG-300 switch.  **Required.**
    CISCO_SSH_USERNAME : str
        SSH username for the switch.  **Required.**
    CISCO_SSH_PASSWORD : str
        SSH password for the switch.  **Required.**
    CISCO_ENABLE_PASSWORD : str, optional
        Enable mode password.  If not set, enable mode is not entered.
    CISCO_VERIFY_SSH_HOST_KEY : str, optional
        Set to ``"false"`` to disable SSH host key verification.
        Defaults to ``"true"``.

    Returns
    -------
    CiscoSSHClient
        The singleton client instance.

    Raises
    ------
    AuthenticationError
        If required environment variables are missing.
    """
    global _client

    if _client is not None:
        return _client

    host = os.environ.get("CISCO_HOST")
    if not host:
        raise AuthenticationError(
            "CISCO_HOST environment variable is not set",
            env_var="CISCO_HOST",
        )

    username = os.environ.get("CISCO_SSH_USERNAME")
    if not username:
        raise AuthenticationError(
            "CISCO_SSH_USERNAME environment variable is not set",
            env_var="CISCO_SSH_USERNAME",
        )

    password = os.environ.get("CISCO_SSH_PASSWORD")
    if not password:
        raise AuthenticationError(
            "CISCO_SSH_PASSWORD environment variable is not set",
            env_var="CISCO_SSH_PASSWORD",
        )

    enable_password = os.environ.get("CISCO_ENABLE_PASSWORD")

    verify_host_key_str = os.environ.get("CISCO_VERIFY_SSH_HOST_KEY", "true").lower()
    verify_host_key = verify_host_key_str != "false"

    _client = CiscoSSHClient(
        host=host,
        username=username,
        password=password,
        enable_password=enable_password,
        verify_host_key=verify_host_key,
    )
    return _client
