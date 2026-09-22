import sqlite3

import pytest

from project_tracker import store
from project_tracker.store import (
    add_agenda,
    add_decision,
    close_agenda,
    connect,
    get_agenda,
    get_meta,
    get_question,
    list_agenda,
    list_changes,
    list_decisions,
    list_flags,
    list_questions,
    reorder_agenda,
    set_meta,
    set_question_difficulty,
    set_question_state,
    update_agenda,
    update_decision,
    upsert_flag,
    upsert_question,
)


@pytest.fixture
def conn(tmp_path):
    c = connect(tmp_path / "dashboard.db")
    yield c
    c.close()


def _q(conn, qid="14", **kw):
    base = dict(
        id=qid, title="HVA benchmark", why="Gates the venue.", owner="Tamra",
        priority="high", raised="2026-09-14", state="open",
    )
    base.update(kw)
    upsert_question(conn, **base)
    return qid


def test_upsert_question_then_get_round_trips(conn):
    _q(conn)
    row = get_question(conn, "14")
    assert row["id"] == "14"
    assert row["title"] == "HVA benchmark"
    assert row["state"] == "open"
    assert row["state_source"] == "tracker"


def test_upsert_question_overwrites_tracker_fields_but_keeps_ui_fields(conn):
    _q(conn)
    set_question_difficulty(conn, "14", "L", source="user", actor="ui")
    _q(conn, title="HVA benchmark, restated", owner="Jonathon")
    row = get_question(conn, "14")
    assert row["title"] == "HVA benchmark, restated"
    assert row["owner"] == "Jonathon"
    assert row["difficulty"] == "L"
    assert row["difficulty_source"] == "user"


def test_question_id_is_a_string_and_sub_items_are_preserved(conn):
    _q(conn, qid="14b")
    assert get_question(conn, "14b")["id"] == "14b"


def test_list_questions_filters_by_state(conn):
    _q(conn, qid="1")
    _q(conn, qid="2", state="closed")
    assert [r["id"] for r in list_questions(conn, state="open")] == ["1"]
    assert [r["id"] for r in list_questions(conn, state="closed")] == ["2"]


def test_set_question_state_records_source_note_and_date(conn):
    _q(conn)
    set_question_state(conn, "14", "closed", source="ui", note="settled in the meeting",
                       on="2026-09-21", actor="ui")
    row = get_question(conn, "14")
    assert row["state"] == "closed"
    assert row["state_source"] == "ui"
    assert row["closed_note"] == "settled in the meeting"
    assert row["closed_on"] == "2026-09-21"


def test_set_question_state_writes_a_changelog_entry(conn):
    _q(conn)
    set_question_state(conn, "14", "closed", source="ui", actor="ui")
    entries = [e for e in list_changes(conn)
               if e["entity"] == "question" and e["field"] == "state"]
    assert len(entries) == 1
    assert entries[0]["field"] == "state"
    assert entries[0]["old"] == "open"
    assert entries[0]["new"] == "closed"
    assert entries[0]["actor"] == "ui"


def test_upsert_question_writes_a_created_entry_once_on_first_insert(conn):
    _q(conn)
    created = [e for e in list_changes(conn)
               if e["entity"] == "question" and e["field"] == "created"]
    assert len(created) == 1
    assert created[0]["new"] == "HVA benchmark"
    # a no-op re-upsert of identical tracker fields must not write a second
    # "created" entry, nor any other changelog entry.
    before = len(list_changes(conn))
    _q(conn)
    after = len(list_changes(conn))
    assert after == before
    created_again = [e for e in list_changes(conn)
                     if e["entity"] == "question" and e["field"] == "created"]
    assert len(created_again) == 1


def test_set_question_state_on_unknown_id_raises(conn):
    with pytest.raises(KeyError):
        set_question_state(conn, "999", "closed", source="ui", actor="ui")


def test_add_agenda_returns_id_and_defaults_to_proposed(conn):
    aid = add_agenda(conn, title="Settle the cluster count", origin="sync:flag:1")
    row = list_agenda(conn)[0]
    assert row["id"] == aid
    assert row["status"] == "proposed"
    assert row["origin"] == "sync:flag:1"


def test_reorder_agenda_sets_sort_order_in_the_given_sequence(conn):
    a = add_agenda(conn, title="first")
    b = add_agenda(conn, title="second")
    reorder_agenda(conn, [b, a])
    assert [r["id"] for r in list_agenda(conn)] == [b, a]


def test_close_agenda_creates_one_decision_carrying_resolution_as_grounds(conn):
    aid = add_agenda(conn, title="Which loss for the 4x4 runs?", status="accepted")
    did = close_agenda(conn, aid, resolution="overlap, matching panels A and B",
                       resolved_by="Eun-Ah", followups=["Jonathon"], resolved_on="2026-09-21")
    decisions = list_decisions(conn)
    assert len(decisions) == 1
    assert decisions[0]["id"] == did
    assert decisions[0]["grounds"] == "overlap, matching panels A and B"
    assert decisions[0]["from_agenda_id"] == aid
    assert decisions[0]["followups"] == ["Jonathon"]
    assert list_agenda(conn, status="closed")[0]["id"] == aid


def test_close_agenda_without_a_resolution_raises(conn):
    aid = add_agenda(conn, title="something", status="accepted")
    with pytest.raises(ValueError):
        close_agenda(conn, aid, resolution="   ", resolved_by="Eun-Ah")


