"""Tests for FreeRADIUS service tools.

Covers:
- get_radius_status: service overview, client/user parsing
- add_radius_client: write gate enforcement, success path
- add_radius_mac_vlan: write gate, MAC normalization, success path
- remove_radius_mac_vlan: write gate, lookup + delete, not-found error
- list_radius_mac_vlans: basic retrieval and parsing
- normalize_mac: various input formats and invalid inputs
"""

from __future__ import annotations

import os
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from opnsense.errors import WriteGateError
from opnsense.safety import WriteBlockReason
from opnsense.tools.radius import normalize_mac

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_client(
    get_side_effect: list[dict[str, Any]] | None = None,
    get_returns: dict[str, Any] | None = None,
) -> AsyncMock:
    """Create a mock OPNsenseClient.

    If ``get_side_effect`` is given, ``client.get`` will return values
    in order for successive calls. Otherwise ``get_returns`` is used
    as a single return value.
    """
    client = AsyncMock()
    if get_side_effect is not None:
        client.get = AsyncMock(side_effect=get_side_effect)
    elif get_returns is not None:
        client.get = AsyncMock(return_value=get_returns)
    else:
        client.get = AsyncMock(return_value={})
    client.write = AsyncMock(
        return_value={"result": "saved", "uuid": "new-uuid"},
    )
    client.reconfigure = AsyncMock(return_value={"status": "ok"})
    client.close = AsyncMock()
    return client


# ---------------------------------------------------------------------------
# normalize_mac
# ---------------------------------------------------------------------------


class TestNormalizeMac:
    """MAC address normalization logic."""

    def test_colon_separated_uppercase(self) -> None:
        assert normalize_mac("AA:BB:CC:DD:EE:FF") == "aabbccddeeff"

    def test_colon_separated_lowercase(self) -> None:
        assert normalize_mac("aa:bb:cc:dd:ee:ff") == "aabbccddeeff"

    def test_colon_separated_mixed_case(self) -> None:
        assert normalize_mac("Aa:Bb:Cc:Dd:Ee:Ff") == "aabbccddeeff"

    def test_dash_separated(self) -> None:
        assert normalize_mac("aa-bb-cc-dd-ee-ff") == "aabbccddeeff"

    def test_dash_separated_uppercase(self) -> None:
        assert normalize_mac("AA-BB-CC-DD-EE-FF") == "aabbccddeeff"

    def test_plain_lowercase(self) -> None:
        assert normalize_mac("aabbccddeeff") == "aabbccddeeff"

    def test_plain_uppercase(self) -> None:
        assert normalize_mac("AABBCCDDEEFF") == "aabbccddeeff"

    def test_whitespace_stripped(self) -> None:
        assert normalize_mac("  AA:BB:CC:DD:EE:FF  ") == "aabbccddeeff"

    def test_invalid_too_short(self) -> None:
        with pytest.raises(ValueError, match="Invalid MAC"):
            normalize_mac("AABB")

    def test_invalid_mixed_separators(self) -> None:
        with pytest.raises(ValueError, match="Invalid MAC"):
            normalize_mac("AA:BB-CC:DD:EE:FF")

    def test_invalid_non_hex(self) -> None:
        with pytest.raises(ValueError, match="Invalid MAC"):
            normalize_mac("GG:HH:II:JJ:KK:LL")

    def test_empty_string(self) -> None:
        with pytest.raises(ValueError, match="Invalid MAC"):
            normalize_mac("")


# ---------------------------------------------------------------------------
# get_radius_status
# ---------------------------------------------------------------------------


class TestGetRadiusStatus:
    @pytest.mark.asyncio
    async def test_returns_full_status(self) -> None:
        from opnsense.tools.radius import (
            opnsense__services__get_radius_status,
        )

        general_resp = {"general": {"enabled": "1"}}
        clients_resp = {
            "rows": [
                {
                    "uuid": "c-1",
                    "name": "unifi",
                    "ip": "10.0.0.1",
                    "enabled": "1",
                    "description": "UniFi CK",
                },
            ],
        }
        users_resp = {
            "rows": [
                {
                    "uuid": "u-1",
                    "username": "aabbccddeeff",
                    "vlan": "70",
                    "enabled": "1",
                    "description": "Xbox",
                },
                {
                    "uuid": "u-2",
                    "username": "112233445566",
                    "vlan": "30",
                    "enabled": "1",
                    "description": "Camera",
                },
            ],
        }

        mock_client = _make_client(
            get_side_effect=[general_resp, clients_resp, users_resp],
        )

        with patch(
            "opnsense.tools.radius._get_client",
            return_value=mock_client,
        ):
            result = await opnsense__services__get_radius_status()

        assert result["enabled"] == "1"
        assert result["client_count"] == 1
        assert result["user_count"] == 2
        assert len(result["clients"]) == 1
        assert result["clients"][0]["name"] == "unifi"
        assert len(result["users"]) == 2

    @pytest.mark.asyncio
    async def test_empty_service(self) -> None:
        from opnsense.tools.radius import (
            opnsense__services__get_radius_status,
        )

        mock_client = _make_client(
            get_side_effect=[
                {"general": {"enabled": "0"}},
                {"rows": []},
                {"rows": []},
            ],
        )

        with patch(
            "opnsense.tools.radius._get_client",
            return_value=mock_client,
        ):
            result = await opnsense__services__get_radius_status()

        assert result["enabled"] == "0"
        assert result["client_count"] == 0
        assert result["user_count"] == 0


