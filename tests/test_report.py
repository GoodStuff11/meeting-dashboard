from project_tracker.report import render_pending, write_pending
from project_tracker.store import (
    add_agenda,
    close_agenda,
    connect,
    set_question_state,
    upsert_question,
)
from project_tracker.sync import SyncResult


def _conn(tmp_path):
    conn = connect(tmp_path / "d.db")
    upsert_question(conn, id="1", title="Cost per gradient", why="", owner="Jonathon",
                    priority="high", raised="2026-09-10", state="open")
    return conn


def test_reverted_closures_are_listed_as_owed_section_seven_edits(tmp_path):
    conn = _conn(tmp_path)
    result = SyncResult(reverted=[{"id": "1", "title": "Cost per gradient",
                                   "note": "settled in the meeting",
                                   "closed_on": "2026-09-21"}])
    text = render_pending(conn, result, today="2026-09-21")
    assert "closed in the UI, still open in §7" in text
    assert "item 1" in text.lower()
    assert "settled in the meeting" in text


def test_reverted_item_with_no_note_or_closed_on_uses_fallback_text(tmp_path):
    conn = _conn(tmp_path)
    result = SyncResult(reverted=[{"id": "1", "title": "Cost per gradient"}])
    text = render_pending(conn, result, today="2026-09-21")
    assert "(no note recorded)" in text
    assert "in the UI" in text
    assert "None" not in text


def test_decisions_taken_in_the_ui_are_listed(tmp_path):
    conn = _conn(tmp_path)
    aid = add_agenda(conn, title="Settle the cluster count", status="accepted")
    close_agenda(conn, aid, resolution="Ten, as in Figs. 2-4", resolved_by="Eun-Ah",
                 resolved_on="2026-09-21")
    text = render_pending(conn, SyncResult(), today="2026-09-21")
    assert "Ten, as in Figs. 2-4" in text
    assert "Eun-Ah" in text


def test_stale_items_are_listed(tmp_path):
    conn = _conn(tmp_path)
    text = render_pending(conn, SyncResult(stale=["21"]), today="2026-09-21")
    assert "21" in text
    assert "no longer in" in text.lower()


def test_a_clean_sync_says_so_rather_than_emitting_an_empty_file(tmp_path):
    conn = _conn(tmp_path)
    text = render_pending(conn, SyncResult(), today="2026-09-21")
    assert "Nothing owed" in text


def test_write_pending_creates_the_file_and_returns_its_text(tmp_path):
    conn = _conn(tmp_path)
    path = tmp_path / "pending-changes.md"
    text = write_pending(conn, SyncResult(), path, today="2026-09-21")
    assert path.read_text() == text
    assert path.read_text().startswith("# Pending changes")


def test_rendering_is_stable_across_repeated_calls(tmp_path):
    conn = _conn(tmp_path)
    result = SyncResult(stale=["21"])
    assert render_pending(conn, result, today="2026-09-21") == \
        render_pending(conn, result, today="2026-09-21")


def test_a_reverted_closure_is_re_derived_from_the_store_on_a_later_render(tmp_path):
    """B1: the sync that noticed the revert is not the only one that may report it.

    After that sync the row is open/tracker again with its closing breadcrumb
    intact, so every later render must find it — otherwise a second
    `./dashboard update` erases the only record of an in-meeting closure.
    """
    conn = _conn(tmp_path)
    set_question_state(conn, "1", "closed", source="ui", note="settled in the meeting",
                       on="2026-09-21", actor="ui")
    # What sync does next: section 7 still says open, so the tracker wins.
    upsert_question(conn, id="1", title="Cost per gradient", why="", owner="Jonathon",
                    priority="high", raised="2026-09-10", state="open", actor="sync")

    text = render_pending(conn, SyncResult(), today="2026-09-22")
    assert "closed in the UI, still open in §7" in text
    assert "settled in the meeting" in text


def test_a_re_derived_revert_is_not_listed_twice(tmp_path):
    conn = _conn(tmp_path)
    set_question_state(conn, "1", "closed", source="ui", note="settled in the meeting",
                       on="2026-09-21", actor="ui")
    upsert_question(conn, id="1", title="Cost per gradient", why="", owner="Jonathon",
                    priority="high", raised="2026-09-10", state="open", actor="sync")
    result = SyncResult(reverted=[{"id": "1", "title": "Cost per gradient",
                                   "note": "settled in the meeting",
                                   "closed_on": "2026-09-21"}])
    text = render_pending(conn, result, today="2026-09-21")
    assert text.count("settled in the meeting") == 1


def test_a_ui_reopen_the_tracker_overrode_is_reported_as_owed(tmp_path):
    """M4: the mirror of the revert — section 7 says closed, the group reopened it."""
    conn = _conn(tmp_path)
    upsert_question(conn, id="25", title="Stale ledger", why="", owner="",
                    priority="", raised="2026-09-20", state="closed", actor="sync")
    set_question_state(conn, "25", "open", source="ui", on="2026-09-21", actor="ui")
    upsert_question(conn, id="25", title="Stale ledger", why="", owner="",
                    priority="", raised="2026-09-20", state="closed", actor="sync")

    text = render_pending(conn, SyncResult(), today="2026-09-22")
    assert "reopened in the UI" in text
    assert "item 25" in text.lower()


def test_a_fresh_reopen_from_the_sync_result_is_listed_once(tmp_path):
    conn = _conn(tmp_path)
    upsert_question(conn, id="25", title="Stale ledger", why="", owner="",
                    priority="", raised="2026-09-20", state="closed", actor="sync")
    set_question_state(conn, "25", "open", source="ui", on="2026-09-21", actor="ui")
    upsert_question(conn, id="25", title="Stale ledger", why="", owner="",
                    priority="", raised="2026-09-20", state="closed", actor="sync")
    result = SyncResult(reopened=[{"id": "25", "title": "Stale ledger",
                                   "reopened_on": "2026-09-21"}])
    text = render_pending(conn, result, today="2026-09-21")
    assert text.count("item 25") == 1
