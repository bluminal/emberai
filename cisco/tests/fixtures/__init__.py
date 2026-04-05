"""Test fixture loader for Cisco SG-300 CLI output text files.

Usage::

    from tests.fixtures import load_fixture

    def test_vlan_parsing():
        data = load_fixture("show_vlan.txt")
        assert "default" in data
"""

from __future__ import annotations

from pathlib import Path

FIXTURES_DIR = Path(__file__).parent


def load_fixture(name: str) -> str:
    """Load a text fixture file by name.

    Args:
        name: Filename relative to the fixtures directory
              (e.g. ``"show_vlan.txt"``).

    Returns:
        Raw text content as a string.

    Raises:
        FileNotFoundError: If the fixture file does not exist.
    """
    filepath = FIXTURES_DIR / name
    return filepath.read_text()
