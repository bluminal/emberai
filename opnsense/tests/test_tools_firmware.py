"""Tests for Firmware skill tools.

Covers:
- get_status: parsing with model, fallback to raw
- list_packages: multiple response formats
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

import pytest


def _make_client(get_returns: dict[str, Any] | None = None) -> AsyncMock:
    client = AsyncMock()
    if get_returns is not None:
        client.get = AsyncMock(return_value=get_returns)
    return client


# ---------------------------------------------------------------------------
# get_status
# ---------------------------------------------------------------------------


class TestGetStatus:
    @pytest.mark.asyncio
    async def test_returns_parsed_status(self) -> None:
        from opnsense.tools.firmware import opnsense__firmware__get_status

        data = {
            "product_version": "24.7.1",
            "product_latest": "24.7.2",
            "upgrade_available": True,
            "last_check": "2026-03-19T09:00:00Z",
            "changelog": "https://opnsense.org/changelog/24.7.2",
        }
        client = _make_client(data)

        status = await opnsense__firmware__get_status(client)

        assert status["current_version"] == "24.7.1"
        assert status["latest_version"] == "24.7.2"
        assert status["upgrade_available"] is True
        assert status["changelog_url"] == "https://opnsense.org/changelog/24.7.2"
        client.get.assert_called_once_with("core", "firmware", "status")

    @pytest.mark.asyncio
    async def test_no_upgrade_available(self) -> None:
        from opnsense.tools.firmware import opnsense__firmware__get_status

        data = {
            "product_version": "24.7.2",
            "upgrade_available": False,
        }
        client = _make_client(data)

        status = await opnsense__firmware__get_status(client)

        assert status["current_version"] == "24.7.2"
        assert status["upgrade_available"] is False

    @pytest.mark.asyncio
    async def test_fallback_to_raw_on_parse_error(self) -> None:
        from opnsense.tools.firmware import opnsense__firmware__get_status

        # Missing required field (product_version) will fail model parse
        data = {"status": "ok", "extra": "value"}
        client = _make_client(data)

        status = await opnsense__firmware__get_status(client)

        # Should fall back to raw response
        assert status == data


# ---------------------------------------------------------------------------
# list_packages
# ---------------------------------------------------------------------------


class TestListPackages:
    @pytest.mark.asyncio
    async def test_package_key_format(self) -> None:
        from opnsense.tools.firmware import opnsense__firmware__list_packages

        data = {
            "package": [
                {"name": "opnsense", "version": "24.7.1"},
                {"name": "suricata", "version": "7.0.1"},
            ],
        }
        client = _make_client(data)

        packages = await opnsense__firmware__list_packages(client)

        assert len(packages) == 2
        assert packages[0]["name"] == "opnsense"
        assert packages[1]["name"] == "suricata"

    @pytest.mark.asyncio
    async def test_packages_key_format(self) -> None:
        from opnsense.tools.firmware import opnsense__firmware__list_packages

        data = {
            "packages": [
                {"name": "php82", "version": "8.2.20"},
            ],
        }
        client = _make_client(data)

        packages = await opnsense__firmware__list_packages(client)

        assert len(packages) == 1
        assert packages[0]["name"] == "php82"

    @pytest.mark.asyncio
    async def test_rows_key_format(self) -> None:
        from opnsense.tools.firmware import opnsense__firmware__list_packages

        data = {
            "rows": [
                {"name": "pkg1", "version": "1.0"},
            ],
        }
        client = _make_client(data)

        packages = await opnsense__firmware__list_packages(client)

        assert len(packages) == 1

    @pytest.mark.asyncio
    async def test_fallback_wraps_as_list(self) -> None:
        from opnsense.tools.firmware import opnsense__firmware__list_packages

        data = {"status": "ok", "name": "opnsense"}
        client = _make_client(data)

        packages = await opnsense__firmware__list_packages(client)

        assert len(packages) == 1
        assert packages[0] == data

    @pytest.mark.asyncio
    async def test_calls_correct_endpoint(self) -> None:
        from opnsense.tools.firmware import opnsense__firmware__list_packages

        client = _make_client({"package": []})
        await opnsense__firmware__list_packages(client)
        client.get.assert_called_once_with("core", "firmware", "info")
