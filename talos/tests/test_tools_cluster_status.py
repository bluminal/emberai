"""Tests for the ``talos__cluster__status`` unified overview tool.

Covers:
- All data available: returns complete status
- Health check fails: returns partial status with health error
- Version check fails: returns partial status with version error
- Node list fails: returns partial status with node list error
- All calls fail: returns error status
- Single node cluster: correct count
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from talos.api.talosctl_client import TalosCtlClient, TalosCtlResult
from talos.errors import TalosCtlError


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_result(
    stdout: str = "",
    stderr: str = "",
    exit_code: int = 0,
    parsed: dict[str, Any] | list[Any] | None = None,
) -> TalosCtlResult:
    """Create a TalosCtlResult for mocking."""
    return TalosCtlResult(
        stdout=stdout,
        stderr=stderr,
        exit_code=exit_code,
        parsed=parsed,
    )


def _health_output_ok() -> dict[str, Any]:
    """Healthy 3-node cluster health JSON."""
    return {
        "messages": [
            {
                "metadata": {"hostname": "talos-cp-1", "error": ""},
                "health": {"ready": True, "unmet_conditions": []},
            },
            {
                "metadata": {"hostname": "talos-cp-2", "error": ""},
                "health": {"ready": True, "unmet_conditions": []},
            },
            {
                "metadata": {"hostname": "talos-w-1", "error": ""},
                "health": {"ready": True, "unmet_conditions": []},
            },
        ],
        "cluster_info": {
            "nodes_healthy": 3,
            "nodes_total": 3,
            "etcd_healthy": True,
            "kubernetes_healthy": True,
            "all_services_healthy": True,
        },
    }


def _version_output() -> dict[str, Any]:
    """Version JSON with client and server info."""
    return {
        "messages": [
            {
                "metadata": {"hostname": "talos-cp-1", "error": ""},
                "version": {
                    "tag": "v1.12.0",
                    "sha": "a1b2c3d4e5f6",
                    "built": "2025-12-15T10:30:00Z",
                    "go_version": "go1.23.4",
                    "os": "linux",
                    "arch": "amd64",
                },
            }
        ],
        "client_version": {
            "tag": "v1.12.0",
            "sha": "a1b2c3d4e5f6",
            "built": "2025-12-15T10:30:00Z",
            "go_version": "go1.23.4",
            "os": "darwin",
            "arch": "arm64",
        },
    }


def _members_output() -> dict[str, Any]:
    """``talosctl get members -o json`` with 2 CP + 1 worker."""
    return {
        "messages": [
            {
                "metadata": {"hostname": "talos-cp-1"},
                "members": [
                    {
                        "namespace": "cluster",
                        "type": "Member",
                        "id": "talos-cp-1",
                        "spec": {
                            "addresses": ["192.168.30.11"],
                            "hostname": "talos-cp-1",
                            "machine_type": "controlplane",
                            "operating_system": "Talos (v1.12.0)",
                            "config_version": "v1alpha1",
                        },
                    },
                    {
                        "namespace": "cluster",
                        "type": "Member",
                        "id": "talos-cp-2",
                        "spec": {
                            "addresses": ["192.168.30.12"],
                            "hostname": "talos-cp-2",
                            "machine_type": "controlplane",
                            "operating_system": "Talos (v1.12.0)",
                            "config_version": "v1alpha1",
                        },
                    },
                    {
                        "namespace": "cluster",
                        "type": "Member",
                        "id": "talos-w-1",
                        "spec": {
                            "addresses": ["192.168.30.21"],
                            "hostname": "talos-w-1",
                            "machine_type": "worker",
                            "operating_system": "Talos (v1.12.0)",
                            "config_version": "v1alpha1",
                        },
                    },
                ],
            }
        ]
    }


def _single_node_members() -> dict[str, Any]:
    """Single control-plane node cluster."""
    return {
        "messages": [
            {
                "metadata": {"hostname": "talos-solo"},
                "members": [
                    {
                        "namespace": "cluster",
                        "type": "Member",
                        "id": "talos-solo",
                        "spec": {
                            "addresses": ["192.168.30.10"],
                            "hostname": "talos-solo",
                            "machine_type": "controlplane",
                            "operating_system": "Talos (v1.12.0)",
                            "config_version": "v1alpha1",
                        },
                    }
                ],
            }
        ]
    }


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestClusterStatus:
    """Tests for talos__cluster__status."""

    @pytest.mark.asyncio
    async def test_all_data_available(self) -> None:
        """Complete status when all sub-calls succeed."""
        from talos.tools.cluster import talos__cluster__status

        health_json = _health_output_ok()
        version_json = _version_output()
        members_json = _members_output()

        health_result = _make_result(
            stdout=json.dumps(health_json), parsed=health_json
        )
        version_result = _make_result(
            stdout=json.dumps(version_json), parsed=version_json
        )
        members_result = _make_result(
            stdout=json.dumps(members_json), parsed=members_json
        )

        # The tool calls health and version via their tool functions
        # (which internally call client.run), and then calls client.run
        # for members directly.  We mock at the TalosCtlClient.run level.
        # Calls are: health, version, members (3 calls).
        with patch.object(
            TalosCtlClient,
            "run",
            new_callable=AsyncMock,
            side_effect=[health_result, version_result, members_result],
        ):
            result = await talos__cluster__status()

        assert result["status"] == "ok"
        assert result["operation"] == "cluster_status"
        assert result["severity"] == "OK"
        assert "errors" not in result

        # Health info
        assert result["health"]["nodes_healthy"] == 3
        assert result["health"]["etcd_healthy"] is True

        # Version info
        assert result["versions"]["talos_client"] == "v1.12.0"
        assert result["versions"]["talos_server"] == "v1.12.0"

        # Node inventory
        assert result["nodes"]["total"] == 3
        assert result["nodes"]["control_plane"] == 2
        assert result["nodes"]["workers"] == 1
        assert len(result["nodes"]["details"]) == 3

        # Per-node ready status merged from health
        cp1 = next(
            n for n in result["nodes"]["details"] if n["hostname"] == "talos-cp-1"
        )
        assert cp1["ready"] is True
        assert cp1["role"] == "controlplane"
        assert "192.168.30.11" in cp1["addresses"]

        # Message
        assert "2 control plane" in result["message"]
        assert "1 worker" in result["message"]

    @pytest.mark.asyncio
    async def test_health_check_fails(self) -> None:
        """Partial status when health sub-call returns error.

        The health tool catches TalosCtlError internally and returns
        a dict with ``status=error`` and ``severity=CRITICAL``.  The
        status tool should propagate that severity and still populate
        version and nodes.
        """
        from talos.tools.cluster import talos__cluster__status

        version_json = _version_output()
        members_json = _members_output()

        version_result = _make_result(
            stdout=json.dumps(version_json), parsed=version_json
        )
        members_result = _make_result(
            stdout=json.dumps(members_json), parsed=members_json
        )

        # Health call raises TalosCtlError (caught by health tool internally,
        # returning status=error dict); version and members succeed.
        with patch.object(
            TalosCtlClient,
            "run",
            new_callable=AsyncMock,
            side_effect=[
                TalosCtlError(
                    "health check timed out",
                    stderr="deadline exceeded",
                    exit_code=1,
                ),
                version_result,
                members_result,
            ],
        ):
            result = await talos__cluster__status()

        assert result["status"] == "ok"
        # Health tool returns CRITICAL when talosctl health fails
        assert result["severity"] == "CRITICAL"
        assert "error" in result["health"]

        # Version and nodes should still be populated
        assert result["versions"]["talos_client"] == "v1.12.0"
        assert result["nodes"]["total"] == 3

    @pytest.mark.asyncio
    async def test_version_check_fails(self) -> None:
        """Partial status when version sub-call returns error.

        The version tool catches TalosCtlError internally and returns
        a dict with ``status=error``.  The status tool should report
        an error in versions but still populate health and nodes.
        """
        from talos.tools.cluster import talos__cluster__status

        health_json = _health_output_ok()
        members_json = _members_output()

        health_result = _make_result(
            stdout=json.dumps(health_json), parsed=health_json
        )
        members_result = _make_result(
            stdout=json.dumps(members_json), parsed=members_json
        )

        # Version call raises (caught by version tool, returning error dict);
        # health and members succeed.
        with patch.object(
            TalosCtlClient,
            "run",
            new_callable=AsyncMock,
            side_effect=[
                health_result,
                TalosCtlError(
                    "connection refused",
                    stderr="connection refused",
                    exit_code=1,
                ),
                members_result,
            ],
        ):
            result = await talos__cluster__status()

        assert result["status"] == "ok"
        assert result["severity"] == "OK"

        # Health and nodes should still be populated
        assert result["health"]["nodes_healthy"] == 3
        assert result["nodes"]["total"] == 3
        assert "error" in result["versions"]

    @pytest.mark.asyncio
    async def test_node_list_fails(self) -> None:
        """Partial status returned when members sub-call fails."""
        from talos.tools.cluster import talos__cluster__status

        health_json = _health_output_ok()
        version_json = _version_output()

        health_result = _make_result(
            stdout=json.dumps(health_json), parsed=health_json
        )
        version_result = _make_result(
            stdout=json.dumps(version_json), parsed=version_json
        )

        # Members call raises; health and version succeed
        with patch.object(
            TalosCtlClient,
            "run",
            new_callable=AsyncMock,
            side_effect=[
                health_result,
                version_result,
                TalosCtlError(
                    "failed to get members",
                    stderr="context deadline exceeded",
                    exit_code=1,
                ),
            ],
        ):
            result = await talos__cluster__status()

        assert result["status"] == "ok"
        assert result["severity"] == "OK"
        assert "errors" in result
        assert len(result["errors"]) == 1
        assert result["errors"][0]["component"] == "members"

        # Health and versions should be populated
        assert result["health"]["nodes_healthy"] == 3
        assert result["versions"]["talos_server"] == "v1.12.0"

        # Nodes should have zero counts (no members data)
        assert result["nodes"]["total"] == 0
        assert result["nodes"]["details"] == []
        assert "Partial status" in result["message"]

    @pytest.mark.asyncio
    async def test_all_calls_fail(self) -> None:
        """Error status when all three underlying client calls fail.

        Health and version tools catch TalosCtlError internally, returning
        error dicts.  The members call is direct, so it populates the
        errors list.  Overall: health=CRITICAL, version=error, members=error
        in the errors list (1 entry for members).
        """
        from talos.tools.cluster import talos__cluster__status

        with patch.object(
            TalosCtlClient,
            "run",
            new_callable=AsyncMock,
            side_effect=[
                TalosCtlError("health failed", stderr="err", exit_code=1),
                TalosCtlError("version failed", stderr="err", exit_code=1),
                TalosCtlError("members failed", stderr="err", exit_code=1),
            ],
        ):
            result = await talos__cluster__status()

        # Health tool catches its error and returns CRITICAL dict
        assert result["severity"] == "CRITICAL"
        assert "error" in result["health"]

        # Version tool catches its error and returns error dict
        assert "error" in result["versions"]

        # Members call is direct -- exception lands in errors list
        assert "errors" in result
        assert len(result["errors"]) == 1
        assert result["errors"][0]["component"] == "members"

        # Nodes should have zero counts since members failed
        assert result["nodes"]["total"] == 0

    @pytest.mark.asyncio
    async def test_all_calls_fail_via_unexpected_exception(self) -> None:
        """Error status when all sub-calls raise unexpected exceptions.

        Uses RuntimeError (not TalosCtlError) to bypass the internal
        error handling in health/version tools, forcing all three to
        land in the status tool's except blocks.
        """
        from talos.tools.cluster import talos__cluster__status

        with patch.object(
            TalosCtlClient,
            "run",
            new_callable=AsyncMock,
            side_effect=[
                RuntimeError("health boom"),
                RuntimeError("version boom"),
                RuntimeError("members boom"),
            ],
        ):
            result = await talos__cluster__status()

        assert result["status"] == "error"
        assert result["severity"] == "UNKNOWN"
        assert len(result["errors"]) == 3
        assert "All status sub-queries failed" in result["message"]

        components = {e["component"] for e in result["errors"]}
        assert components == {"health", "version", "members"}

    @pytest.mark.asyncio
    async def test_single_node_cluster(self) -> None:
        """Correct counts for a single control-plane node."""
        from talos.tools.cluster import talos__cluster__status

        health_json = {
            "messages": [
                {
                    "metadata": {"hostname": "talos-solo", "error": ""},
                    "health": {"ready": True, "unmet_conditions": []},
                }
            ],
            "cluster_info": {
                "nodes_healthy": 1,
                "nodes_total": 1,
                "etcd_healthy": True,
                "kubernetes_healthy": True,
                "all_services_healthy": True,
            },
        }
        version_json = _version_output()
        members_json = _single_node_members()

        health_result = _make_result(
            stdout=json.dumps(health_json), parsed=health_json
        )
        version_result = _make_result(
            stdout=json.dumps(version_json), parsed=version_json
        )
        members_result = _make_result(
            stdout=json.dumps(members_json), parsed=members_json
        )

        with patch.object(
            TalosCtlClient,
            "run",
            new_callable=AsyncMock,
            side_effect=[health_result, version_result, members_result],
        ):
            result = await talos__cluster__status()

        assert result["status"] == "ok"
        assert result["severity"] == "OK"
        assert result["nodes"]["total"] == 1
        assert result["nodes"]["control_plane"] == 1
        assert result["nodes"]["workers"] == 0
        assert len(result["nodes"]["details"]) == 1
        assert result["nodes"]["details"][0]["hostname"] == "talos-solo"
        assert result["nodes"]["details"][0]["role"] == "controlplane"
        assert result["nodes"]["details"][0]["ready"] is True

    @pytest.mark.asyncio
    async def test_health_returns_error_status(self) -> None:
        """Health sub-call returns error dict (not exception) -- severity propagated."""
        from talos.tools.cluster import talos__cluster__status

        # Simulate talosctl health exiting non-zero (caught internally by
        # talos__cluster__health, which returns a dict with status=error).
        health_error_result = _make_result(stdout="", stderr="etcd down", exit_code=1)
        version_json = _version_output()
        members_json = _members_output()
        version_result = _make_result(
            stdout=json.dumps(version_json), parsed=version_json
        )
        members_result = _make_result(
            stdout=json.dumps(members_json), parsed=members_json
        )

        # The health call raises TalosCtlError which the health tool catches
        # and returns as a dict.  So we simulate that sequence: the first
        # client.run raises, then version and members succeed.
        with patch.object(
            TalosCtlClient,
            "run",
            new_callable=AsyncMock,
            side_effect=[
                TalosCtlError(
                    "health check failed: etcd unhealthy",
                    stderr="etcd cluster is unavailable",
                    exit_code=1,
                ),
                version_result,
                members_result,
            ],
        ):
            result = await talos__cluster__status()

        # Health tool catches TalosCtlError and returns CRITICAL dict.
        # Status tool sees that and propagates severity.
        assert result["severity"] == "CRITICAL"
        assert "errors" not in result  # no exception = no errors list entry
        assert result["versions"]["talos_client"] == "v1.12.0"
        assert result["nodes"]["total"] == 3
