# SPDX-License-Identifier: MIT
"""Tests for firewall filter rule CRUD tools (Task 193).

Covers:
- create_rule: success, write gate, validation (action, direction, ipprotocol),
  sequence field, apply workflow
- update_rule: success, partial update, no fields, write gate, apply workflow
- delete_rule: success, getRule failure fallback, write gate, apply workflow
- All writes: savepoint/apply/cancelRollback called, client closed

Test strategy:
- Mock OPNsenseClient at the _get_client factory level
- Verify payloads sent to client.write / client.post
- Verify write gate enforcement (env var + apply flag)
- Verify cache flush / apply called after every write
"""

from __future__ import annotations

import os
from typing import Any
from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest

from opnsense.errors import APIError, ValidationError, WriteGateError, WriteGateReason


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_mock_client(**kwargs: Any) -> MagicMock:
    """Create a mocked OPNsenseClient with sensible defaults."""
    from opnsense.api.opnsense_client import OPNsenseClient

    client = MagicMock(spec=OPNsenseClient)
    client.close = AsyncMock()
    client.get = AsyncMock(return_value=kwargs.get("get_response", {}))
    client.get_cached = AsyncMock(return_value=kwargs.get("get_cached_response", {}))
    client.write = AsyncMock(
        return_value=kwargs.get(
            "write_response", {"result": "saved", "uuid": "new-rule-uuid-1234"}
        )
    )
    client.post = AsyncMock(
        return_value=kwargs.get("post_response", {"revision": "rev-abc"})
    )
    client.reconfigure = AsyncMock(return_value={"status": "ok"})
    client.cache = MagicMock()
    client.cache.flush_by_prefix = AsyncMock()
    return client


@pytest.fixture()
def mock_client() -> MagicMock:
    return _make_mock_client()


@pytest.fixture(autouse=True)
def _enable_writes():
    """Enable writes by default -- individual tests can override."""
    with patch.dict(os.environ, {"OPNSENSE_WRITE_ENABLED": "true"}):
        yield


# ===========================================================================
# create_rule tests
# ===========================================================================


