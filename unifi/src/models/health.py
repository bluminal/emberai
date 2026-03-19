"""Health and firmware status models for UniFi monitoring data.

Maps from UniFi API responses to normalized Python representations:
- ``HealthStatus``: GET ``{local}/api/s/{site}/stat/health``
- ``FirmwareStatus``: GET ``api.ui.com/v1/devices``
"""

from pydantic import BaseModel, ConfigDict, Field


class HealthStatus(BaseModel):
    """Aggregate site health status.

    Returned by ``unifi__health__get_site_health(site_id)``.

    API field mapping (Local Gateway ``/stat/health``):
        The ``/stat/health`` endpoint returns an array of subsystem objects.
        This model represents the merged/normalized view across subsystems
        (wan, lan, wlan, www).
    """

    model_config = ConfigDict(strict=True, populate_by_name=True)

    wan_status: str = Field(
        default="unknown",
        description="WAN subsystem status (e.g. 'ok', 'error', 'unknown')",
    )
    lan_status: str = Field(
        default="unknown",
        description="LAN subsystem status (e.g. 'ok', 'error', 'unknown')",
    )
    wlan_status: str = Field(
        default="unknown",
        description="WLAN subsystem status (e.g. 'ok', 'error', 'unknown')",
    )
    www_status: str = Field(
        default="unknown",
        description="Internet connectivity status (e.g. 'ok', 'error', 'unknown')",
    )
    device_count: int = Field(
        default=0,
        alias="num_d",
        description="Total number of devices at this site",
    )
    adopted_count: int = Field(
        default=0,
        alias="num_adopted",
        description="Number of adopted (managed) devices",
    )
    offline_count: int = Field(
        default=0,
        alias="num_disconnected",
        description="Number of offline/disconnected devices",
    )
    client_count: int = Field(
        default=0,
        alias="num_sta",
        description="Number of connected clients",
    )


class FirmwareStatus(BaseModel):
    """Firmware upgrade status for a single device.

    Returned by ``unifi__health__get_firmware_status(site_id)`` as a list.

    API field mapping (Cloud V1 ``/v1/devices``):
        ``_id``                        -> ``device_id``
        ``model``                      -> ``model``
        ``version``                    -> ``current_version``
        ``upgrade_to_firmware``        -> ``latest_version``
        ``upgradable``                 -> ``upgrade_available``
        ``product_line``               -> ``product_line``
    """

    model_config = ConfigDict(strict=True, populate_by_name=True)

    device_id: str = Field(alias="_id", description="Unique device identifier")
    model: str = Field(description="Hardware model code")
    current_version: str = Field(
        alias="version",
        description="Currently installed firmware version",
    )
    latest_version: str = Field(
        default="",
        alias="upgrade_to_firmware",
        description="Latest available firmware version (empty if up to date)",
    )
    upgrade_available: bool = Field(
        default=False,
        alias="upgradable",
        description="Whether a firmware upgrade is available",
    )
    product_line: str = Field(
        default="",
        description="Product line (e.g. 'network', 'protect')",
    )
