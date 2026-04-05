"""SNMP client layer for Cisco SG-300 monitoring and polling.

Provides an async SNMPv2c client, numeric OID constants for all
relevant MIBs, and mapper functions that convert raw SNMP walk data
into typed Pydantic models.

Usage::

    from cisco.snmp import get_snmp_client, map_interface_counters
    from cisco.snmp.oids import IF_MIB

    client = get_snmp_client()
    descr = await client.walk(IF_MIB.ifDescr)
"""

from cisco.snmp.client import CiscoSNMPClient, get_snmp_client
from cisco.snmp.mappers import map_interface_counters, map_lldp_neighbors, map_mac_table

__all__ = [
    "CiscoSNMPClient",
    "get_snmp_client",
    "map_interface_counters",
    "map_lldp_neighbors",
    "map_mac_table",
]
