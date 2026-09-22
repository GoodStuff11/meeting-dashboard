import json
from pathlib import Path

import pytest

from project_tracker import config


@pytest.fixture
def sandbox(tmp_path, monkeypatch):
    """Point config at an isolated project root so tests never touch the
    real dashboard-config.json."""
    root = tmp_path / "project"
    root.mkdir()
    monkeypatch.setattr(config, "PROJECT_ROOT", root)
    monkeypatch.setattr(config, "CONFIG_PATH", root / "dashboard-config.json")
    return root


def test_relative_data_dir_resolves_against_the_project_root(sandbox):
    cfg = {"data_dir": "dashboard-data", "handoff": "/nowhere.md"}
    assert config.resolve_data_dir(cfg) == sandbox / "dashboard-data"


def test_absolute_data_dir_is_used_as_is(sandbox):
    absolute = "/somewhere/else/dashboard-data"
    cfg = {"data_dir": absolute, "handoff": "/nowhere.md"}
    assert str(config.resolve_data_dir(cfg)) == absolute


def test_load_writes_the_defaults_on_first_use(sandbox):
    assert not config.CONFIG_PATH.exists()
    cfg = config.load()
    assert cfg == config.defaults()
    assert config.CONFIG_PATH.exists()
    on_disk = json.loads(config.CONFIG_PATH.read_text())
    assert on_disk == config.defaults()


def test_load_does_not_overwrite_an_existing_config(sandbox):
    config.CONFIG_PATH.write_text(json.dumps({"data_dir": "elsewhere",
                                              "handoff": "/custom.md"}))
    cfg = config.load()
    assert cfg == {"data_dir": "elsewhere", "handoff": "/custom.md"}


def test_resolve_handoff_reads_the_config_value(sandbox):
    cfg = {"data_dir": "dashboard-data", "handoff": "/custom/HANDOFF.md"}
    assert config.resolve_handoff(cfg) == Path("/custom/HANDOFF.md")
