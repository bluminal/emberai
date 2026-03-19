"""Shared custom types for UniFi data models.

Contains reusable Pydantic type annotations that handle API response
normalization. These types are internal to the models package.
"""

from datetime import UTC, datetime
from typing import Annotated

from pydantic import BeforeValidator


def _coerce_datetime(v: int | float | str | datetime | None) -> datetime | None:
    """Coerce UniFi timestamp values to datetime.

    The UniFi API returns timestamps as either epoch integers (seconds since
    Unix epoch) or ISO 8601 strings depending on the endpoint and field.
    This validator normalizes both formats to ``datetime`` objects.
    """
    if v is None:
        return None
    if isinstance(v, datetime):
        return v
    if isinstance(v, (int, float)):
        return datetime.fromtimestamp(v, tz=UTC)
    if isinstance(v, str):
        return datetime.fromisoformat(v)
    msg = f"Cannot coerce {type(v).__name__} to datetime"
    raise TypeError(msg)


FlexibleDatetime = Annotated[datetime, BeforeValidator(_coerce_datetime)]
"""A datetime type that accepts epoch ints, ISO 8601 strings, or datetime objects.

Use this instead of ``datetime`` for fields that may receive raw API values.
Works correctly with ``ConfigDict(strict=True)`` because the ``BeforeValidator``
runs before strict type checking.
"""
