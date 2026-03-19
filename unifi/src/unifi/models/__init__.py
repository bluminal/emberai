"""UniFi data models.

Re-exports all Pydantic models used to normalize UniFi API responses into
clean Python objects. Every model uses strict mode and field aliases so that
raw API payloads can be parsed directly while downstream code uses
Pythonic attribute names.

Usage::

    from unifi.models import Site, Device, Client, VLAN, Event
    from unifi.models import HealthStatus, FirmwareStatus

    site = Site.model_validate(raw_api_response)
    print(site.site_id)  # normalized field name
"""

from unifi.models.client import Client
from unifi.models.device import Device
from unifi.models.event import Event
from unifi.models.health import FirmwareStatus, HealthStatus
from unifi.models.site import Site
from unifi.models.vlan import VLAN

__all__ = [
    "Client",
    "Device",
    "Event",
    "FirmwareStatus",
    "HealthStatus",
    "Site",
    "VLAN",
]