class TestCreateRule:
    """opnsense__firewall__create_rule -- filter rule creation."""

    async def test_create_rule_success(self, mock_client: MagicMock) -> None:
        """Successful creation returns UUID and applies via savepoint workflow."""
        with patch("opnsense.tools.firewall._get_client", return_value=mock_client):
            from opnsense.tools.firewall import opnsense__firewall__create_rule

            result = await opnsense__firewall__create_rule(
                interface="lan",
                action="pass",
                source_net="192.168.1.0/24",
                destination_net="any",
                protocol="TCP",
                description="Test rule",
                apply=True,
            )

        assert result["status"] == "created"
        assert result["uuid"] == "new-rule-uuid-1234"
        assert result["action"] == "pass"
        assert result["interface"] == "lan"
        assert result["source"] == "192.168.1.0/24"
        assert result["destination"] == "any"
        assert result["applied"] is True

        # Verify the write payload
        write_call = mock_client.write.call_args
        rule_payload = write_call.kwargs["data"]["rule"]
        assert rule_payload["action"] == "pass"
        assert rule_payload["interface"] == "lan"
        assert rule_payload["source_net"] == "192.168.1.0/24"
        assert rule_payload["destination_net"] == "any"
        assert rule_payload["protocol"] == "TCP"
        assert rule_payload["description"] == "Test rule"
        assert rule_payload["enabled"] == "1"
        assert rule_payload["direction"] == "in"
        assert rule_payload["ipprotocol"] == "inet"

    async def test_create_rule_write_gate_env_disabled(self) -> None:
        """Write gate blocks when OPNSENSE_WRITE_ENABLED is not true."""
        with patch.dict(os.environ, {"OPNSENSE_WRITE_ENABLED": "false"}):
            from opnsense.tools.firewall import opnsense__firewall__create_rule

            with pytest.raises(WriteGateError) as exc_info:
                await opnsense__firewall__create_rule(
                    interface="lan",
                    action="pass",
                    source_net="any",
                    destination_net="any",
                    apply=True,
                )
            assert exc_info.value.reason == WriteGateReason.ENV_VAR_DISABLED

    async def test_create_rule_write_gate_apply_missing(self) -> None:
        """Write gate blocks when apply=False."""
        from opnsense.tools.firewall import opnsense__firewall__create_rule

        with pytest.raises(WriteGateError) as exc_info:
            await opnsense__firewall__create_rule(
                interface="lan",
                action="pass",
                source_net="any",
                destination_net="any",
                apply=False,
            )
        assert exc_info.value.reason == WriteGateReason.APPLY_FLAG_MISSING

    async def test_create_rule_invalid_action(self) -> None:
        """Invalid action raises ValidationError."""
        from opnsense.tools.firewall import opnsense__firewall__create_rule

        with pytest.raises(ValidationError, match="Action must be one of"):
            await opnsense__firewall__create_rule(
                interface="lan",
                action="allow",
                source_net="any",
                destination_net="any",
                apply=True,
            )

    async def test_create_rule_invalid_direction(self) -> None:
        """Invalid direction raises ValidationError."""
        from opnsense.tools.firewall import opnsense__firewall__create_rule

        with pytest.raises(ValidationError, match="Direction must be one of"):
            await opnsense__firewall__create_rule(
                interface="lan",
                action="pass",
                source_net="any",
                destination_net="any",
                direction="forward",
                apply=True,
            )

    async def test_create_rule_invalid_ipprotocol(self) -> None:
        """Invalid ipprotocol raises ValidationError."""
        from opnsense.tools.firewall import opnsense__firewall__create_rule

        with pytest.raises(ValidationError, match="IP protocol must be one of"):
            await opnsense__firewall__create_rule(
                interface="lan",
                action="pass",
                source_net="any",
                destination_net="any",
                ipprotocol="inet8",
                apply=True,
            )

    async def test_create_rule_empty_interface(self) -> None:
        """Empty interface raises ValidationError."""
        from opnsense.tools.firewall import opnsense__firewall__create_rule

        with pytest.raises(ValidationError, match="Interface must not be empty"):
            await opnsense__firewall__create_rule(
                interface="",
                action="pass",
                source_net="any",
                destination_net="any",
                apply=True,
            )

    async def test_create_rule_with_sequence(self, mock_client: MagicMock) -> None:
        """Sequence field included in payload when specified."""
        with patch("opnsense.tools.firewall._get_client", return_value=mock_client):
            from opnsense.tools.firewall import opnsense__firewall__create_rule

            await opnsense__firewall__create_rule(
                interface="lan",
                action="block",
                source_net="any",
                destination_net="any",
                sequence=5,
                apply=True,
            )

        rule_payload = mock_client.write.call_args.kwargs["data"]["rule"]
        assert rule_payload["sequence"] == "5"

    async def test_create_rule_without_sequence(self, mock_client: MagicMock) -> None:
        """Sequence field NOT in payload when not specified."""
        with patch("opnsense.tools.firewall._get_client", return_value=mock_client):
            from opnsense.tools.firewall import opnsense__firewall__create_rule

            await opnsense__firewall__create_rule(
                interface="wan",
                action="reject",
                source_net="any",
                destination_net="any",
                apply=True,
            )

        rule_payload = mock_client.write.call_args.kwargs["data"]["rule"]
        assert "sequence" not in rule_payload

    async def test_create_rule_savepoint_apply_workflow(
        self, mock_client: MagicMock
    ) -> None:
        """Savepoint, apply, and cancelRollback are called in order."""
        with patch("opnsense.tools.firewall._get_client", return_value=mock_client):
            from opnsense.tools.firewall import opnsense__firewall__create_rule

            await opnsense__firewall__create_rule(
                interface="lan",
                action="pass",
                source_net="any",
                destination_net="any",
                apply=True,
            )

        # client.post should be called for savepoint, apply/rev, cancelRollback/rev
        post_calls = mock_client.post.call_args_list
        assert len(post_calls) == 3
        assert post_calls[0] == call("firewall", "filter", "savepoint")
        assert post_calls[1] == call("firewall", "filter", "apply/rev-abc")
        assert post_calls[2] == call("firewall", "filter", "cancelRollback/rev-abc")

    async def test_create_rule_client_always_closed(
        self, mock_client: MagicMock
    ) -> None:
        """Client is closed even when write fails."""
        mock_client.write = AsyncMock(side_effect=Exception("API down"))
        with patch("opnsense.tools.firewall._get_client", return_value=mock_client):
            from opnsense.tools.firewall import opnsense__firewall__create_rule

            with pytest.raises(Exception, match="API down"):
                await opnsense__firewall__create_rule(
                    interface="lan",
                    action="pass",
                    source_net="any",
                    destination_net="any",
                    apply=True,
                )

        mock_client.close.assert_awaited_once()

    async def test_create_rule_api_error_on_failure(
        self, mock_client: MagicMock
    ) -> None:
        """APIError raised when addRule response indicates failure."""
        mock_client.write = AsyncMock(
            return_value={"result": "failed", "validations": {"interface": "invalid"}}
        )
        with patch("opnsense.tools.firewall._get_client", return_value=mock_client):
            from opnsense.tools.firewall import opnsense__firewall__create_rule

            with pytest.raises(APIError, match="Failed to create firewall rule"):
                await opnsense__firewall__create_rule(
                    interface="lan",
                    action="pass",
                    source_net="any",
                    destination_net="any",
                    apply=True,
                )

    async def test_create_rule_log_and_quick_flags(
        self, mock_client: MagicMock
    ) -> None:
        """Log=True and quick=False are encoded as '1' and '0'."""
        with patch("opnsense.tools.firewall._get_client", return_value=mock_client):
            from opnsense.tools.firewall import opnsense__firewall__create_rule

            await opnsense__firewall__create_rule(
                interface="lan",
                action="pass",
                source_net="any",
                destination_net="any",
                log=True,
                quick=False,
                apply=True,
            )

        rule_payload = mock_client.write.call_args.kwargs["data"]["rule"]
        assert rule_payload["log"] == "1"
        assert rule_payload["quick"] == "0"


