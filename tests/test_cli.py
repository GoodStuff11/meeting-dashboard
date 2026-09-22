import json

import pytest

from project_tracker.cli import main

HANDOFF = """\
## 7. Open items (state at 2026-09-21)

### Open — Jonathon

**1. Cost per gradient** — wall-clock per gradient. *Asked 2026-09-10; task `86akhc9zz`.*

### Closed

**25. Stale ledger** — CLOSED 2026-09-21.

### 7.1 Flags — disagreements (2026-09-21)

1. **Ten clusters or fourteen?** Someone has to say which.

## 8. Next
"""


@pytest.fixture
def workspace(tmp_path):
    handoff = tmp_path / "HANDOFF.md"
    handoff.write_text(HANDOFF)
    data = tmp_path / "data"
    return handoff, data


def test_sync_creates_the_json_and_pending_files(workspace, capsys):
    handoff, data = workspace
    code = main(["sync", "--handoff", str(handoff), "--data", str(data)])
    assert code == 0
    doc = json.loads((data / "dashboard.json").read_text())
    assert {q["id"] for q in doc["questions"]} == {"1", "25"}
    assert (data / "pending-changes.md").exists()


def test_sync_prints_a_summary(workspace, capsys):
    handoff, data = workspace
    main(["sync", "--handoff", str(handoff), "--data", str(data)])
    out = capsys.readouterr().out
    assert "added" in out.lower()
    assert "2" in out


def test_second_sync_leaves_the_json_byte_identical(workspace):
    handoff, data = workspace
    main(["sync", "--handoff", str(handoff), "--data", str(data)])
    first = (data / "dashboard.json").read_bytes()
    main(["sync", "--handoff", str(handoff), "--data", str(data)])
    assert (data / "dashboard.json").read_bytes() == first


def test_export_rewrites_the_json_without_syncing(workspace):
    handoff, data = workspace
    main(["sync", "--handoff", str(handoff), "--data", str(data)])
    (data / "dashboard.json").unlink()
    assert main(["export", "--data", str(data)]) == 0
    assert (data / "dashboard.json").exists()


def test_meeting_verb_records_a_meeting_in_the_json(workspace):
    """M7: nothing ever wrote meta['meetings'], so every card read '0 mtg'."""
    handoff, data = workspace
    main(["sync", "--handoff", str(handoff), "--data", str(data)])
    assert main(["meeting", "2026-09-21", "--data", str(data)]) == 0
    doc = json.loads((data / "dashboard.json").read_text())
    assert [m["date"] for m in doc["meta"]["meetings"]] == ["2026-09-21"]


def test_meetings_are_deduplicated_and_sorted(workspace):
    handoff, data = workspace
    main(["sync", "--handoff", str(handoff), "--data", str(data)])
    main(["meeting", "2026-09-21", "--data", str(data)])
    main(["meeting", "2026-09-14", "--data", str(data)])
    main(["meeting", "2026-09-21", "--data", str(data)])
    doc = json.loads((data / "dashboard.json").read_text())
    assert [m["date"] for m in doc["meta"]["meetings"]] == ["2026-09-14", "2026-09-21"]


def test_a_meeting_survives_the_next_sync(workspace):
    handoff, data = workspace
    main(["sync", "--handoff", str(handoff), "--data", str(data)])
    main(["meeting", "2026-09-21", "--data", str(data)])
    main(["sync", "--handoff", str(handoff), "--data", str(data)])
    doc = json.loads((data / "dashboard.json").read_text())
    assert [m["date"] for m in doc["meta"]["meetings"]] == ["2026-09-21"]


def test_a_malformed_meeting_date_fails_loudly(workspace, capsys):
    handoff, data = workspace
    main(["sync", "--handoff", str(handoff), "--data", str(data)])
    assert main(["meeting", "last tuesday", "--data", str(data)]) != 0
    assert "YYYY-MM-DD" in capsys.readouterr().err


def test_the_meeting_verb_needs_a_date(workspace, capsys):
    handoff, data = workspace
    main(["sync", "--handoff", str(handoff), "--data", str(data)])
    assert main(["meeting", "--data", str(data)]) != 0


def test_a_missing_handoff_file_fails_loudly(tmp_path, capsys):
    code = main(["sync", "--handoff", str(tmp_path / "nope.md"),
                 "--data", str(tmp_path / "data")])
    assert code != 0
    assert "nope.md" in capsys.readouterr().err


def test_unparseable_handoff_fails_loudly(tmp_path, capsys):
    handoff = tmp_path / "HANDOFF.md"
    handoff.write_text("# Nothing resembling section seven\n")
    code = main(["sync", "--handoff", str(handoff), "--data", str(tmp_path / "data")])
    assert code != 0
    assert "section 7" in capsys.readouterr().err.lower()


