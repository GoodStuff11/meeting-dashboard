"""One pass through the whole loop, against the real HANDOFF.md."""

import json
import threading
import urllib.request
from pathlib import Path

import pytest

from project_tracker.export import ensure_db, export_json
from project_tracker.report import write_pending
from project_tracker.serve import make_server
from project_tracker.store import connect, get_question, list_decisions
from project_tracker.sync import sync
from project_tracker import config

def _configured_handoff():
    """The HANDOFF.md this checkout is configured to use, or None.

    Read straight off disk rather than through `config.load()`, which would
    write a config file as a side effect of merely collecting tests. There is
    no default handoff path any more — a personal path baked into a shared
    repository was the bug — so a checkout that has never run `set-handoff`
    skips these.
    """
    if not config.CONFIG_PATH.exists():
        return None
    path = config.resolve_handoff(json.loads(config.CONFIG_PATH.read_text()))
    return path if path is not None and path.exists() else None


REAL = _configured_handoff()
pytestmark = pytest.mark.skipif(REAL is None, reason="no HANDOFF.md configured")


def _post(base, path, payload):
    req = urllib.request.Request(base + path, data=json.dumps(payload).encode(),
                                 headers={"Content-Type": "application/json"},
                                 method="POST")
    with urllib.request.urlopen(req) as r:
        return json.loads(r.read())


def test_sync_then_edit_then_resync_keeps_ui_work_and_reports_it(tmp_path):
    db, js = tmp_path / "d.db", tmp_path / "dashboard.json"
    conn = connect(db)

    first = sync(conn, handoff_path=REAL, json_path=js)
    assert len(first.added) > 10, "the real section 7 should yield a substantial board"

    httpd = make_server(conn, js, host="127.0.0.1", port=0)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{httpd.server_address[1]}"
    try:
        open_id = [q["id"] for q in json.loads(js.read_text())["questions"]
                   if q["state"] == "open"][0]
        _post(base, f"/api/questions/{open_id}/state",
              {"state": "closed", "note": "closed live in the meeting"})
        assert get_question(conn, open_id)["state"] == "closed"

        aid = _post(base, "/api/agenda",
                    {"title": "Confirm the venue fork", "status": "accepted"})["id"]
        _post(base, f"/api/agenda/{aid}/close",
              {"resolution": "PRR now, PRX Quantum on a win", "resolved_by": "Eun-Ah"})
        assert len(list_decisions(conn)) == 1
    finally:
        httpd.shutdown()
        httpd.server_close()

    second = sync(conn, handoff_path=REAL, json_path=js)
    assert get_question(conn, open_id)["state"] == "open", "the tracker dictates state"
    assert any(r["id"] == open_id for r in second.reverted)
    assert len(list_decisions(conn)) == 1, "sync must never remove a decision"

    pending = write_pending(conn, second, tmp_path / "pending-changes.md")
    assert "closed live in the meeting" in pending
    assert "PRR now, PRX Quantum on a win" in pending


def test_a_fresh_clone_can_serve_from_the_committed_json_alone(tmp_path):
    db, js = tmp_path / "d.db", tmp_path / "dashboard.json"
    conn = connect(db)
    sync(conn, handoff_path=REAL, json_path=js)
    export_json(conn, js)
    conn.close()

    clone = tmp_path / "clone"
    clone.mkdir()
    (clone / "dashboard.json").write_text(js.read_text())

    fresh = ensure_db(clone / "dashboard.db", clone / "dashboard.json")
    httpd = make_server(fresh, clone / "dashboard.json", host="127.0.0.1", port=0)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{httpd.server_address[1]}"
    try:
        with urllib.request.urlopen(base + "/api/state") as r:
            state = json.loads(r.read())
        assert len(state["questions"]) > 10
    finally:
        httpd.shutdown()
        httpd.server_close()
