"""Shared pytest fixtures for nextdns tests."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture()
def fixture_data() -> dict[str, Any]:
    """Load all fixture files into a dict keyed by filename (without extension)."""
    data: dict[str, Any] = {}
    for f in sorted(FIXTURES_DIR.glob("*.json")):
        with open(f) as fh:
            data[f.stem] = json.load(fh)
    return data


@pytest.fixture()
def load_fixture():
    """Return a callable that loads a specific fixture by name."""

    def _load(name: str) -> Any:
        path = FIXTURES_DIR / f"{name}.json"
        with open(path) as fh:
            return json.load(fh)

    return _load
