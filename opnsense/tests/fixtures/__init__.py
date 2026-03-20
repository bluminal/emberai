"""Test fixture loader for OPNsense API response JSON files.

Usage::

    from tests.fixtures import load_fixture

    def test_firewall_rule_parsing():
        data = load_fixture("firewall_rules.json")
        assert "rows" in data
        rules = data["rows"]
        ...
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

FIXTURES_DIR = Path(__file__).parent


def load_fixture(name: str) -> dict[str, Any]:
    """Load a JSON fixture file by name.

    Args:
        name: Filename relative to the fixtures directory (e.g. ``"firewall_rules.json"``).

    Returns:
        Parsed JSON as a dictionary.

    Raises:
        FileNotFoundError: If the fixture file does not exist.
    """
    filepath = FIXTURES_DIR / name
    with open(filepath) as f:
        return json.load(f)