# ---------------------------------------------------------------------------
# add_radius_client -- WRITE GATE TESTS
# ---------------------------------------------------------------------------


class TestAddRadiusClient:
    @pytest.mark.asyncio
    async def test_blocked_when_env_var_disabled(self) -> None:
        from opnsense.tools.radius import (
            opnsense__services__add_radius_client,
        )

        mock_client = _make_client()

        with (
            patch.dict(os.environ, {}, clear=True),
            patch(
                "opnsense.tools.radius._get_client",
                return_value=mock_client,
            ),
            pytest.raises(WriteGateError) as exc_info,
        ):
            await opnsense__services__add_radius_client(
                "unifi",
                "10.0.0.1",
                "secret123",
                apply=True,
            )
        assert exc_info.value.reason == WriteBlockReason.ENV_VAR_DISABLED

    @pytest.mark.asyncio
    async def test_blocked_when_apply_false(self) -> None:
        from opnsense.tools.radius import (
            opnsense__services__add_radius_client,
        )

        mock_client = _make_client()

        with (
            patch.dict(
                os.environ,
                {"OPNSENSE_WRITE_ENABLED": "true"},
            ),
            patch(
                "opnsense.tools.radius._get_client",
                return_value=mock_client,
            ),
            pytest.raises(WriteGateError) as exc_info,
        ):
            await opnsense__services__add_radius_client(
                "unifi",
                "10.0.0.1",
                "secret123",
                apply=False,
            )
        assert exc_info.value.reason == WriteBlockReason.APPLY_FLAG_MISSING

    @pytest.mark.asyncio
    async def test_succeeds_when_gates_pass(self) -> None:
        from opnsense.tools.radius import (
            opnsense__services__add_radius_client,
        )

        mock_client = _make_client()

        with (
            patch.dict(
                os.environ,
                {"OPNSENSE_WRITE_ENABLED": "true"},
            ),
            patch(
                "opnsense.tools.radius._get_client",
                return_value=mock_client,
            ),
        ):
            result = await opnsense__services__add_radius_client(
                "unifi",
                "10.0.0.1",
                "secret123",
                description="UniFi CK",
                apply=True,
            )

        assert result["name"] == "unifi"
        assert result["ip"] == "10.0.0.1"
        assert "write_result" in result
        assert "reconfigure_result" in result

        # Verify write payload
        mock_client.write.assert_called_once()
        call_args = mock_client.write.call_args
        assert call_args[0] == ("freeradius", "client", "addClient")
        data = call_args[1]["data"]
        assert data["client"]["name"] == "unifi"
        assert data["client"]["secret"] == "secret123"
        assert data["client"]["ip"] == "10.0.0.1"

        # Verify reconfigure called
        mock_client.reconfigure.assert_called_once_with(
            "freeradius",
            "service",
        )


# ---------------------------------------------------------------------------
# add_radius_mac_vlan -- WRITE GATE + MAC NORMALIZATION
# ---------------------------------------------------------------------------


