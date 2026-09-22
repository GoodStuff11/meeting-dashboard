import json

from project_tracker.export import ensure_db, export_json, import_json
from project_tracker.store import (
    add_agenda,
    add_decision,
    close_agenda,
    connect,
    list_decisions,
    list_flags,
    list_questions,
    set_meta,
    set_question_difficulty,
    upsert_flag,
    upsert_question,
)


def _populate(conn):
    upsert_question(conn, id="14", title="HVA benchmark", why="Gates the venue.",
                    owner="Tamra", priority="high", raised="2026-09-14", state="open")
    upsert_question(conn, id="3", title="Reference state", why="", owner="Jonathon",
                    priority="", raised="2026-09-09", state="closed")
    set_question_difficulty(conn, "14", "L", source="user", actor="ui")
    aid = add_agenda(conn, title="Settle the cluster count", origin="sync:flag:1",
                     status="accepted")
    close_agenda(conn, aid, resolution="Ten, as in Figs. 2-4", resolved_by="Eun-Ah",
                 resolved_on="2026-09-21")
    add_decision(conn, text="PRR regular article", grounds="Body exceeds the Letter limit",
                 decided_on="2026-09-13", decided_by="Eun-Ah")
    upsert_flag(conn, key="1", text="Ten clusters or fourteen?", first_seen="2026-09-21")
    set_meta(conn, "meetings", [{"date": "2026-09-14", "label": "Frame and novelty"}])


def test_export_writes_every_table(tmp_path):
    conn = connect(tmp_path / "d.db")
    _populate(conn)
    path = tmp_path / "dashboard.json"
    doc = export_json(conn, path)
    on_disk = json.loads(path.read_text())
    assert on_disk == doc
    assert {"schema", "meta", "questions", "agenda", "decisions", "flags"} <= set(doc)
    assert [q["id"] for q in doc["questions"]] == ["14", "3"]


def test_export_is_byte_identical_when_nothing_changed(tmp_path):
    conn = connect(tmp_path / "d.db")
    _populate(conn)
    path = tmp_path / "dashboard.json"
    export_json(conn, path)
    first = path.read_bytes()
    export_json(conn, path)
    assert path.read_bytes() == first


def test_export_contains_no_wall_clock_timestamp(tmp_path):
    conn = connect(tmp_path / "d.db")
    _populate(conn)
    path = tmp_path / "dashboard.json"
    export_json(conn, path)
    assert "generated" not in json.loads(path.read_text())


def test_export_ends_with_a_single_trailing_newline(tmp_path):
    conn = connect(tmp_path / "d.db")
    _populate(conn)
    path = tmp_path / "dashboard.json"
    export_json(conn, path)
    text = path.read_text()
    assert text.endswith("\n") and not text.endswith("\n\n")


def test_import_round_trips_losslessly(tmp_path):
    source = connect(tmp_path / "a.db")
    _populate(source)
    path = tmp_path / "dashboard.json"
    export_json(source, path)

    target = connect(tmp_path / "b.db")
    import_json(target, path)
    again = tmp_path / "again.json"
    export_json(target, again)
    assert again.read_bytes() == path.read_bytes()


def test_import_preserves_ui_owned_fields(tmp_path):
    source = connect(tmp_path / "a.db")
    _populate(source)
    path = tmp_path / "dashboard.json"
    export_json(source, path)

    target = connect(tmp_path / "b.db")
    import_json(target, path)
    q = [r for r in list_questions(target) if r["id"] == "14"][0]
    assert q["difficulty"] == "L"
    assert q["difficulty_source"] == "user"
    assert list_decisions(target)[0]["grounds"] == "Ten, as in Figs. 2-4"
    assert list_flags(target)[0]["first_seen"] == "2026-09-21"


def test_import_replaces_rather_than_appends(tmp_path):
    source = connect(tmp_path / "a.db")
    _populate(source)
    path = tmp_path / "dashboard.json"
    export_json(source, path)

    target = connect(tmp_path / "b.db")
    import_json(target, path)
    import_json(target, path)
    assert len(list_questions(target)) == 2
    assert len(list_decisions(target)) == 2


def test_ensure_db_builds_the_database_from_json_when_it_is_missing(tmp_path):
    source = connect(tmp_path / "a.db")
    _populate(source)
    path = tmp_path / "dashboard.json"
    export_json(source, path)

    db = tmp_path / "fresh.db"
    assert not db.exists()
    conn = ensure_db(db, path)
    assert len(list_questions(conn)) == 2


