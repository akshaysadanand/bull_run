"""Add project root to sys.path so `scraper` is importable from tests/."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


@pytest.fixture
def presets_file(tmp_path: Path):
    """Provide a temporary presets.json path and helper to read/write it."""
    p = tmp_path / "presets.json"
    return p
