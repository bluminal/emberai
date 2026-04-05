# SPDX-License-Identifier: MIT
# ruff: noqa: N801, N815
"""SNMP OID constants for Cisco SG-300 managed switches.

All OIDs use numeric dot notation so they work without MIB files loaded
on the target device.  Grouped by MIB module for readability.

Class names (``IF_MIB``, ``LLDP_MIB``, etc.) and attribute names
(``ifDescr``, ``sysName``, etc.) intentionally match RFC/MIB naming
conventions rather than PEP 8 to keep parity with SNMP documentation.

Usage::

    from cisco.snmp.oids import IF_MIB, LLDP_MIB

    await client.walk(IF_MIB.ifDescr)
"""


# ---------------------------------------------------------------------------
# IF-MIB  (1.3.6.1.2.1.2.2.1.*)
# ---------------------------------------------------------------------------


class IF_MIB:
    """Interface statistics from IF-MIB (RFC 2863)."""

    ifDescr = "1.3.6.1.2.1.2.2.1.2"
    ifType = "1.3.6.1.2.1.2.2.1.3"
    ifSpeed = "1.3.6.1.2.1.2.2.1.5"
    ifAdminStatus = "1.3.6.1.2.1.2.2.1.7"
    ifOperStatus = "1.3.6.1.2.1.2.2.1.8"
    ifInOctets = "1.3.6.1.2.1.2.2.1.10"
    ifOutOctets = "1.3.6.1.2.1.2.2.1.16"
    ifInErrors = "1.3.6.1.2.1.2.2.1.14"
    ifOutErrors = "1.3.6.1.2.1.2.2.1.20"
    ifInDiscards = "1.3.6.1.2.1.2.2.1.13"
    ifOutDiscards = "1.3.6.1.2.1.2.2.1.19"
    ifInUcastPkts = "1.3.6.1.2.1.2.2.1.11"
    ifOutUcastPkts = "1.3.6.1.2.1.2.2.1.17"


# ---------------------------------------------------------------------------
# BRIDGE-MIB  (1.3.6.1.2.1.17.*)
# ---------------------------------------------------------------------------


class BRIDGE_MIB:
    """Transparent bridge MAC table from BRIDGE-MIB (RFC 4188)."""

    dot1dTpFdbAddress = "1.3.6.1.2.1.17.4.3.1.1"
    dot1dTpFdbPort = "1.3.6.1.2.1.17.4.3.1.2"


# ---------------------------------------------------------------------------
# Q-BRIDGE-MIB  (1.3.6.1.2.1.17.7.1.*)
# ---------------------------------------------------------------------------


class Q_BRIDGE_MIB:
    """802.1Q VLAN-aware bridge table from Q-BRIDGE-MIB (RFC 4363)."""

    dot1qTpFdbPort = "1.3.6.1.2.1.17.7.1.2.2.1.2"
    dot1qPvid = "1.3.6.1.2.1.17.7.1.4.5.1.1"
    dot1qVlanStaticName = "1.3.6.1.2.1.17.7.1.4.3.1.1"


# ---------------------------------------------------------------------------
# LLDP-MIB  (1.0.8802.1.1.2.*)
# ---------------------------------------------------------------------------


class LLDP_MIB:
    """Link Layer Discovery Protocol from LLDP-MIB (IEEE 802.1AB)."""

    lldpRemSysName = "1.0.8802.1.1.2.1.4.1.1.9"
    lldpRemPortId = "1.0.8802.1.1.2.1.4.1.1.7"
    lldpRemPortDesc = "1.0.8802.1.1.2.1.4.1.1.8"
    lldpRemSysCapEnabled = "1.0.8802.1.1.2.1.4.1.1.12"
    lldpRemManAddrIfId = "1.0.8802.1.1.2.1.4.2.1.4"


# ---------------------------------------------------------------------------
# SNMPv2-MIB  (1.3.6.1.2.1.1.*)
# ---------------------------------------------------------------------------


class SNMPv2_MIB:
    """System identity from SNMPv2-MIB (RFC 3418)."""

    sysDescr = "1.3.6.1.2.1.1.1"
    sysUpTime = "1.3.6.1.2.1.1.3"
    sysName = "1.3.6.1.2.1.1.5"
    sysContact = "1.3.6.1.2.1.1.4"
    sysLocation = "1.3.6.1.2.1.1.6"


# ---------------------------------------------------------------------------
# ENTITY-MIB  (1.3.6.1.2.1.47.1.1.1.1.*)
# ---------------------------------------------------------------------------


class ENTITY_MIB:
    """Physical entity details from ENTITY-MIB (RFC 6933)."""

    entPhysicalSerialNum = "1.3.6.1.2.1.47.1.1.1.1.11"
    entPhysicalModelName = "1.3.6.1.2.1.47.1.1.1.1.13"
    entPhysicalHardwareRev = "1.3.6.1.2.1.47.1.1.1.1.8"