# --- config-backed commands: where / move-data / set-handoff ------------------

from pathlib import Path

from project_tracker import config


@pytest.fixture
def cfg_root(tmp_path, monkeypatch):
    """Isolate dashboard-config.json under tmp_path so these tests never touch
    the real project's config file."""
    root = tmp_path / "project"
    root.mkdir()
    monkeypatch.setattr(config, "PROJECT_ROOT", root)
    monkeypatch.setattr(config, "CONFIG_PATH", root / "dashboard-config.json")
    return root


def test_move_data_relocates_the_files_and_the_dashboard_still_works(cfg_root, tmp_path):
    handoff = tmp_path / "HANDOFF.md"
    handoff.write_text(HANDOFF)

    # First sync with no --data: this exercises the config-resolved default
    # (dashboard-data under the project root).
    assert main(["sync", "--handoff", str(handoff)]) == 0
    original = cfg_root / "dashboard-data"
    assert original.exists()
    before = (original / "dashboard.json").read_bytes()

    new_home = tmp_path / "elsewhere"
    assert main(["move-data", str(new_home)]) == 0

    moved = new_home / "dashboard-data"
    assert moved.exists()
    assert not original.exists()
    assert (moved / "dashboard.json").read_bytes() == before

    cfg = json.loads((cfg_root / "dashboard-config.json").read_text())
    assert Path(cfg["data_dir"]).resolve() == moved.resolve() or \
        cfg["data_dir"] == str(moved)

    # The dashboard keeps working: a further sync with no --data lands on the
    # moved directory.
    assert main(["sync", "--handoff", str(handoff)]) == 0
    assert (moved / "dashboard.json").exists()


def test_move_data_refuses_a_nonempty_destination(cfg_root, tmp_path):
    handoff = tmp_path / "HANDOFF.md"
    handoff.write_text(HANDOFF)
    assert main(["sync", "--handoff", str(handoff)]) == 0
    original = cfg_root / "dashboard-data"

    collision_parent = tmp_path / "occupied"
    collision_parent.mkdir()
    collision = collision_parent / "dashboard-data"
    collision.mkdir()
    (collision / "squatter.txt").write_text("already here")

    code = main(["move-data", str(collision_parent)])
    assert code != 0
    # Nothing was disturbed: the source is intact and the squatter survives.
    assert original.exists()
    assert (collision / "squatter.txt").read_text() == "already here"


def test_move_data_to_its_current_location_is_a_noop(cfg_root, tmp_path):
    handoff = tmp_path / "HANDOFF.md"
    handoff.write_text(HANDOFF)
    assert main(["sync", "--handoff", str(handoff)]) == 0
    original = cfg_root / "dashboard-data"
    before = (original / "dashboard.json").read_bytes()

    assert main(["move-data", str(cfg_root)]) == 0
    assert original.exists()
    assert (original / "dashboard.json").read_bytes() == before


def test_set_handoff_validates_existence(cfg_root, tmp_path, capsys):
    missing = tmp_path / "nope.md"
    code = main(["set-handoff", str(missing)])
    assert code != 0
    assert str(missing) in capsys.readouterr().err
    assert not (cfg_root / "dashboard-config.json").exists()


def test_set_handoff_records_a_valid_path(cfg_root, tmp_path):
    real = tmp_path / "HANDOFF.md"
    real.write_text(HANDOFF)
    assert main(["set-handoff", str(real)]) == 0
    cfg = json.loads((cfg_root / "dashboard-config.json").read_text())
    assert cfg["handoff"] == str(real.resolve())


def test_handoff_and_data_flags_still_override_the_config(cfg_root, tmp_path):
    # Config points at nonsense; --handoff/--data must win anyway.
    config.save({"data_dir": "/nonexistent/nowhere",
                 "handoff": "/nonexistent/HANDOFF.md"}, cfg_root / "dashboard-config.json")
    handoff = tmp_path / "HANDOFF.md"
    handoff.write_text(HANDOFF)
    data = tmp_path / "real-data"
    assert main(["sync", "--handoff", str(handoff), "--data", str(data)]) == 0
    assert (data / "dashboard.json").exists()


def test_a_missing_configured_handoff_gives_a_clear_error_not_a_traceback(cfg_root, capsys):
    config.save({"data_dir": "dashboard-data",
                 "handoff": "/definitely/not/a/real/HANDOFF.md"},
                cfg_root / "dashboard-config.json")
    code = main(["sync"])
    assert code != 0
    err = capsys.readouterr().err
    assert "/definitely/not/a/real/HANDOFF.md" in err
    assert "set-handoff" in err
    assert "Traceback" not in err
