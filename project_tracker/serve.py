"""HTTP surface for the dashboard.

Routing and serialisation only — every rule lives in store.py. Each mutation
rewrites dashboard.json before replying, so what git carries is never behind
what the browser has just done, and there is no save button to forget.

`ThreadingHTTPServer` runs every request on its own thread, but the whole
point of `store` is not losing meeting work, so concurrent access to the one
`sqlite3.Connection` (and to the dashboard.json rewrite that follows a write)
is serialised through a single lock held for the whole request, not just
disabled at the driver level. See `_handle_api` and its call sites below.
"""

import json
import mimetypes
import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from . import store
from .export import export_json

STATIC = Path(__file__).parent / "static"

_Q_STATE = re.compile(r"^/api/questions/(?P<id>[^/]+)/state$")
_Q_DIFF = re.compile(r"^/api/questions/(?P<id>[^/]+)/difficulty$")
_A_CLOSE = re.compile(r"^/api/agenda/(?P<id>\d+)/close$")
_A_ONE = re.compile(r"^/api/agenda/(?P<id>\d+)$")
_D_ONE = re.compile(r"^/api/decisions/(?P<id>\d+)$")


class ApiError(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code
        self.message = message


def build_state(conn):
    """The whole board, plus the derived staleness counter the UI colours by."""
    meetings = store.get_meta(conn, "meetings", default=[]) or []
    dates = sorted(m["date"] for m in meetings if m.get("date"))

    questions = []
    for row in store.list_questions(conn):
        row = dict(row)
        raised = row.get("raised") or ""
        row["staleness"] = sum(1 for d in dates if raised and d >= raised)
        questions.append(row)

    return {
        "meta": {
            "meetings": meetings,
            "last_sync": store.get_meta(conn, "last_sync"),
            "last_clickup_pull": store.get_meta(conn, "last_clickup_pull"),
        },
        "questions": questions,
        "agenda": store.list_agenda(conn),
        "decisions": store.list_decisions(conn),
        "flags": store.list_flags(conn),
    }


def _handle_api(conn, method, path, payload):
    if method == "GET" and path == "/api/state":
        return build_state(conn)

    if method == "POST" and (m := _Q_STATE.match(path)):
        state = payload.get("state")
        if state not in ("open", "closed"):
            raise ApiError(400, "state must be 'open' or 'closed'")
        try:
            store.set_question_state(conn, m.group("id"), state, source="ui",
                                     note=payload.get("note"), on=payload.get("on"),
                                     actor="ui")
        except KeyError:
            raise ApiError(404, f"no question {m.group('id')}")
        return {"ok": True}

    if method == "POST" and (m := _Q_DIFF.match(path)):
        difficulty = payload.get("difficulty")
        # Clearing the difficulty means "let the agent estimate it again", not
        # "the user has chosen blank": marking it user-owned would pin it empty
        # forever, since sync skips user-owned rows.
        source = "user" if difficulty else "agent"
        try:
            store.set_question_difficulty(conn, m.group("id"), difficulty,
                                          source=source, actor="ui")
        except KeyError:
            raise ApiError(404, f"no question {m.group('id')}")
        except ValueError as exc:
            raise ApiError(400, str(exc))
        return {"ok": True}

    if method == "POST" and path == "/api/agenda":
        title = (payload.get("title") or "").strip()
        if not title:
            raise ApiError(400, "an agenda item needs a title")
        aid = store.add_agenda(conn, title=title, detail=payload.get("detail", ""),
                               origin="manual", proposed_by=payload.get("proposed_by", ""),
                               status=payload.get("status", "accepted"), actor="ui")
        return {"id": aid}

    if method == "POST" and path == "/api/agenda/reorder":
        store.reorder_agenda(conn, payload.get("ids") or [], actor="ui")
        return {"ok": True}

    if method == "POST" and (m := _A_CLOSE.match(path)):
        try:
            did = store.close_agenda(
                conn, int(m.group("id")), resolution=payload.get("resolution", ""),
                resolved_by=payload.get("resolved_by", ""),
                followups=payload.get("followups"), resolved_on=payload.get("resolved_on"),
                actor="ui")
        except KeyError:
            raise ApiError(404, f"no agenda item {m.group('id')}")
        except store.AlreadyClosed as exc:
            # A duplicate submission, not a malformed one: the usual cause is a
            # double-click firing the second handler before the reload.
            raise ApiError(409, str(exc))
        except ValueError as exc:
            raise ApiError(400, str(exc))
        return {"decision_id": did}

    if method == "PATCH" and (m := _A_ONE.match(path)):
        try:
            store.update_agenda(conn, int(m.group("id")), actor="ui", **payload)
        except KeyError:
            raise ApiError(404, f"no agenda item {m.group('id')}")
        except ValueError as exc:
            raise ApiError(400, str(exc))
        return {"ok": True}

    if method == "PATCH" and (m := _D_ONE.match(path)):
        try:
            store.update_decision(conn, int(m.group("id")), text=payload.get("text"),
                                  grounds=payload.get("grounds"),
                                  decided_by=payload.get("decided_by"), actor="ui")
        except KeyError:
            raise ApiError(404, f"no decision {m.group('id')}")
        except ValueError as exc:
            raise ApiError(400, str(exc))
        return {"ok": True}

    raise ApiError(404, f"no route for {method} {path}")


def _make_handler(conn, json_path, static_dir, lock):
    class Handler(BaseHTTPRequestHandler):
        server_version = "MeetingDashboard/1"

        def log_message(self, fmt, *args):  # quieter than the default
            pass

        def _reply(self, code, body, content_type="application/json"):
            payload = body if isinstance(body, bytes) else json.dumps(body).encode()
            self.send_response(code)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def _static(self, name):
            target = (static_dir / name).resolve()
            if static_dir.resolve() not in target.parents or not target.is_file():
                self._reply(404, {"error": "not found"})
                return
            ctype = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
            self._reply(200, target.read_bytes(), ctype)

        def _dispatch(self, method):
            path = self.path.split("?", 1)[0]
            if method == "GET" and path in ("/", "/index.html"):
                self._static("index.html")
                return
            if method == "GET" and path.startswith("/static/"):
                self._static(path[len("/static/"):])
                return
            length = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(length) if length else b""
            try:
                payload = json.loads(raw) if raw else {}
            except json.JSONDecodeError:
                self._reply(400, {"error": "body is not valid JSON"})
                return
            if not isinstance(payload, dict):
                # Every route below calls payload.get(), and one does **payload,
                # all outside a try block: a JSON array or string body would be
                # an unhandled traceback and a reset socket rather than an error
                # the browser can show.
                self._reply(400, {"error": "body must be a JSON object"})
                return
            # One lock around the whole logical operation (store mutation plus
            # the dashboard.json rewrite that must reflect it): each request
            # is a single unit of work, and the export must never interleave
            # with another request's write to the same connection or file.
            with lock:
                try:
                    result = _handle_api(conn, method, path, payload)
                except ApiError as exc:
                    self._reply(exc.code, {"error": exc.message})
                    return
                if method != "GET":
                    export_json(conn, json_path)
            self._reply(200, result)

        def do_GET(self):
            self._dispatch("GET")

        def do_POST(self):
            self._dispatch("POST")

        def do_PATCH(self):
            self._dispatch("PATCH")

    return Handler


def make_server(conn, json_path, *, host="127.0.0.1", port=8765, static_dir=None):
    static_dir = Path(static_dir) if static_dir else STATIC
    lock = threading.Lock()
    return ThreadingHTTPServer((host, port), _make_handler(conn, json_path, static_dir, lock))


def run(conn, json_path, *, host="127.0.0.1", port=8765, static_dir=None):
    httpd = make_server(conn, json_path, host=host, port=port, static_dir=static_dir)
    bound = httpd.server_address[1]
    print(f"Meeting dashboard: http://{host}:{bound}")
    print("  Ctrl-C to stop. Every change is saved as you make it.")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        httpd.server_close()