# ===========================================================================
# update_rule tests
# ===========================================================================


class TestUpdateRule:
    """opnsense__firewall__update_rule -- partial rule updates."""

    async def test_update_rule_success(self, mock_client: MagicMock) -> None:
        """Successful update returns changed fields and applies."""
        mock_client.write = AsyncMock(return_value={"result": "saved"})
        with patch("opnsense.tools.firewall._get_client", return_value=mock_client):
            from opnsense.tools.firewall import opnsense__firewall__update_rule

            result = await opnsense__firewall__update_rule(
                uuid="abc-123",
                action="block",
                description="Updated rule",
                apply=True,
            )

        assert result["status"] == "updated"
        assert result["uuid"] == "abc-123"
        assert "action" in result["updated_fields"]
        assert "description" in result["updated_fields"]
        assert result["applied"] is True

        # Verify partial payload -- only changed fields
        rule_payload = mock_client.write.call_args.kwargs["data"]["rule"]
        assert rule_payload == {"action": "block", "description": "Updated rule"}

    async def test_update_rule_no_fields_specified(self) -> None:
        """No fields specified raises ValidationError."""
        mock_client = _make_mock_client()
        with patch("opnsense.tools.firewall._get_client", return_value=mock_client):
            from opnsense.tools.firewall import opnsense__firewall__update_rule

            with pytest.raises(ValidationError, match="No fields specified"):
                await opnsense__firewall__update_rule(
                    uuid="abc-123",
                    apply=True,
                )

    async def test_update_rule_partial_update_only_sends_changed(
        self, mock_client: MagicMock
    ) -> None:
        """Only action and description sent -- other fields NOT in payload."""
        mock_client.write = AsyncMock(return_value={"result": "saved"})
        with patch("opnsense.tools.firewall._get_client", return_value=mock_client):
            from opnsense.tools.firewall import opnsense__firewall__update_rule

            await opnsense__firewall__update_rule(
                uuid="abc-123",
                action="reject",
                description="Partial",
                apply=True,
            )

        rule_payload = mock_client.write.call_args.kwargs["data"]["rule"]
        assert set(rule_payload.keys()) == {"action", "description"}
        # Verify fields that were NOT specified are absent
        assert "interface" not in rule_payload
        assert "source_net" not in rule_payload
        assert "destination_net" not in rule_payload
        assert "protocol" not in rule_payload
        assert "enabled" not in rule_payload
        assert "log" not in rule_payload

    async def test_update_rule_write_gate_env_disabled(self) -> None:
        """Write gate blocks when env var is disabled."""
        with patch.dict(os.environ, {"OPNSENSE_WRITE_ENABLED": "false"}):
            from opnsense.tools.firewall import opnsense__firewall__update_rule

            with pytest.raises(WriteGateError) as exc_info:
                await opnsense__firewall__update_rule(
                    uuid="abc-123",
                    action="pass",
                    apply=True,
                )
            assert exc_info.value.reason == WriteGateReason.ENV_VAR_DISABLED

    async def test_update_rule_write_gate_apply_missing(self) -> None:
        """Write gate blocks when apply=False."""
        from opnsense.tools.firewall import opnsense__firewall__update_rule

        with pytest.raises(WriteGateError) as exc_info:
            await opnsense__firewall__update_rule(
                uuid="abc-123",
                action="pass",
                apply=False,
            )
        assert exc_info.value.reason == WriteGateReason.APPLY_FLAG_MISSING

    async def test_update_rule_invalid_action(self) -> None:
        """Invalid action raises ValidationError."""
        from opnsense.tools.firewall import opnsense__firewall__update_rule

        with pytest.raises(ValidationError, match="Action must be one of"):
            await opnsense__firewall__update_rule(
                uuid="abc-123",
                action="deny",
                apply=True,
            )

    async def test_update_rule_invalid_direction(self) -> None:
        """Invalid direction raises ValidationError."""
        from opnsense.tools.firewall import opnsense__firewall__update_rule

        with pytest.raises(ValidationError, match="Direction must be one of"):
            await opnsense__firewall__update_rule(
                uuid="abc-123",
                direction="both",
                apply=True,
            )

    async def test_update_rule_invalid_ipprotocol(self) -> None:
        """Invalid ipprotocol raises ValidationError."""
        from opnsense.tools.firewall import opnsense__firewall__update_rule

        with pytest.raises(ValidationError, match="IP protocol must be one of"):
            await opnsense__firewall__update_rule(
                uuid="abc-123",
                ipprotocol="inet99",
                apply=True,
            )

    async def test_update_rule_boolean_fields_encoded(
        self, mock_client: MagicMock
    ) -> None:
        """Boolean fields enabled/quick/log encoded as '1'/'0' strings."""
        mock_client.write = AsyncMock(return_value={"result": "saved"})
        with patch("opnsense.tools.firewall._get_client", return_value=mock_client):
            from opnsense.tools.firewall import opnsense__firewall__update_rule

            await opnsense__firewall__update_rule(
                uuid="abc-123",
                enabled=False,
                quick=True,
                log=True,
                apply=True,
            )

        rule_payload = mock_client.write.call_args.kwargs["data"]["rule"]
        assert rule_payload["enabled"] == "0"
        assert rule_payload["quick"] == "1"
        assert rule_payload["log"] == "1"

    async def test_update_rule_savepoint_apply_workflow(
        self, mock_client: MagicMock
    ) -> None:
        """Savepoint/apply/cancelRollback workflow called after update."""
        mock_client.write = AsyncMock(return_value={"result": "saved"})
        with patch("opnsense.tools.firewall._get_client", return_value=mock_client):
            from opnsense.tools.firewall import opnsense__firewall__update_rule

            await opnsense__firewall__update_rule(
                uuid="abc-123",
                action="block",
                apply=True,
            )

        post_calls = mock_client.post.call_args_list
        assert len(post_calls) == 3
        assert post_calls[0] == call("firewall", "filter", "savepoint")
        assert post_calls[1] == call("firewall", "filter", "apply/rev-abc")
        assert post_calls[2] == call("firewall", "filter", "cancelRollback/rev-abc")

    async def test_update_rule_setRule_endpoint(
        self, mock_client: MagicMock
    ) -> None:
        """Write goes to setRule/{uuid} endpoint."""
        mock_client.write = AsyncMock(return_value={"result": "saved"})
        with patch("opnsense.tools.firewall._get_client", return_value=mock_client):
            from opnsense.tools.firewall import opnsense__firewall__update_rule

            await opnsense__firewall__update_rule(
                uuid="rule-uuid-5678",
                action="pass",
                apply=True,
            )

        mock_client.write.assert_awaited_once_with(
            "firewall",
            "filter",
            "setRule/rule-uuid-5678",
            data={"rule": {"action": "pass"}},
        )

    async def test_update_rule_sequence_as_string(
        self, mock_client: MagicMock
    ) -> None:
        """Sequence int is converted to string in payload."""
        mock_client.write = AsyncMock(return_value={"result": "saved"})
        with patch("opnsense.tools.firewall._get_client", return_value=mock_client):
            from opnsense.tools.firewall import opnsense__firewall__update_rule

            await opnsense__firewall__update_rule(
                uuid="abc-123",
                sequence=10,
                apply=True,
            )

        rule_payload = mock_client.write.call_args.kwargs["data"]["rule"]
        assert rule_payload["sequence"] == "10"


