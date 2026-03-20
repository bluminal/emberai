"""OPNsense data models.

Re-exports all Pydantic models used to normalize OPNsense API responses into
clean Python objects. Every model uses strict mode and field aliases so that
raw API payloads can be parsed directly while downstream code uses
Pythonic attribute names.

Usage::

    from opnsense.models import Interface, FirewallRule, Route, DHCPLease
    from opnsense.models import IPSecSession, FirmwareStatus

    interface = Interface.model_validate(raw_api_response)
    print(interface.name)  # normalized field name
"""

from opnsense.models.firewall import Alias, FirewallRule, NATRule
from opnsense.models.firmware import FirmwareStatus
from opnsense.models.interface import Interface
from opnsense.models.routing import Gateway, Route
from opnsense.models.security import Certificate, IDSAlert
from opnsense.models.services import DHCPLease, DNSOverride
from opnsense.models.vlan_interface import VLANInterface
from opnsense.models.vpn import IPSecSession, OpenVPNInstance, WireGuardPeer

__all__ = [
    "Alias",
    "Certificate",
    "DHCPLease",
    "DNSOverride",
    "FirewallRule",
    "FirmwareStatus",
    "Gateway",
    "IDSAlert",
    "IPSecSession",
    "Interface",
    "NATRule",
    "OpenVPNInstance",
    "Route",
    "VLANInterface",
    "WireGuardPeer",
]
