# SPDX-License-Identifier: MIT
"""Async SNMP client for Cisco SG-300 managed switches.

Wraps the pysnmp-lextudio v6 async API with:

- **SNMPv2c** authentication using a community string from
  ``CISCO_SNMP_COMMUNITY`` (defaults to ``"public"``).
- **Three query methods**: :meth:`get`, :meth:`get_bulk`, and :meth:`walk`.
- **Error mapping** into the plugin error hierarchy
  (:class:`~cisco.errors.NetworkError`, :class:`~cisco.errors.AuthenticationError`).
- **Module-level factory** :func:`get_snmp_client` that reads environment
  variables once and returns a reusable client instance.

Usage::

    from cisco.snmp import get_snmp_client

    client = get_snmp_client()
    value = await client.get("1.3.6.1.2.1.1.1.0")
    rows  = await client.walk("1.3.6.1.2.1.2.2.1.2")
"""

from __future__ import annotations

import logging
import os
from typing import Any

from pysnmp.hlapi.asyncio import (  # type: ignore[import-untyped]
    CommunityData,
    ContextData,
    ObjectIdentity,
    ObjectType,
    SnmpEngine,
    UdpTransportTarget,
    bulkCmd,
    getCmd,
    walkCmd,
)

from cisco.errors import AuthenticationError, NetworkError

logger = logging.getLogger(__name__)

# SNMP port used by the SG-300 (standard)
_SNMP_PORT = 161