# ===========================================================================
# delete_rule tests
# ===========================================================================


class TestDeleteRule:
    """opnsense__firewall__delete_rule -- rule deletion."""

    async def test_delete_rule_success(self, mock_client: MagicMock) -> None:
        """Successful deletion returns UUID, description, and applied status."""
        mock_client.get = AsyncMock(
            return_value={"rule": {"description": "Block bad traffic"}}
        )
        mock_client.write = AsyncMock(return_value={"result": "saved"})
        with patch("opnsense.tools.firewall._get_client", return_value=mock_client):
            from opnsense.tools.firewall import opnsense__firewall__delete_rule

            result = await opnsense__firewall__delete_rule(
                uuid="del-uuid-1234",
                apply=True,
            )

        assert result["status"] == "deleted"
        assert result["uuid"] == "del-uuid-1234"
        assert result["description"] == "Block bad traffic"
        assert result["applied"] is True

        # Verify delRule endpoint
        mock_client.write.assert_awaited_once_with(
            "firewall", "filter", "delRule/del-uuid-1234"
        )

    async def test_delete_rule_get_info_fails_gracefully(
        self, mock_client: MagicMock
    ) -> None:
        """If getRule fails, delete still proceeds with 'Unknown' description."""
        mock_client.get = AsyncMock(side_effect=APIError("Not found", status_code=404))
        mock_client.write = AsyncMock(return_value={"result": "saved"})
        with patch("opnsense.tools.firewall._get_client", return_value=mock_client):
            from opnsense.tools.firewall import opnsense__firewall__delete_rule

            result = await opnsense__firewall__delete_rule(
                uuid="missing-uuid",
                apply=True,
            )

        assert result["status"] == "deleted"
        assert result["description"] == "Unknown"
        # Delete should still have been called
        mock_client.write.assert_awaited_once()

    async def test_delete_rule_write_gate_env_disabled(self) -> None:
        """Write gate blocks when env var is disabled."""
        with patch.dict(os.environ, {"OPNSENSE_WRITE_ENABLED": "false"}):
            from opnsense.tools.firewall import opnsense__firewall__delete_rule

            with pytest.raises(WriteGateError) as exc_info:
                await opnsense__firewall__delete_rule(
                    uuid="abc-123",
                    apply=True,
                )
            assert exc_info.value.reason == WriteGateReason.ENV_VAR_DISABLED

    async def test_delete_rule_write_gate_apply_missing(self) -> None:
        """Write gate blocks when apply=False."""
        from opnsense.tools.firewall import opnsense__firewall__delete_rule

        with pytest.raises(WriteGateError) as exc_info:
            await opnsense__firewall__delete_rule(
                uuid="abc-123",
                apply=False,
            )
        assert exc_info.value.reason == WriteGateReason.APPLY_FLAG_MISSING

    async def test_delete_rule_savepoint_apply_workflow(
        self, mock_client: MagicMock
    ) -> None:
        """Savepoint/apply/cancelRollback workflow called after delete."""
        mock_client.write = AsyncMock(return_value={"result": "saved"})
        with patch("opnsense.tools.firewall._get_client", return_value=mock_client):
            from opnsense.tools.firewall import opnsense__firewall__delete_rule

            await opnsense__firewall__delete_rule(
                uuid="del-uuid",
                apply=True,
            )

        post_calls = mock_client.post.call_args_list
        assert len(post_calls) == 3
        assert post_calls[0] == call("firewall", "filter", "savepoint")
        assert post_calls[1] == call("firewall", "filter", "apply/rev-abc")
        assert post_calls[2] == call("firewall", "filter", "cancelRollback/rev-abc")

    async def test_delete_rule_api_error_on_failure(
        self, mock_client: MagicMock
    ) -> None:
        """APIError raised when delRule response indicates failure."""
        mock_client.write = AsyncMock(
            return_value={"result": "failed"}
        )
        with patch("opnsense.tools.firewall._get_client", return_value=mock_client):
            from opnsense.tools.firewall import opnsense__firewall__delete_rule

            with pytest.raises(APIError, match="Failed to delete firewall rule"):
                await opnsense__firewall__delete_rule(
                    uuid="bad-uuid",
                    apply=True,
                )

    async def test_delete_rule_client_always_closed(
        self, mock_client: MagicMock
    ) -> None:
        """Client is closed even when delete fails."""
        mock_client.write = AsyncMock(side_effect=Exception("Network error"))
        with patch("opnsense.tools.firewall._get_client", return_value=mock_client):
            from opnsense.tools.firewall import opnsense__firewall__delete_rule

            with pytest.raises(Exception, match="Network error"):
                await opnsense__firewall__delete_rule(
                    uuid="abc-123",
                    apply=True,
                )

        mock_client.close.assert_awaited_once()