class TestAddRadiusMacVlan:
    @pytest.mark.asyncio
    async def test_blocked_when_env_var_disabled(self) -> None:
        from opnsense.tools.radius import (
            opnsense__services__add_radius_mac_vlan,
        )

        mock_client = _make_client()

        with (
            patch.dict(os.environ, {}, clear=True),
            patch(
                "opnsense.tools.radius._get_client",
                return_value=mock_client,
            ),
            pytest.raises(WriteGateError) as exc_info,
        ):
            await opnsense__services__add_radius_mac_vlan(
                "AA:BB:CC:DD:EE:FF",
                70,
                apply=True,
            )
        assert exc_info.value.reason == WriteBlockReason.ENV_VAR_DISABLED

    @pytest.mark.asyncio
    async def test_blocked_when_apply_false(self) -> None:
        from opnsense.tools.radius import (
            opnsense__services__add_radius_mac_vlan,
        )

        mock_client = _make_client()

        with (
            patch.dict(
                os.environ,
                {"OPNSENSE_WRITE_ENABLED": "true"},
            ),
            patch(
                "opnsense.tools.radius._get_client",
                return_value=mock_client,
            ),
            pytest.raises(WriteGateError) as exc_info,
        ):
            await opnsense__services__add_radius_mac_vlan(
                "AA:BB:CC:DD:EE:FF",
                70,
                apply=False,
            )
        assert exc_info.value.reason == WriteBlockReason.APPLY_FLAG_MISSING

    @pytest.mark.asyncio
    async def test_normalizes_mac_colon_format(self) -> None:
        from opnsense.tools.radius import (
            opnsense__services__add_radius_mac_vlan,
        )

        mock_client = _make_client()

        with (
            patch.dict(
                os.environ,
                {"OPNSENSE_WRITE_ENABLED": "true"},
            ),
            patch(
                "opnsense.tools.radius._get_client",
                return_value=mock_client,
            ),
        ):
            result = await opnsense__services__add_radius_mac_vlan(
                "AA:BB:CC:DD:EE:FF",
                70,
                "Xbox",
                apply=True,
            )

        assert result["mac"] == "aabbccddeeff"
        assert result["vlan_id"] == 70

        # Check the write payload uses normalized MAC
        call_data = mock_client.write.call_args[1]["data"]
        assert call_data["user"]["username"] == "aabbccddeeff"
        assert call_data["user"]["password"] == "aabbccddeeff"
        assert call_data["user"]["vlan"] == "70"

    @pytest.mark.asyncio
    async def test_normalizes_mac_dash_format(self) -> None:
        from opnsense.tools.radius import (
            opnsense__services__add_radius_mac_vlan,
        )

        mock_client = _make_client()

        with (
            patch.dict(
                os.environ,
                {"OPNSENSE_WRITE_ENABLED": "true"},
            ),
            patch(
                "opnsense.tools.radius._get_client",
                return_value=mock_client,
            ),
        ):
            result = await opnsense__services__add_radius_mac_vlan(
                "aa-bb-cc-dd-ee-ff",
                30,
                apply=True,
            )

        assert result["mac"] == "aabbccddeeff"

    @pytest.mark.asyncio
    async def test_normalizes_mac_plain_format(self) -> None:
        from opnsense.tools.radius import (
            opnsense__services__add_radius_mac_vlan,
        )

        mock_client = _make_client()

        with (
            patch.dict(
                os.environ,
                {"OPNSENSE_WRITE_ENABLED": "true"},
            ),
            patch(
                "opnsense.tools.radius._get_client",
                return_value=mock_client,
            ),
        ):
            result = await opnsense__services__add_radius_mac_vlan(
                "AABBCCDDEEFF",
                50,
                apply=True,
            )

        assert result["mac"] == "aabbccddeeff"

    @pytest.mark.asyncio
    async def test_invalid_mac_raises_value_error(self) -> None:
        from opnsense.tools.radius import (
            opnsense__services__add_radius_mac_vlan,
        )

        mock_client = _make_client()

        with (
            patch.dict(
                os.environ,
                {"OPNSENSE_WRITE_ENABLED": "true"},
            ),
            patch(
                "opnsense.tools.radius._get_client",
                return_value=mock_client,
            ),
            pytest.raises(ValueError, match="Invalid MAC"),
        ):
            await opnsense__services__add_radius_mac_vlan(
                "not-a-mac",
                70,
                apply=True,
            )


# ---------------------------------------------------------------------------
# remove_radius_mac_vlan -- WRITE GATE + LOOKUP
# ---------------------------------------------------------------------------