class CiscoSNMPClient:
    """Async SNMPv2c client for Cisco SG-300 switches.

    Parameters
    ----------
    host:
        IP address or hostname of the switch.
    community:
        SNMPv2c community string.
    port:
        UDP port for SNMP (default 161).
    """

    def __init__(
        self,
        host: str,
        community: str = "public",
        port: int = _SNMP_PORT,
    ) -> None:
        self._host = host
        self._community = community
        self._port = port
        self._engine = SnmpEngine()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _community_data(self) -> CommunityData:
        """Build the SNMPv2c community data object."""
        return CommunityData(self._community, mpModel=1)  # mpModel=1 -> SNMPv2c

    def _transport_target(self) -> UdpTransportTarget:
        """Build the UDP transport target."""
        return UdpTransportTarget((self._host, self._port))

    @staticmethod
    def _context_data() -> ContextData:
        """Build the default SNMP context data."""
        return ContextData()

    @staticmethod
    def _check_error(
        error_indication: Any,
        error_status: Any,
        error_index: Any,
    ) -> None:
        """Raise an appropriate plugin error for SNMP-level failures.

        Parameters
        ----------
        error_indication:
            Transport-level error string from pysnmp (e.g. timeout).
        error_status:
            Protocol-level error status integer.
        error_index:
            Index of the varbind that caused the error.

        Raises
        ------
        NetworkError
            If *error_indication* is truthy (timeout, unreachable, etc.).
        NetworkError
            If *error_status* indicates a protocol error.
        """
        if error_indication:
            raise NetworkError(
                f"SNMP transport error: {error_indication}",
                retry_hint="Verify the switch is reachable and SNMP is enabled",
            )
        if error_status:
            raise NetworkError(
                f"SNMP error: {error_status.prettyPrint()} at index {error_index}",
                endpoint=None,
                retry_hint="Check OID validity and SNMP community access rights",
            )

    # ------------------------------------------------------------------
    # Public query methods
    # ------------------------------------------------------------------

    async def get(self, oid: str) -> Any:
        """Perform an SNMP GET for a single OID.

        Parameters
        ----------
        oid:
            Numeric OID string (e.g. ``"1.3.6.1.2.1.1.1.0"``).

        Returns
        -------
        Any
            The value returned by the SNMP agent.  The caller is
            responsible for interpreting the pysnmp value type.

        Raises
        ------
        NetworkError
            On transport errors or SNMP protocol errors.
        """
        try:
            error_indication, error_status, error_index, var_binds = await getCmd(
                self._engine,
                self._community_data(),
                self._transport_target(),
                self._context_data(),
                ObjectType(ObjectIdentity(oid)),
            )
        except NetworkError:
            raise
        except Exception as exc:
            raise NetworkError(
                f"SNMP GET failed for OID {oid}: {exc}",
                endpoint=self._host,
                retry_hint="Check network connectivity and SNMP configuration",
                details={"oid": oid, "original_error": str(exc)},
            ) from exc

        self._check_error(error_indication, error_status, error_index)

        # getCmd returns a single row of var_binds
        for var_bind in var_binds:
            return var_bind[1]

        return None  # pragma: no cover - defensive; getCmd always returns binds

    async def get_bulk(
        self,
        oid: str,
        max_repetitions: int = 25,
    ) -> list[tuple[str, Any]]:
        """Perform an SNMP GETBULK request.

        Retrieves up to *max_repetitions* rows starting from *oid* in a
        single PDU, which is significantly faster than individual GET-NEXT
        calls for table columns.

        Parameters
        ----------
        oid:
            Base OID to start the bulk walk from.
        max_repetitions:
            Maximum number of rows to retrieve per PDU.

        Returns
        -------
        list[tuple[str, Any]]
            List of ``(oid_string, value)`` pairs.

        Raises
        ------
        NetworkError
            On transport errors or SNMP protocol errors.
        """
        results: list[tuple[str, Any]] = []
        try:
            error_indication, error_status, error_index, var_bind_table = await bulkCmd(
                self._engine,
                self._community_data(),
                self._transport_target(),
                self._context_data(),
                0,  # nonRepeaters
                max_repetitions,
                ObjectType(ObjectIdentity(oid)),
            )
        except NetworkError:
            raise
        except Exception as exc:
            raise NetworkError(
                f"SNMP GETBULK failed for OID {oid}: {exc}",
                endpoint=self._host,
                retry_hint="Check network connectivity and SNMP configuration",
                details={"oid": oid, "original_error": str(exc)},
            ) from exc

        self._check_error(error_indication, error_status, error_index)

        for var_bind in var_bind_table:
            oid_str = str(var_bind[0])
            results.append((oid_str, var_bind[1]))

        return results

    async def walk(self, oid: str) -> list[tuple[str, Any]]:
        """Perform an SNMP walk (repeated GET-NEXT) over a subtree.

        Walks the entire subtree rooted at *oid* using the pysnmp
        ``walkCmd`` async generator.  Stops automatically when the
        returned OID leaves the requested subtree.

        Parameters
        ----------
        oid:
            Base OID of the subtree to walk.

        Returns
        -------
        list[tuple[str, Any]]
            List of ``(oid_string, value)`` tuples for every entry in the
            subtree.

        Raises
        ------
        NetworkError
            On transport errors or SNMP protocol errors.
        """
        results: list[tuple[str, Any]] = []
        base_oid = oid

        try:
            async for error_indication, error_status, error_index, var_binds in walkCmd(
                self._engine,
                self._community_data(),
                self._transport_target(),
                self._context_data(),
                ObjectType(ObjectIdentity(oid)),
            ):
                self._check_error(error_indication, error_status, error_index)

                for var_bind in var_binds:
                    oid_str = str(var_bind[0])
                    # Stop if we've walked past the requested subtree
                    if not oid_str.startswith(base_oid + "."):
                        return results
                    results.append((oid_str, var_bind[1]))
        except NetworkError:
            raise
        except Exception as exc:
            raise NetworkError(
                f"SNMP walk failed for OID {oid}: {exc}",
                endpoint=self._host,
                retry_hint="Check network connectivity and SNMP configuration",
                details={"oid": oid, "original_error": str(exc)},
            ) from exc

        return results


# ---------------------------------------------------------------------------
# Singleton factory
# ---------------------------------------------------------------------------

_client: CiscoSNMPClient | None = None


def get_snmp_client() -> CiscoSNMPClient:
    """Get or create the singleton SNMP client from environment variables.

    Environment Variables
    ---------------------
    CISCO_HOST : str
        IP address or hostname of the Cisco SG-300 switch.  **Required.**
    CISCO_SNMP_COMMUNITY : str, optional
        SNMPv2c community string.  Defaults to ``"public"``.

    Returns
    -------
    CiscoSNMPClient
        The singleton client instance.

    Raises
    ------
    AuthenticationError
        If ``CISCO_HOST`` is not set.
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

    community = os.environ.get("CISCO_SNMP_COMMUNITY", "public")

    _client = CiscoSNMPClient(host=host, community=community)
    return _client
