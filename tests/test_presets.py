import json
from pathlib import Path

import pytest


def test_load_presets_returns_list(presets_file: Path, monkeypatch: pytest.MonkeyPatch):
    """Loading a valid presets.json returns a list of dicts."""
    data = [{"name": "Test", "ticker": "TST", "custom_urls": []}]
    presets_file.write_text(json.dumps(data))

    # Import after monkeypatch so app.py picks up the test file
    monkeypatch.setattr("app.PRESETS_FILE", str(presets_file))
    from app import load_presets

    result = load_presets()
    assert isinstance(result, list)
    assert len(result) == 1
    assert result[0]["ticker"] == "TST"


def test_load_presets_missing_file_returns_empty(presets_file: Path, monkeypatch: pytest.MonkeyPatch):
    """Loading a non-existent presets.json returns an empty list."""
    from app import load_presets
    monkeypatch.setattr("app.PRESETS_FILE", str(presets_file))

    result = load_presets()
    assert result == []


def test_load_presets_invalid_json_returns_empty(presets_file: Path, monkeypatch: pytest.MonkeyPatch):
    """Loading a malformed presets.json returns an empty list."""
    presets_file.write_text("{invalid json")
    from app import load_presets
    monkeypatch.setattr("app.PRESETS_FILE", str(presets_file))

    result = load_presets()
    assert result == []


def test_save_preset_appends_to_file(presets_file: Path, monkeypatch: pytest.MonkeyPatch):
    """Saving a preset appends it to the existing presets.json."""
    data = [{"name": "Existing", "ticker": "EXS", "custom_urls": []}]
    presets_file.write_text(json.dumps(data))
    from app import save_preset
    monkeypatch.setattr("app.PRESETS_FILE", str(presets_file))

    result = save_preset("New Preset", "NWP", ["https://example.com"])
    assert result is True

    updated = json.loads(presets_file.read_text())
    assert len(updated) == 2
    assert updated[1]["name"] == "New Preset"
    assert updated[1]["ticker"] == "NWP"


def test_save_preset_rejects_duplicate_name(presets_file: Path, monkeypatch: pytest.MonkeyPatch):
    """Saving a preset with a duplicate name returns False."""
    data = [{"name": "Existing", "ticker": "EXS", "custom_urls": []}]
    presets_file.write_text(json.dumps(data))
    from app import save_preset
    monkeypatch.setattr("app.PRESETS_FILE", str(presets_file))

    result = save_preset("Existing", "XXX", [])
    assert result is False


def test_save_preset_creates_file_if_missing(presets_file: Path, monkeypatch: pytest.MonkeyPatch):
    """Saving a preset creates presets.json if it doesn't exist."""
    from app import save_preset
    monkeypatch.setattr("app.PRESETS_FILE", str(presets_file))

    result = save_preset("First", "FST", [])
    assert result is True
    assert presets_file.exists()

    data = json.loads(presets_file.read_text())
    assert len(data) == 1
