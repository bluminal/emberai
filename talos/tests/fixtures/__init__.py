"""Test fixture loader for Talos Linux talosctl output.

Supports both JSON and text fixtures.

Usage::

    from tests.fixtures import load_fixture, load_json_fixture

    def test_version_parsing():
        data = load_json_fixture("version.json")
        assert "client" in data

    def test_dashboard_output():
        text = load_fixture("dashboard.txt")
        assert "TALOS" in text
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

FIXTURES_DIR = Path(__file__).parent


def load_fixture(name: str) -> str:
    """Load a text fixture file by name.

    Args:
        name: Filename relative to the fixtures directory
              (e.g. ``"dashboard.txt"``).

    Returns:
        Raw text content as a string.

    Raises:
        FileNotFoundError: If the fixture file does not exist.
    """
    filepath = FIXTURES_DIR / name
    return filepath.read_text()


def load_json_fixture(name: str) -> dict[str, Any] | list[dict[str, Any]]:
    """Load a JSON fixture file by name.

    Args:
        name: Filename relative to the fixtures directory
              (e.g. ``"version.json"``).

    Returns:
        Parsed JSON data.

    Raises:
        FileNotFoundError: If the fixture file does not exist.
    """
    filepath = FIXTURES_DIR / name
    with open(filepath) as f:
        return json.load(f)
