"""Test fixture loader for NextDNS API response JSON files.

Usage::

    from tests.fixtures import load_fixture

    def test_profile_parsing():
        data = load_fixture("profiles.json")
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
        name: Filename relative to the fixtures directory (e.g. ``"profiles.json"``).

    Returns:
        Parsed JSON as a dictionary.

    Raises:
        FileNotFoundError: If the fixture file does not exist.
    """
    filepath = FIXTURES_DIR / name
    with open(filepath) as f:
        return json.load(f)
