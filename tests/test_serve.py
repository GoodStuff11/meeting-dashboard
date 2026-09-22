import json
import threading
import urllib.error
import urllib.request

import pytest

from project_tracker.export import export_json
from project_tracker.serve import build_state, make_server
from project_tracker.store import (
    add_agenda,
    connect,
    get_question,
    list_agenda,
    list_decisions,
    set_meta,
    upsert_question,
)


@pytest.fixture
def server(tmp_path):
    conn = connect(tmp_path / "d.db")
    upsert_question(conn, id="1", title="Cost per gradient", why="w", owner="Jonathon",
                    priority="high", raised="2026-09-10", state="open")
    upsert_question(conn, id="25", title="Stale ledger", why="", owner="", priority="",
                    raised="2026-09-20", state="closed")
    set_meta(conn, "meetings", [{"date": "2026-09-11", "label": "one"},
                                {"date": "2026-09-14", "label": "two"}])
    json_path = tmp_path / "dashboard.json"
    export_json(conn, json_path)
    httpd = make_server(conn, json_path, host="127.0.0.1", port=0)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{httpd.server_address[1]}"
    yield base, conn, json_path
    httpd.shutdown()
    httpd.server_close()
    conn.close()


def _get(base, path):
    with urllib.request.urlopen(base + path) as r:
        return r.status, json.loads(r.read())


def _send(base, path, payload, method="POST"):
    req = urllib.request.Request(base + path, data=json.dumps(payload).encode(),
                                 headers={"Content-Type": "application/json"},
                                 method=method)
    with urllib.request.urlopen(req) as r:
        return r.status, json.loads(r.read())


def test_state_endpoint_returns_every_section(server):
    base, _, _ = server
    status, doc = _get(base, "/api/state")
    assert status == 200
    assert {"questions", "agenda", "decisions", "flags", "meta"} <= set(doc)


def test_root_serves_the_ui(server):
    base, _, _ = server
    with urllib.request.urlopen(base + "/") as r:
        assert r.status == 200
        assert b"<html" in r.read().lower()


def test_build_state_counts_staleness_from_meetings(server):
    _, conn, _ = server
    state = build_state(conn)
    q = [x for x in state["questions"] if x["id"] == "1"][0]
    assert q["staleness"] == 2


def test_closing_a_question_persists_and_rewrites_the_json(server):
    base, conn, json_path = server
    status, _ = _send(base, "/api/questions/1/state",
                      {"state": "closed", "note": "settled"})
    assert status == 200
    row = get_question(conn, "1")
    assert row["state"] == "closed"
    assert row["state_source"] == "ui"
    assert row["closed_note"] == "settled"
    on_disk = json.loads(json_path.read_text())
    assert [q for q in on_disk["questions"] if q["id"] == "1"][0]["state"] == "closed"


def test_reopening_a_closed_question_works(server):
    base, conn, _ = server
    _send(base, "/api/questions/25/state", {"state": "open"})
    assert get_question(conn, "25")["state"] == "open"


def test_setting_difficulty_marks_it_user_owned(server):
    base, conn, _ = server
    _send(base, "/api/questions/1/difficulty", {"difficulty": "L"})
    row = get_question(conn, "1")
    assert row["difficulty"] == "L"
    assert row["difficulty_source"] == "user"


def test_adding_an_agenda_item_returns_its_id(server):
    base, conn, _ = server
    status, body = _send(base, "/api/agenda", {"title": "Ask about the venue"})
    assert status == 200
    assert any(a["id"] == body["id"] for a in list_agenda(conn))


def test_closing_an_agenda_item_creates_a_decision_and_removes_it_from_the_agenda(server):
    base, conn, _ = server
    aid = add_agenda(conn, title="Settle the cluster count", status="accepted")
    status, body = _send(base, f"/api/agenda/{aid}/close",
                         {"resolution": "Ten, as in Figs. 2-4", "resolved_by": "Eun-Ah",
                          "followups": ["Jonathon"]})
    assert status == 200
    assert body["decision_id"] == list_decisions(conn)[0]["id"]
    assert [a for a in list_agenda(conn) if a["id"] == aid][0]["status"] == "closed"
    assert list_decisions(conn)[0]["followups"] == ["Jonathon"]


