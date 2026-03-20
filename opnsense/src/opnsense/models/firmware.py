"""Firmware model for OPNsense system firmware status.

Maps from OPNsense API responses
(GET ``/api/core/firmware/status``) to a normalized Python representation.
"""

from pydantic import BaseModel, ConfigDict, Field


class FirmwareStatus(BaseModel):
    """OPNsense firmware status and update availability.

    Returned by ``opnsense__firmware__get_status()``.

    API field mapping (``/api/core/firmware/status``):
        ``product_version``  -> ``current_version``
        ``product_latest``   -> ``latest_version``
        ``upgrade_available`` -> ``upgrade_available``  (may need bool coercion)
        ``last_check``       -> ``last_check``
        ``changelog``        -> ``changelog_url``
    """

    model_config = ConfigDict(strict=True, populate_by_name=True)

    current_version: str = Field(
        alias="product_version",
        description="Currently installed firmware version (e.g. '24.7.1')",
    )
    latest_version: str = Field(
        default="",
        alias="product_latest",
        description="Latest available firmware version",
    )
    upgrade_available: bool = Field(
        default=False,
        description="Whether a firmware upgrade is available",
    )
    last_check: str = Field(
        default="",
        description="Timestamp of last firmware update check",
    )
    changelog_url: str | None = Field(
        default=None,
        alias="changelog",
        description="URL to the changelog for the available update",
    )