def test_closing_an_already_closed_agenda_item_raises_and_mints_nothing(conn):
    """B3: a double-click on Close must not mint two identical decisions, each
    of which a person then folds into section 7."""
    aid = add_agenda(conn, title="Which loss for the 4x4 runs?", status="accepted")
    close_agenda(conn, aid, resolution="overlap", resolved_by="Eun-Ah",
                 resolved_on="2026-09-21")
    with pytest.raises(store.AlreadyClosed):
        close_agenda(conn, aid, resolution="overlap", resolved_by="Eun-Ah",
                     resolved_on="2026-09-21")
    assert len(list_decisions(conn)) == 1


def test_already_closed_is_a_value_error_too(conn):
    aid = add_agenda(conn, title="x", status="accepted")
    close_agenda(conn, aid, resolution="r", resolved_by="E", resolved_on="2026-09-21")
    with pytest.raises(ValueError):
        close_agenda(conn, aid, resolution="r", resolved_by="E", resolved_on="2026-09-21")


def test_add_decision_without_grounds_raises(conn):
    with pytest.raises(ValueError):
        add_decision(conn, text="We do X", grounds="", decided_on="2026-09-21",
                     decided_by="Eun-Ah")


def test_list_decisions_sorts_newest_first(conn):
    add_decision(conn, text="older", grounds="g", decided_on="2026-09-11", decided_by="E")
    add_decision(conn, text="newer", grounds="g", decided_on="2026-09-14", decided_by="E")
    assert [d["text"] for d in list_decisions(conn)] == ["newer", "older"]


def test_upsert_flag_is_idempotent_on_key_and_keeps_first_seen(conn):
    upsert_flag(conn, key="1", text="Ten clusters or fourteen?", first_seen="2026-09-21")
    upsert_flag(conn, key="1", text="Ten clusters or fourteen?", first_seen="2026-09-28")
    flags = list_flags(conn)
    assert len(flags) == 1
    assert flags[0]["first_seen"] == "2026-09-21"


def test_meta_round_trips_structured_values(conn):
    set_meta(conn, "meetings", [{"date": "2026-09-14", "label": "Frame and novelty"}])
    assert get_meta(conn, "meetings")[0]["date"] == "2026-09-14"
    assert get_meta(conn, "absent", default="fallback") == "fallback"


def test_update_agenda_rejects_unknown_columns(conn):
    aid = add_agenda(conn, title="x")
    with pytest.raises(ValueError):
        update_agenda(conn, aid, nonsense="boom")


def test_connect_is_idempotent_on_an_existing_database(tmp_path):
    path = tmp_path / "d.db"
    c1 = connect(path)
    upsert_question(c1, id="1", title="t", why="w", owner="o", priority="", raised="",
                    state="open")
    c1.close()
    c2 = connect(path)
    assert get_question(c2, "1")["title"] == "t"
    c2.close()


def test_update_decision_happy_path_updates_fields_and_ignores_none(conn):
    did = add_decision(conn, text="We do X", grounds="because reasons",
                       decided_on="2026-09-21", decided_by="Eun-Ah")
    update_decision(conn, did, text="We do Y", grounds="better reasons",
                    decided_by="Jonathon", actor="ui")
    row = [d for d in list_decisions(conn) if d["id"] == did][0]
    assert row["text"] == "We do Y"
    assert row["grounds"] == "better reasons"
    assert row["decided_by"] == "Jonathon"


def test_update_decision_unknown_id_raises_keyerror(conn):
    with pytest.raises(KeyError):
        update_decision(conn, 999, text="nope")


def test_update_decision_blank_grounds_raises_valueerror(conn):
    did = add_decision(conn, text="We do X", grounds="because reasons",
                       decided_on="2026-09-21", decided_by="Eun-Ah")
    with pytest.raises(ValueError):
        update_decision(conn, did, grounds="   ")


def test_update_decision_writes_a_changelog_entry_per_changed_field(conn):
    did = add_decision(conn, text="We do X", grounds="because reasons",
                       decided_on="2026-09-21", decided_by="Eun-Ah")
    update_decision(conn, did, text="We do Y", grounds="better reasons", actor="ui")
    entries = [e for e in list_changes(conn)
               if e["entity"] == "decision" and e["entity_id"] == str(did)
               and e["field"] in ("text", "grounds")]
    fields = {e["field"] for e in entries}
    assert fields == {"text", "grounds"}
    for e in entries:
        assert e["actor"] == "ui"


def test_update_decision_with_no_changed_fields_writes_no_changelog_entry(conn):
    did = add_decision(conn, text="We do X", grounds="because reasons",
                       decided_on="2026-09-21", decided_by="Eun-Ah")
    before = len(list_changes(conn))
    update_decision(conn, did)
    after = len(list_changes(conn))
    assert after == before


def test_close_agenda_is_atomic_if_the_decision_insert_fails(conn, monkeypatch):
    aid = add_agenda(conn, title="Which loss for the 4x4 runs?", status="accepted")

    def _boom(*a, **kw):
        raise RuntimeError("simulated failure")

    monkeypatch.setattr(store, "_add_decision", _boom)
    with pytest.raises(RuntimeError):
        close_agenda(conn, aid, resolution="overlap, matching panels A and B",
                     resolved_by="Eun-Ah")
    row = get_agenda(conn, aid)
    assert row["status"] == "accepted"
    assert row["resolution"] is None
    assert list_decisions(conn) == []
