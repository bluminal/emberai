"""Site model for UniFi topology data.

Maps from UniFi Cloud V1 API responses (GET api.ui.com/v1/sites) to a
normalized Python representation.
"""

from pydantic import BaseModel, ConfigDict, Field


class Site(BaseModel):
    """A UniFi site (logical grouping of devices and clients).

    Returned by ``unifi__topology__list_sites()``.

    API field mapping (Cloud V1 ``/v1/sites``):
        ``_id``          -> ``site_id``
        ``desc``         -> ``description``
        ``num_new_alarms`` is ignored (not in tool signature)
    """

    model_config = ConfigDict(strict=True, populate_by_name=True)

    site_id: str = Field(alias="_id", description="Unique site identifier")
    name: str = Field(description="Human-readable site name")
    description: str = Field(
        default="",
        alias="desc",
        description="Optional site description",
    )
    device_count: int = Field(
        default=0,
        alias="num_d",
        description="Number of adopted devices at this site",
    )
    client_count: int = Field(
        default=0,
        alias="num_sta",
        description="Number of connected clients at this site",
    )