class TestRemoveRadiusMacVlan:
    @pytest.mark.asyncio
    async def test_blocked_when_env_var_disabled(self) -> None:
        from opnsense.tools.radius import (
            opnsense__services__remove_radius_mac_vlan,
        )

        mock_client = _make_client(
            get_returns={
                "rows": [
                    {"uuid": "u-1", "username": "aabbccddeeff"},
                ],
            },
        )

        with (
            patch.dict(os.environ, {}, clear=True),
            patch(
                "opnsense.tools.radius._get_client",
                return_value=mock_client,
            ),
            pytest.raises(WriteGateError) as exc_info,
        ):
            await opnsense__services__remove_radius_mac_vlan(
                "AA:BB:CC:DD:EE:FF",
                apply=True,
            )
        assert exc_info.value.reason == WriteBlockReason.ENV_VAR_DISABLED

    @pytest.mark.asyncio
    async def test_blocked_when_apply_false(self) -> None:
        from opnsense.tools.radius import (
            opnsense__services__remove_radius_mac_vlan,
        )

        mock_client = _make_client(
            get_returns={
                "rows": [
                    {"uuid": "u-1", "username": "aabbccddeeff"},
                ],
            },
        )

        with (
            patch.dict(
                os.environ,
                {"OPNSENSE_WRITE_ENABLED": "true"},
            ),
            patch(
                "opnsense.tools.radius._get_client",
                return_value=mock_client,
            ),
            pytest.raises(WriteGateError) as exc_info,
        ):
            await opnsense__services__remove_radius_mac_vlan(
                "AA:BB:CC:DD:EE:FF",
                apply=False,
            )
        assert exc_info.value.reason == WriteBlockReason.APPLY_FLAG_MISSING

    @pytest.mark.asyncio
    async def test_succeeds_when_user_found(self) -> None:
        from opnsense.tools.radius import (
            opnsense__services__remove_radius_mac_vlan,
        )

        mock_client = _make_client(
            get_returns={
                "rows": [
                    {
                        "uuid": "u-1",
                        "username": "aabbccddeeff",
                        "vlan": "70",
                    },
                    {
                        "uuid": "u-2",
                        "username": "112233445566",
                        "vlan": "30",
                    },
                ],
            },
        )

        with (
            patch.dict(
                os.environ,
                {"OPNSENSE_WRITE_ENABLED": "true"},
            ),
            patch(
                "opnsense.tools.radius._get_client",
                return_value=mock_client,
            ),
        ):
            result = await opnsense__services__remove_radius_mac_vlan(
                "AA:BB:CC:DD:EE:FF",
                apply=True,
            )

        assert result["mac"] == "aabbccddeeff"
        assert result["uuid"] == "u-1"
        assert "delete_result" in result
        assert "reconfigure_result" in result

        # Verify delete was called with correct UUID
        mock_client.write.assert_called_once_with(
            "freeradius",
            "user",
            "delUser/u-1",
        )
        mock_client.reconfigure.assert_called_once_with(
            "freeradius",
            "service",
        )

    @pytest.mark.asyncio
    async def test_raises_when_user_not_found(self) -> None:
        from opnsense.tools.radius import (
            opnsense__services__remove_radius_mac_vlan,
        )

        mock_client = _make_client(get_returns={"rows": []})

        with (
            patch.dict(
                os.environ,
                {"OPNSENSE_WRITE_ENABLED": "true"},
            ),
            patch(
                "opnsense.tools.radius._get_client",
                return_value=mock_client,
            ),
            pytest.raises(ValueError, match="No RADIUS user found"),
        ):
            await opnsense__services__remove_radius_mac_vlan(
                "AA:BB:CC:DD:EE:FF",
                apply=True,
            )


# ---------------------------------------------------------------------------
# list_radius_mac_vlans
# ---------------------------------------------------------------------------


class TestListRadiusMacVlans:
    @pytest.mark.asyncio
    async def test_returns_parsed_users(self) -> None:
        from opnsense.tools.radius import (
            opnsense__services__list_radius_mac_vlans,
        )

        mock_client = _make_client(
            get_returns={
                "rows": [
                    {
                        "uuid": "u-1",
                        "username": "aabbccddeeff",
                        "vlan": "70",
                        "enabled": "1",
                        "description": "Xbox",
                    },
                    {
                        "uuid": "u-2",
                        "username": "112233445566",
                        "vlan": "30",
                        "enabled": "1",
                        "description": "Camera",
                    },
                ],
            },
        )

        with patch(
            "opnsense.tools.radius._get_client",
            return_value=mock_client,
        ):
            users = await opnsense__services__list_radius_mac_vlans()

        assert len(users) == 2
        assert users[0]["username"] == "aabbccddeeff"
        assert users[0]["vlan"] == "70"
        assert users[0]["description"] == "Xbox"
        assert users[1]["username"] == "112233445566"
        assert users[1]["vlan"] == "30"

    @pytest.mark.asyncio
    async def test_empty_list(self) -> None:
        from opnsense.tools.radius import (
            opnsense__services__list_radius_mac_vlans,
        )

        mock_client = _make_client(get_returns={"rows": []})

        with patch(
            "opnsense.tools.radius._get_client",
            return_value=mock_client,
        ):
            users = await opnsense__services__list_radius_mac_vlans()

        assert users == []

    @pytest.mark.asyncio
    async def test_client_closed_after_call(self) -> None:
        from opnsense.tools.radius import (
            opnsense__services__list_radius_mac_vlans,
        )

        mock_client = _make_client(get_returns={"rows": []})

        with patch(
            "opnsense.tools.radius._get_client",
            return_value=mock_client,
        ):
            await opnsense__services__list_radius_mac_vlans()

        mock_client.close.assert_called_once()