def test_closing_an_agenda_item_without_a_resolution_is_a_400(server):
    base, conn, _ = server
    aid = add_agenda(conn, title="x", status="accepted")
    with pytest.raises(urllib.error.HTTPError) as exc:
        _send(base, f"/api/agenda/{aid}/close", {"resolution": "", "resolved_by": "E"})
    assert exc.value.code == 400


def test_closing_an_agenda_item_twice_is_a_409_and_mints_one_decision(server):
    base, conn, _ = server
    aid = add_agenda(conn, title="Settle the cluster count", status="accepted")
    _send(base, f"/api/agenda/{aid}/close",
          {"resolution": "Ten, as in Figs. 2-4", "resolved_by": "Eun-Ah"})
    with pytest.raises(urllib.error.HTTPError) as exc:
        _send(base, f"/api/agenda/{aid}/close",
              {"resolution": "Ten, as in Figs. 2-4", "resolved_by": "Eun-Ah"})
    assert exc.value.code == 409
    assert len(list_decisions(conn)) == 1


def test_patching_an_agenda_item_updates_it(server):
    base, conn, _ = server
    aid = add_agenda(conn, title="x")
    _send(base, f"/api/agenda/{aid}", {"status": "accepted", "title": "y"},
          method="PATCH")
    row = [a for a in list_agenda(conn) if a["id"] == aid][0]
    assert row["status"] == "accepted"
    assert row["title"] == "y"


def test_reordering_the_agenda_persists(server):
    base, conn, _ = server
    a = add_agenda(conn, title="first", status="accepted")
    b = add_agenda(conn, title="second", status="accepted")
    _send(base, "/api/agenda/reorder", {"ids": [b, a]})
    ordered = [x["id"] for x in list_agenda(conn, status="accepted")]
    assert ordered == [b, a]


def test_clearing_a_difficulty_hands_it_back_to_the_agent(server):
    """S10: the blank option used to pin difficulty_source='user' forever, so
    sync never estimated that item again — an irreversible trap."""
    base, conn, _ = server
    _send(base, "/api/questions/1/difficulty", {"difficulty": "L"})
    _send(base, "/api/questions/1/difficulty", {"difficulty": None})
    row = get_question(conn, "1")
    assert row["difficulty"] is None
    assert row["difficulty_source"] == "agent"


def test_a_json_body_that_is_not_an_object_is_a_400_not_a_traceback(server):
    """S-payload: every route calls payload.get(), outside the try block."""
    base, _, _ = server
    req = urllib.request.Request(base + "/api/agenda", data=b'["not", "an", "object"]',
                                 headers={"Content-Type": "application/json"},
                                 method="POST")
    with pytest.raises(urllib.error.HTTPError) as exc:
        urllib.request.urlopen(req)
    assert exc.value.code == 400


def test_a_bare_json_string_body_is_a_400_too(server):
    base, _, _ = server
    req = urllib.request.Request(base + "/api/agenda", data=b'"nope"',
                                 headers={"Content-Type": "application/json"},
                                 method="POST")
    with pytest.raises(urllib.error.HTTPError) as exc:
        urllib.request.urlopen(req)
    assert exc.value.code == 400


def test_unknown_question_is_a_404(server):
    base, _, _ = server
    with pytest.raises(urllib.error.HTTPError) as exc:
        _send(base, "/api/questions/999/state", {"state": "closed"})
    assert exc.value.code == 404


def test_unknown_route_is_a_404(server):
    base, _, _ = server
    with pytest.raises(urllib.error.HTTPError) as exc:
        _get(base, "/api/nonsense")
    assert exc.value.code == 404


def test_server_binds_to_loopback_only(server):
    base, _, _ = server
    assert base.startswith("http://127.0.0.1:")