# ===========================================================================
# Matrix alias resolution tests
# ===========================================================================


class TestMatrixAliasResolution:
    """_resolve_alias_names -- alias resolution for matrix rules."""

    async def test_cidr_passes_through(self) -> None:
        """CIDR addresses are used as-is without alias lookup."""
        mock_aliases = [{"name": "LAN_NET", "type": "network", "content": "10.0.0.0/8"}]
        with patch(
            "opnsense.tools.firewall.opnsense__firewall__list_aliases",
            new_callable=AsyncMock,
            return_value=mock_aliases,
        ):
            from opnsense.tools.commands import _resolve_alias_names

            rules = [{"src": "172.16.30.0/24", "dst": "10.0.0.0/8", "action": "pass"}]
            resolved = await _resolve_alias_names(rules)

        assert resolved[0]["src"] == "172.16.30.0/24"
        assert resolved[0]["dst"] == "10.0.0.0/8"

    async def test_alias_name_resolved(self) -> None:
        """Known alias name is accepted and passed through."""
        mock_aliases = [
            {"name": "RFC1918", "type": "network", "content": "10.0.0.0/8\n172.16.0.0/12"},
            {"name": "DNS_Servers", "type": "host", "content": "1.1.1.1"},
        ]
        with patch(
            "opnsense.tools.firewall.opnsense__firewall__list_aliases",
            new_callable=AsyncMock,
            return_value=mock_aliases,
        ):
            from opnsense.tools.commands import _resolve_alias_names

            rules = [{"src": "RFC1918", "dst": "DNS_Servers", "action": "pass"}]
            resolved = await _resolve_alias_names(rules)

        assert resolved[0]["src"] == "RFC1918"
        assert resolved[0]["dst"] == "DNS_Servers"

    async def test_unknown_alias_error_with_available_list(self) -> None:
        """Unknown alias raises ValidationError listing available aliases."""
        mock_aliases = [
            {"name": "RFC1918", "type": "network", "content": "10.0.0.0/8"},
            {"name": "LAN_NET", "type": "network", "content": "192.168.1.0/24"},
        ]
        with patch(
            "opnsense.tools.firewall.opnsense__firewall__list_aliases",
            new_callable=AsyncMock,
            return_value=mock_aliases,
        ):
            from opnsense.tools.commands import _resolve_alias_names

            rules = [{"src": "NONEXISTENT", "dst": "any", "action": "pass"}]
            with pytest.raises(ValidationError, match="Unknown alias 'NONEXISTENT'"):
                await _resolve_alias_names(rules)

    async def test_any_passes_through(self) -> None:
        """'any' is treated as a special keyword, not an alias."""
        mock_aliases: list[dict[str, str]] = []
        with patch(
            "opnsense.tools.firewall.opnsense__firewall__list_aliases",
            new_callable=AsyncMock,
            return_value=mock_aliases,
        ):
            from opnsense.tools.commands import _resolve_alias_names

            rules = [{"src": "any", "dst": "any", "action": "block"}]
            resolved = await _resolve_alias_names(rules)

        assert resolved[0]["src"] == "any"
        assert resolved[0]["dst"] == "any"

    async def test_bare_ip_passes_through(self) -> None:
        """Bare IP addresses pass through without alias lookup."""
        mock_aliases: list[dict[str, str]] = []
        with patch(
            "opnsense.tools.firewall.opnsense__firewall__list_aliases",
            new_callable=AsyncMock,
            return_value=mock_aliases,
        ):
            from opnsense.tools.commands import _resolve_alias_names

            rules = [{"src": "192.168.1.1", "dst": "10.0.0.1", "action": "pass"}]
            resolved = await _resolve_alias_names(rules)

        assert resolved[0]["src"] == "192.168.1.1"
        assert resolved[0]["dst"] == "10.0.0.1"
