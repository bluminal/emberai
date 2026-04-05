"""Shared pytest fixtures for Talos plugin tests.

Provides:
- ``fixture_dir`` -- path to the fixtures/ directory
- Individual fixtures loading each talosctl JSON/text output
- Edge case fixtures for degraded/error scenarios
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from tests.fixtures import load_fixture, load_json_fixture

FIXTURES_DIR = Path(__file__).parent / "fixtures"


# ---------------------------------------------------------------------------
# Fixture directory
# ---------------------------------------------------------------------------


@pytest.fixture()
def fixture_dir() -> Path:
    """Return the path to the test fixtures directory."""
    return FIXTURES_DIR


# ---------------------------------------------------------------------------
# JSON fixtures -- healthy cluster
# ---------------------------------------------------------------------------


@pytest.fixture()
def version_output() -> dict[str, Any]:
    """Load ``talosctl version -o json`` fixture."""
    return load_json_fixture("version.json")


@pytest.fixture()
def health_output() -> dict[str, Any]:
    """Load ``talosctl health -o json`` fixture (healthy 3-node cluster)."""
    return load_json_fixture("health.json")


@pytest.fixture()
def etcd_members_output() -> dict[str, Any]:
    """Load ``talosctl etcd members -o json`` fixture (3 members, one leader)."""
    return load_json_fixture("etcd_members.json")


@pytest.fixture()
def services_output() -> dict[str, Any]:
    """Load ``talosctl service -o json`` fixture (all services running)."""
    return load_json_fixture("services.json")


@pytest.fixture()
def get_members_output() -> dict[str, Any]:
    """Load ``talosctl get members -o json`` fixture (cluster members)."""
    return load_json_fixture("get_members.json")


@pytest.fixture()
def cluster_info_output() -> dict[str, Any]:
    """Load combined cluster info fixture."""
    return load_json_fixture("cluster_info.json")


# ---------------------------------------------------------------------------
# Text fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def dashboard_output() -> str:
    """Load ``talosctl dashboard`` text output fixture."""
    return load_fixture("dashboard.txt")


@pytest.fixture()
def dmesg_output() -> str:
    """Load ``talosctl dmesg`` kernel log fixture."""
    return load_fixture("dmesg.txt")


@pytest.fixture()
def logs_machined_output() -> str:
    """Load ``talosctl logs machined`` fixture."""
    return load_fixture("logs_machined.txt")


# ---------------------------------------------------------------------------
# Edge case fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def health_degraded_output() -> dict[str, Any]:
    """Load health fixture with one node not ready."""
    return load_json_fixture("health_degraded.json")


@pytest.fixture()
def etcd_single_member_output() -> dict[str, Any]:
    """Load etcd fixture with single member (non-HA)."""
    return load_json_fixture("etcd_single_member.json")


@pytest.fixture()
def version_unreachable_output() -> dict[str, Any]:
    """Load version fixture with unreachable node error."""
    return load_json_fixture("version_unreachable.json")
