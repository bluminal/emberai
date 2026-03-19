"""Device model for UniFi topology data.

Maps from UniFi Local Gateway API responses
(GET ``{local}/api/s/{site}/stat/device``) to a normalized Python
representation.
"""

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class Device(BaseModel):
    """A UniFi network device (switch, AP, gateway, console, etc.).

    Returned by ``unifi__topology__list_devices(site_id)`` (summary fields)
    and ``unifi__topology__get_device(device_id)`` (full detail including
    optional fields).

    API field mapping (Local Gateway ``/stat/device``):
        ``_id``             -> ``device_id``
        ``mac``             -> ``mac``  (no alias needed)
        ``ip``              -> ``ip``   (no alias needed)
        ``state``           -> ``status``
        ``version``         -> ``firmware``
        ``model``           -> ``model`` (no alias needed)
        ``port_table``      -> ``port_table``
        ``config_network``  -> ``config_network``
    """

    model_config = ConfigDict(strict=True, populate_by_name=True)

    # --- Core fields (always present in list responses) ---

    device_id: str = Field(alias="_id", description="Unique device identifier")
    name: str = Field(default="", description="User-assigned device name")
    model: str = Field(description="Hardware model code (e.g. 'U7PG2')")
    mac: str = Field(description="Device MAC address")
    ip: str = Field(default="", description="Management IP address")
    status: str = Field(
        alias="state",
        description="Device status (e.g. 'connected', 'disconnected', 'upgrading')",
    )
    uptime: int = Field(
        default=0,
        description="Uptime in seconds since last boot",
    )
    firmware: str = Field(
        default="",
        alias="version",
        description="Currently running firmware version",
    )
    product_line: str = Field(
        default="",
        description="Product line (e.g. 'network', 'protect')",
    )
    is_console: bool = Field(
        default=False,
        description="Whether this device is a UniFi Console (UDM, UCK, etc.)",
    )

    # --- Detail fields (present in get_device responses) ---

    port_table: list[dict[str, Any]] | None = Field(
        default=None,
        description="Switch port table with per-port status and config",
    )
    uplink: dict[str, Any] | None = Field(
        default=None,
        description="Uplink connection details (upstream device, port, speed)",
    )
    vlan_assignments: list[dict[str, Any]] | None = Field(
        default=None,
        description="VLAN assignments on this device's ports",
    )
    radio_table: list[dict[str, Any]] | None = Field(
        default=None,
        description="Radio configuration table (APs only)",
    )
    config_network: dict[str, Any] | None = Field(
        default=None,
        description="Network configuration applied to this device",
    )