def test_ensure_db_rebuilds_when_json_is_newer_than_the_database(tmp_path):
    db = tmp_path / "d.db"
    path = tmp_path / "dashboard.json"
    conn = connect(db)
    _populate(conn)
    export_json(conn, path)
    conn.close()

    doc = json.loads(path.read_text())
    doc["questions"].append({
        "id": "99", "title": "Added by a collaborator", "why": "", "owner": "",
        "priority": "", "raised": "", "clickup_id": None, "clickup_status": None,
        "due": None, "state": "open", "state_source": "tracker", "difficulty": None,
        "difficulty_source": None, "closed_on": None, "closed_note": None,
        "last_seen_sync": None, "updated_at": None,
    })
    path.write_text(json.dumps(doc, indent=2, sort_keys=True, ensure_ascii=False) + "\n")
    import os, time
    os.utime(path, (time.time() + 10, time.time() + 10))

    conn = ensure_db(db, path)
    assert "99" in [q["id"] for q in list_questions(conn)]


def test_ensure_db_leaves_a_current_database_alone(tmp_path):
    db = tmp_path / "d.db"
    path = tmp_path / "dashboard.json"
    conn = connect(db)
    _populate(conn)
    export_json(conn, path)
    upsert_question(conn, id="55", title="local only", why="", owner="", priority="",
                    raised="", state="open")
    conn.close()

    conn = ensure_db(db, path)
    assert "55" in [q["id"] for q in list_questions(conn)]


# --- content-hash staleness (fix round 1) -----------------------------------
#
# ensure_db used to decide staleness from mtime comparison, which is wrong in
# both directions: export_json always writes the .json *after* the mutation
# that preceded it, so the .json's mtime trails the .db's mtime in the
# ordinary case (an mtime check would re-import on every startup), while a
# coarse-mtime filesystem can make a real edit invisible. These tests pin the
# content-hash replacement down directly, independent of file timestamps.


def test_ensure_db_imports_from_json_on_a_fresh_clone(tmp_path):
    source = connect(tmp_path / "a.db")
    _populate(source)
    path = tmp_path / "dashboard.json"
    export_json(source, path)

    db = tmp_path / "fresh.db"
    assert not db.exists()
    conn = ensure_db(db, path)
    assert len(list_questions(conn)) == 2


def test_ensure_db_does_not_reimport_when_json_content_is_unchanged(tmp_path):
    db = tmp_path / "d.db"
    path = tmp_path / "dashboard.json"
    conn = connect(db)
    _populate(conn)
    export_json(conn, path)
    # A row that exists only in the db, never written to the json. If ensure_db
    # re-imports (replacing table contents from the unchanged json), this row
    # is destroyed. Its survival is the proof that no import happened.
    upsert_question(conn, id="77", title="local only, not in json", why="", owner="",
                    priority="", raised="", state="open")
    conn.close()

    conn = ensure_db(db, path)
    assert "77" in [q["id"] for q in list_questions(conn)]


def test_ensure_db_reimports_when_json_content_changes_regardless_of_mtime(tmp_path):
    db = tmp_path / "d.db"
    path = tmp_path / "dashboard.json"
    conn = connect(db)
    _populate(conn)
    export_json(conn, path)
    conn.close()

    doc = json.loads(path.read_text())
    doc["questions"].append({
        "id": "99", "title": "Added by a collaborator", "why": "", "owner": "",
        "priority": "", "raised": "", "clickup_id": None, "clickup_status": None,
        "due": None, "state": "open", "state_source": "tracker", "difficulty": None,
        "difficulty_source": None, "closed_on": None, "closed_note": None,
    })
    path.write_text(json.dumps(doc, indent=2, sort_keys=True, ensure_ascii=False) + "\n")
    # Deliberately make the json's mtime *older* than the db's, to prove
    # staleness is decided by content hash, not by mtime comparison.
    import os, time
    old = time.time() - 3600
    os.utime(path, (old, old))

    conn = ensure_db(db, path)
    assert "99" in [q["id"] for q in list_questions(conn)]


def test_export_does_not_carry_its_own_hash_key(tmp_path):
    conn = connect(tmp_path / "d.db")
    _populate(conn)
    path = tmp_path / "dashboard.json"
    doc = export_json(conn, path)
    assert "export_sha256" not in doc["meta"]
    assert "export_sha256" not in json.dumps(doc)
