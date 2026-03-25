"""Tests for OPNsense 26.x VLAN listing -- response parsing and type coercion.

Covers the end-to-end path from raw OPNsense 26.x API responses (which
return tag/pcp as strings) through coercion, model validation, and the
tool-level list function.

Regression tests for: Task 176 -- list_vlan_interfaces returning 0 VLANs.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from pydantic import ValidationError

from opnsense.api.response import normalize_response
from opnsense.models.vlan_interface import VLANInterface
from opnsense.tools.interfaces import _coerce_vlan_fields
from tests.fixtures import load_fixture

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def vlan_26x_response() -> dict[str, Any]:
    """Load the 26.x-format VLAN fixture."""
    return load_fixture("vlan_interfaces.json")


@pytest.fixture()
def single_vlan_row_26x() -> dict[str, Any]:
    """A single VLAN row as returned by OPNsense 26.x (strings for tag/pcp)."""
    return {
        "uuid": "test-uuid-001",
        "tag": "10",
        "if": "igb1",
        "descr": "Guest",
        "vlanif": "vlan0.10",
        "pcp": "0",
        "proto": "",
    }


# ---------------------------------------------------------------------------
# _coerce_vlan_fields
# ---------------------------------------------------------------------------


class TestCoerceVlanFields:
    """Tests for the type coercion helper."""

    def test_coerces_string_tag_to_int(self) -> None:
        row: dict[str, Any] = {"tag": "10", "pcp": "0"}
        coerced = _coerce_vlan_fields(row)
        assert coerced["tag"] == 10
        assert isinstance(coerced["tag"], int)

    def test_coerces_string_pcp_to_int(self) -> None:
        row: dict[str, Any] = {"tag": "10", "pcp": "4"}
        coerced = _coerce_vlan_fields(row)
        assert coerced["pcp"] == 4
        assert isinstance(coerced["pcp"], int)

    def test_leaves_int_tag_unchanged(self) -> None:
        row: dict[str, Any] = {"tag": 10, "pcp": 0}
        coerced = _coerce_vlan_fields(row)
        assert coerced["tag"] == 10
        assert isinstance(coerced["tag"], int)

    def test_empty_string_becomes_none(self) -> None:
        row: dict[str, Any] = {"tag": "10", "pcp": ""}
        coerced = _coerce_vlan_fields(row)
        assert coerced["pcp"] is None

    def test_null_string_becomes_none(self) -> None:
        row: dict[str, Any] = {"tag": "10", "pcp": "null"}
        coerced = _coerce_vlan_fields(row)
        assert coerced["pcp"] is None

    def test_non_numeric_string_becomes_none(self) -> None:
        row: dict[str, Any] = {"tag": "abc", "pcp": "xyz"}
        coerced = _coerce_vlan_fields(row)
        assert coerced["tag"] is None
        assert coerced["pcp"] is None

    def test_missing_fields_left_alone(self) -> None:
        row: dict[str, Any] = {"uuid": "test", "descr": "foo"}
        coerced = _coerce_vlan_fields(row)
        assert coerced == {"uuid": "test", "descr": "foo"}

    def test_preserves_other_fields(self) -> None:
        row: dict[str, Any] = {
            "uuid": "abc",
            "tag": "10",
            "if": "igb1",
            "descr": "Guest",
            "vlanif": "vlan0.10",
            "pcp": "0",
            "proto": "",
        }
        coerced = _coerce_vlan_fields(row)
        assert coerced["uuid"] == "abc"
        assert coerced["if"] == "igb1"
        assert coerced["descr"] == "Guest"
        assert coerced["vlanif"] == "vlan0.10"
        assert coerced["proto"] == ""

    def test_does_not_mutate_original(self) -> None:
        row: dict[str, Any] = {"tag": "10", "pcp": "0"}
        _coerce_vlan_fields(row)
        assert row["tag"] == "10"
        assert row["pcp"] == "0"

    def test_whitespace_stripped(self) -> None:
        row: dict[str, Any] = {"tag": " 10 ", "pcp": " 4 "}
        coerced = _coerce_vlan_fields(row)
        assert coerced["tag"] == 10
        assert coerced["pcp"] == 4


# ---------------------------------------------------------------------------
# VLANInterface model with 26.x data
# ---------------------------------------------------------------------------


class TestVLANInterfaceModel26x:
    """Test VLANInterface model with pre-coerced 26.x-style data."""

    def test_parse_after_coercion(self, single_vlan_row_26x: dict[str, Any]) -> None:
        coerced = _coerce_vlan_fields(single_vlan_row_26x)
        vlan = VLANInterface.model_validate(coerced)
        assert vlan.uuid == "test-uuid-001"
        assert vlan.tag == 10
        assert vlan.parent_if == "igb1"
        assert vlan.description == "Guest"
        assert vlan.device == "vlan0.10"
        assert vlan.pcp == 0
        assert vlan.proto == ""

    def test_field_semantics_parent_if(self) -> None:
        """Verify 'if' maps to parent_if (the physical interface)."""
        data: dict[str, Any] = {
            "uuid": "x",
            "tag": 10,
            "if": "igb1",
            "vlanif": "vlan0.10",
        }
        vlan = VLANInterface.model_validate(data)
        assert vlan.parent_if == "igb1"

    def test_field_semantics_device(self) -> None:
        """Verify 'vlanif' maps to device (the VLAN device name)."""
        data: dict[str, Any] = {
            "uuid": "x",
            "tag": 10,
            "if": "igb1",
            "vlanif": "vlan0.10",
        }
        vlan = VLANInterface.model_validate(data)
        assert vlan.device == "vlan0.10"

    def test_rejects_string_tag_without_coercion(self) -> None:
        """Without coercion, strict mode rejects string tags."""
        data: dict[str, Any] = {
            "uuid": "x",
            "tag": "10",
            "if": "igb1",
            "vlanif": "vlan0.10",
        }
        with pytest.raises(ValidationError):
            VLANInterface.model_validate(data)

    def test_rejects_string_pcp_without_coercion(self) -> None:
        """Without coercion, strict mode rejects string pcp."""
        data: dict[str, Any] = {
            "uuid": "x",
            "tag": 10,
            "if": "igb1",
            "vlanif": "vlan0.10",
            "pcp": "3",
        }
        with pytest.raises(ValidationError):
            VLANInterface.model_validate(data)

    def test_model_dump_uses_python_names(self) -> None:
        """model_dump(by_alias=False) should use Python field names."""
        data: dict[str, Any] = {
            "uuid": "x",
            "tag": 10,
            "if": "igb1",
            "descr": "Test",
            "vlanif": "vlan0.10",
            "pcp": 3,
        }
        vlan = VLANInterface.model_validate(data)
        dumped = vlan.model_dump(by_alias=False)
        assert "parent_if" in dumped
        assert "device" in dumped
        assert "description" in dumped
        assert "if" not in dumped
        assert "vlanif" not in dumped
        assert "descr" not in dumped

    def test_pcp_none_when_missing(self) -> None:
        data: dict[str, Any] = {
            "uuid": "x",
            "tag": 10,
            "if": "igb1",
            "vlanif": "vlan0.10",
        }
        vlan = VLANInterface.model_validate(data)
        assert vlan.pcp is None

    def test_proto_defaults_empty(self) -> None:
        data: dict[str, Any] = {
            "uuid": "x",
            "tag": 10,
            "if": "igb1",
            "vlanif": "vlan0.10",
        }
        vlan = VLANInterface.model_validate(data)
        assert vlan.proto == ""


# ---------------------------------------------------------------------------
# Full fixture parsing (7 VLANs)
# ---------------------------------------------------------------------------


class TestFullFixtureParsing:
    """Test parsing the complete 26.x VLAN fixture through normalize + coerce + validate."""

    def test_all_seven_vlans_parsed(self, vlan_26x_response: dict[str, Any]) -> None:
        """The core regression test: all 7 VLANs must be parsed successfully."""
        normalized = normalize_response(vlan_26x_response)
        vlans: list[dict[str, Any]] = []
        for row in normalized.data:
            coerced = _coerce_vlan_fields(row)
            vlan = VLANInterface.model_validate(coerced)
            vlans.append(vlan.model_dump(by_alias=False))

        assert len(vlans) == 7

    def test_fixture_tags_correct(self, vlan_26x_response: dict[str, Any]) -> None:
        normalized = normalize_response(vlan_26x_response)
        tags: list[int] = []
        for row in normalized.data:
            coerced = _coerce_vlan_fields(row)
            vlan = VLANInterface.model_validate(coerced)
            tags.append(vlan.tag)

        assert tags == [10, 20, 30, 40, 50, 60, 99]

    def test_fixture_descriptions(self, vlan_26x_response: dict[str, Any]) -> None:
        normalized = normalize_response(vlan_26x_response)
        descriptions: list[str] = []
        for row in normalized.data:
            coerced = _coerce_vlan_fields(row)
            vlan = VLANInterface.model_validate(coerced)
            descriptions.append(vlan.description)

        assert descriptions == ["Guest", "Cameras", "IoT", "Kids", "Work", "Lab", "Management"]

    def test_fixture_parent_interfaces(self, vlan_26x_response: dict[str, Any]) -> None:
        """All VLANs should have igb1 as parent interface."""
        normalized = normalize_response(vlan_26x_response)
        for row in normalized.data:
            coerced = _coerce_vlan_fields(row)
            vlan = VLANInterface.model_validate(coerced)
            assert vlan.parent_if == "igb1"

    def test_fixture_device_names(self, vlan_26x_response: dict[str, Any]) -> None:
        normalized = normalize_response(vlan_26x_response)
        devices: list[str] = []
        for row in normalized.data:
            coerced = _coerce_vlan_fields(row)
            vlan = VLANInterface.model_validate(coerced)
            devices.append(vlan.device)

        assert devices == [
            "vlan0.10", "vlan0.20", "vlan0.30", "vlan0.40",
            "vlan0.50", "vlan0.60", "vlan0.99",
        ]

    def test_pcp_values(self, vlan_26x_response: dict[str, Any]) -> None:
        """Verify PCP values: most are 0, Work=4, Management=6."""
        normalized = normalize_response(vlan_26x_response)
        pcp_map: dict[str, int | None] = {}
        for row in normalized.data:
            coerced = _coerce_vlan_fields(row)
            vlan = VLANInterface.model_validate(coerced)
            pcp_map[vlan.description] = vlan.pcp

        assert pcp_map["Guest"] == 0
        assert pcp_map["Work"] == 4
        assert pcp_map["Management"] == 6


# ---------------------------------------------------------------------------
# Edge cases and empty responses
# ---------------------------------------------------------------------------


class TestEdgeCases:
    def test_empty_rows_response(self) -> None:
        """An empty search response should produce 0 VLANs."""
        raw: dict[str, Any] = {
            "rows": [],
            "rowCount": 0,
            "total": 0,
            "current": 1,
        }
        normalized = normalize_response(raw)
        assert len(normalized.data) == 0

    def test_row_missing_uuid_skipped_gracefully(self) -> None:
        """Rows missing required fields should fail validation (not crash)."""
        row: dict[str, Any] = {
            "tag": "10",
            "if": "igb1",
            "vlanif": "vlan0.10",
        }
        coerced = _coerce_vlan_fields(row)
        with pytest.raises(ValidationError):
            VLANInterface.model_validate(coerced)

    def test_row_missing_tag_skipped_gracefully(self) -> None:
        row: dict[str, Any] = {
            "uuid": "x",
            "if": "igb1",
            "vlanif": "vlan0.10",
        }
        coerced = _coerce_vlan_fields(row)
        with pytest.raises(ValidationError):
            VLANInterface.model_validate(coerced)

    def test_row_missing_parent_if_skipped_gracefully(self) -> None:
        row: dict[str, Any] = {
            "uuid": "x",
            "tag": "10",
            "vlanif": "vlan0.10",
        }
        coerced = _coerce_vlan_fields(row)
        with pytest.raises(ValidationError):
            VLANInterface.model_validate(coerced)

    def test_row_missing_device_skipped_gracefully(self) -> None:
        row: dict[str, Any] = {
            "uuid": "x",
            "tag": "10",
            "if": "igb1",
        }
        coerced = _coerce_vlan_fields(row)
        with pytest.raises(ValidationError):
            VLANInterface.model_validate(coerced)

    def test_extra_fields_ignored(self) -> None:
        """Rows with extra unexpected fields should still parse."""
        row: dict[str, Any] = {
            "uuid": "x",
            "tag": 10,
            "if": "igb1",
            "vlanif": "vlan0.10",
            "unknown_field": "should_be_ignored",
            "another_extra": 42,
        }
        # VLANInterface has strict=True for type checking but not
        # for extra fields -- Pydantic default is to ignore extras
        vlan = VLANInterface.model_validate(row)
        assert vlan.uuid == "x"


# ---------------------------------------------------------------------------
# Tool-level integration test (mocked API client)
# ---------------------------------------------------------------------------


class TestListVlanInterfacesTool:
    """Integration test for the full list_vlan_interfaces tool with mocked client."""

    @pytest.mark.asyncio
    async def test_returns_all_vlans_from_26x_response(
        self,
        vlan_26x_response: dict[str, Any],
    ) -> None:
        """The tool should return all 7 VLANs from a 26.x-format response."""
        mock_client = AsyncMock()
        mock_client.get_cached = AsyncMock(return_value=vlan_26x_response)
        mock_client.close = AsyncMock()

        with patch(
            "opnsense.tools.interfaces._get_client",
            return_value=mock_client,
        ):
            from opnsense.tools.interfaces import (
                opnsense__interfaces__list_vlan_interfaces,
            )

            result = await opnsense__interfaces__list_vlan_interfaces()

        assert len(result) == 7
        # Verify first VLAN
        assert result[0]["tag"] == 10
        assert result[0]["parent_if"] == "igb1"
        assert result[0]["device"] == "vlan0.10"
        assert result[0]["description"] == "Guest"
        # Verify last VLAN
        assert result[6]["tag"] == 99
        assert result[6]["description"] == "Management"
        assert result[6]["pcp"] == 6

    @pytest.mark.asyncio
    async def test_returns_empty_for_no_vlans(self) -> None:
        """The tool should return an empty list for 0 VLANs."""
        mock_client = AsyncMock()
        mock_client.get_cached = AsyncMock(return_value={
            "rows": [],
            "rowCount": 0,
            "total": 0,
            "current": 1,
        })
        mock_client.close = AsyncMock()

        with patch(
            "opnsense.tools.interfaces._get_client",
            return_value=mock_client,
        ):
            from opnsense.tools.interfaces import (
                opnsense__interfaces__list_vlan_interfaces,
            )

            result = await opnsense__interfaces__list_vlan_interfaces()

        assert result == []

    @pytest.mark.asyncio
    async def test_skips_invalid_rows_without_crashing(self) -> None:
        """Invalid rows should be skipped; valid ones still returned."""
        response: dict[str, Any] = {
            "rows": [
                {
                    "uuid": "valid-uuid",
                    "tag": "10",
                    "if": "igb1",
                    "descr": "Guest",
                    "vlanif": "vlan0.10",
                    "pcp": "0",
                },
                {
                    # Missing uuid and tag -- will fail validation
                    "descr": "Broken",
                },
                {
                    "uuid": "valid-uuid-2",
                    "tag": "20",
                    "if": "igb1",
                    "descr": "IoT",
                    "vlanif": "vlan0.20",
                    "pcp": "0",
                },
            ],
            "rowCount": 3,
            "total": 3,
            "current": 1,
        }

        mock_client = AsyncMock()
        mock_client.get_cached = AsyncMock(return_value=response)
        mock_client.close = AsyncMock()

        with patch(
            "opnsense.tools.interfaces._get_client",
            return_value=mock_client,
        ):
            from opnsense.tools.interfaces import (
                opnsense__interfaces__list_vlan_interfaces,
            )

            result = await opnsense__interfaces__list_vlan_interfaces()

        assert len(result) == 2
        assert result[0]["tag"] == 10
        assert result[1]["tag"] == 20

    @pytest.mark.asyncio
    async def test_client_always_closed(self, vlan_26x_response: dict[str, Any]) -> None:
        """The client should be closed even if parsing fails."""
        mock_client = AsyncMock()
        mock_client.get_cached = AsyncMock(return_value=vlan_26x_response)
        mock_client.close = AsyncMock()

        with patch(
            "opnsense.tools.interfaces._get_client",
            return_value=mock_client,
        ):
            from opnsense.tools.interfaces import (
                opnsense__interfaces__list_vlan_interfaces,
            )

            await opnsense__interfaces__list_vlan_interfaces()

        mock_client.close.assert_called_once()
