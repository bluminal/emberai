"""Tests for Security skill tools.

Covers:
- get_ids_alerts: fixture parsing, severity filtering, time filtering
- get_ids_rules: search with and without filter
- get_ids_policy: settings retrieval
- get_certificates: fixture parsing, expiry data
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

import pytest

from tests.fixtures import load_fixture


def _make_client(get_returns: dict[str, Any] | None = None) -> AsyncMock:
    client = AsyncMock()
    if get_returns is not None:
        client.get = AsyncMock(return_value=get_returns)
    return client


# ---------------------------------------------------------------------------
# get_ids_alerts
# ---------------------------------------------------------------------------


class TestGetIDSAlerts:
    @pytest.mark.asyncio
    async def test_returns_all_alerts(self) -> None:
        from opnsense.tools.security import opnsense__security__get_ids_alerts

        fixture = load_fixture("ids_alerts.json")
        client = _make_client(fixture)

        alerts = await opnsense__security__get_ids_alerts(client)

        assert len(alerts) == 4
        client.get.assert_called_once_with(
            "ids",
            "service",
            "queryAlerts",
            params={},
        )

    @pytest.mark.asyncio
    async def test_normalizes_field_names(self) -> None:
        from opnsense.tools.security import opnsense__security__get_ids_alerts

        fixture = load_fixture("ids_alerts.json")
        client = _make_client(fixture)

        alerts = await opnsense__security__get_ids_alerts(client)

        first = alerts[0]
        assert first["timestamp"] == "2026-03-19T13:45:22.417Z"
        assert first["signature"] == "ET SCAN Potential SSH Scan"
        assert first["category"] == "Attempted Information Leak"
        assert first["severity"] == 2
        assert first["src_ip"] == "198.51.100.200"
        assert first["action"] == "alert"

    @pytest.mark.asyncio
    async def test_filter_by_severity_high_only(self) -> None:
        from opnsense.tools.security import opnsense__security__get_ids_alerts

        fixture = load_fixture("ids_alerts.json")
        client = _make_client(fixture)

        alerts = await opnsense__security__get_ids_alerts(client, severity=1)

        # Only severity 1 alerts should be returned
        assert len(alerts) == 1
        assert alerts[0]["severity"] == 1
        assert "Spamhaus" in alerts[0]["signature"]

    @pytest.mark.asyncio
    async def test_filter_by_severity_medium_and_above(self) -> None:
        from opnsense.tools.security import opnsense__security__get_ids_alerts

        fixture = load_fixture("ids_alerts.json")
        client = _make_client(fixture)

        alerts = await opnsense__security__get_ids_alerts(client, severity=2)

        # Severity 1 and 2 alerts should be returned
        assert len(alerts) == 2
        severities = {a["severity"] for a in alerts}
        assert severities == {1, 2}

    @pytest.mark.asyncio
    async def test_filter_by_severity_all(self) -> None:
        from opnsense.tools.security import opnsense__security__get_ids_alerts

        fixture = load_fixture("ids_alerts.json")
        client = _make_client(fixture)

        alerts = await opnsense__security__get_ids_alerts(client, severity=3)

        assert len(alerts) == 4

    @pytest.mark.asyncio
    async def test_hours_parameter_passed_to_api(self) -> None:
        from opnsense.tools.security import opnsense__security__get_ids_alerts

        client = _make_client({"rows": []})

        await opnsense__security__get_ids_alerts(client, hours=24)

        client.get.assert_called_once_with(
            "ids",
            "service",
            "queryAlerts",
            params={"fileSince": "24"},
        )

    @pytest.mark.asyncio
    async def test_empty_response(self) -> None:
        from opnsense.tools.security import opnsense__security__get_ids_alerts

        client = _make_client({"rows": []})
        alerts = await opnsense__security__get_ids_alerts(client)
        assert alerts == []

    @pytest.mark.asyncio
    async def test_drop_action_present(self) -> None:
        from opnsense.tools.security import opnsense__security__get_ids_alerts

        fixture = load_fixture("ids_alerts.json")
        client = _make_client(fixture)

        alerts = await opnsense__security__get_ids_alerts(client)

        drop_alerts = [a for a in alerts if a["action"] == "drop"]
        assert len(drop_alerts) >= 1


# ---------------------------------------------------------------------------
# get_ids_rules
# ---------------------------------------------------------------------------


class TestGetIDSRules:
    @pytest.mark.asyncio
    async def test_returns_rules(self) -> None:
        from opnsense.tools.security import opnsense__security__get_ids_rules

        data = {"rows": [{"sid": 1001, "msg": "Test rule"}]}
        client = _make_client(data)

        rules = await opnsense__security__get_ids_rules(client)

        assert len(rules) == 1
        assert rules[0]["sid"] == 1001

    @pytest.mark.asyncio
    async def test_filter_passed_to_api(self) -> None:
        from opnsense.tools.security import opnsense__security__get_ids_rules

        client = _make_client({"rows": []})

        await opnsense__security__get_ids_rules(client, filter_text="SSH")

        client.get.assert_called_once_with(
            "ids",
            "rule",
            "searchRule",
            params={"searchPhrase": "SSH"},
        )

    @pytest.mark.asyncio
    async def test_no_filter(self) -> None:
        from opnsense.tools.security import opnsense__security__get_ids_rules

        client = _make_client({"rows": []})

        await opnsense__security__get_ids_rules(client)

        client.get.assert_called_once_with(
            "ids",
            "rule",
            "searchRule",
            params={},
        )


# ---------------------------------------------------------------------------
# get_ids_policy
# ---------------------------------------------------------------------------


class TestGetIDSPolicy:
    @pytest.mark.asyncio
    async def test_returns_settings(self) -> None:
        from opnsense.tools.security import opnsense__security__get_ids_policy

        settings = {"ids": {"enabled": "1", "mode": "ips"}}
        client = _make_client(settings)

        result = await opnsense__security__get_ids_policy(client)

        assert result == settings
        client.get.assert_called_once_with("ids", "settings", "getSettings")


# ---------------------------------------------------------------------------
# get_certificates
# ---------------------------------------------------------------------------


class TestGetCertificates:
    @pytest.mark.asyncio
    async def test_returns_parsed_certs(self) -> None:
        from opnsense.tools.security import opnsense__security__get_certificates

        data = {
            "rows": [
                {
                    "cn": "fw.home.local",
                    "san": ["fw.home.local"],
                    "issuer": "Self-Signed",
                    "valid_from": "2025-01-01",
                    "valid_to": "2026-12-31",
                    "days_left": 287,
                    "in_use": ["webgui"],
                },
            ],
        }
        client = _make_client(data)

        certs = await opnsense__security__get_certificates(client)

        assert len(certs) == 1
        assert certs[0]["cn"] == "fw.home.local"
        assert certs[0]["days_until_expiry"] == 287
        assert "webgui" in certs[0]["in_use_for"]

    @pytest.mark.asyncio
    async def test_empty_response(self) -> None:
        from opnsense.tools.security import opnsense__security__get_certificates

        client = _make_client({"rows": []})
        certs = await opnsense__security__get_certificates(client)
        assert certs == []
