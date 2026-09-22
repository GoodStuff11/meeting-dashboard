"""SQLite store for the meeting dashboard.

Every mutation goes through a function here, and every mutation that changes a
field a person would care about appends to `changelog`.

`changelog` is a local audit trail and nothing more. It is deliberately not
exported to `dashboard.json` and nothing reads it back — in particular
`report.py` does not: what is owed to §7 is derived from the store's own state
(a reverted closure, a reopening, a decision row), which is simpler than
replaying a log and cannot fall behind it. The log is there for a person asking
"what happened to this item, and when", and for tests.
"""

import json
import re
import sqlite3
from datetime import date, datetime
from pathlib import Path

_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

SCHEMA_VERSION = 2

# Columns added after schema version 1. `CREATE TABLE IF NOT EXISTS` cannot add
# a column to a database that already exists, and the .db is a local cache that
# nobody thinks to delete, so each one is applied by `connect` on open. Adding a
# nullable column is the only migration shape this store supports.
_ADDED_COLUMNS = (
    ("questions", "reopened_on", "TEXT"),
    ("flags", "ordinal", "TEXT"),
)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS questions (
    id                TEXT PRIMARY KEY,
    title             TEXT NOT NULL,
    why               TEXT NOT NULL DEFAULT '',
    owner             TEXT NOT NULL DEFAULT '',
    priority          TEXT NOT NULL DEFAULT '',
    raised            TEXT NOT NULL DEFAULT '',
    clickup_id        TEXT,
    clickup_status    TEXT,
    due               TEXT,
    state             TEXT NOT NULL DEFAULT 'open',
    state_source      TEXT NOT NULL DEFAULT 'tracker',
    difficulty        TEXT,
    difficulty_source TEXT,
    closed_on         TEXT,
    closed_note       TEXT,
    reopened_on       TEXT,
    last_seen_sync    TEXT,
    updated_at        TEXT
);
CREATE TABLE IF NOT EXISTS agenda (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    title        TEXT NOT NULL,
    detail       TEXT NOT NULL DEFAULT '',
    origin       TEXT NOT NULL DEFAULT 'manual',
    proposed_by  TEXT NOT NULL DEFAULT '',
    created      TEXT NOT NULL DEFAULT '',
    sort_order   INTEGER NOT NULL DEFAULT 0,
    status       TEXT NOT NULL DEFAULT 'proposed',
    resolution   TEXT,
    followups    TEXT,
    resolved_on  TEXT,
    resolved_by  TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS agenda_origin_unique
    ON agenda(origin) WHERE origin != 'manual';
CREATE TABLE IF NOT EXISTS decisions (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    text           TEXT NOT NULL,
    grounds        TEXT NOT NULL,
    decided_on     TEXT NOT NULL,
    decided_by     TEXT NOT NULL DEFAULT '',
    followups      TEXT,
    from_agenda_id INTEGER,
    source         TEXT NOT NULL DEFAULT 'ui'
);
CREATE TABLE IF NOT EXISTS flags (
    key        TEXT PRIMARY KEY,
    text       TEXT NOT NULL,
    first_seen TEXT NOT NULL DEFAULT '',
    resolved   INTEGER NOT NULL DEFAULT 0,
    ordinal    TEXT
);
CREATE TABLE IF NOT EXISTS changelog (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    ts        TEXT NOT NULL,
    entity    TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    field     TEXT NOT NULL,
    old       TEXT,
    new       TEXT,
    actor     TEXT NOT NULL DEFAULT 'ui'
);
CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""

_TRACKER_FIELDS = ("title", "why", "owner", "priority", "raised",
                   "clickup_id", "clickup_status", "due", "state")
_AGENDA_FIELDS = ("title", "detail", "origin", "proposed_by", "created", "sort_order",
                  "status", "resolution", "followups", "resolved_on", "resolved_by")


class AlreadyClosed(ValueError):
    """Raised when something already closed is closed again.

    A `ValueError` so existing callers that map `ValueError` to a 400 keep
    working; `serve.py` catches this subclass first and answers 409, which is
    what a duplicate submission actually is.
    """


def connect(db_path):
    """Open (creating if needed) the store at `db_path` and apply the schema."""
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(_SCHEMA)
    conn.commit()
    _migrate(conn)
    _set_meta_raw(conn, "schema_version", str(SCHEMA_VERSION))
    conn.commit()
    return conn


def _migrate(conn):
    """Add any column a newer schema version introduced. See `_ADDED_COLUMNS`."""
    for table, column, decl in _ADDED_COLUMNS:
        have = {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}
        if column not in have:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {decl}")
    conn.commit()


def _today():
    return date.today().isoformat()


def _now():
    return datetime.now().isoformat(timespec="seconds")


def log(conn, entity, entity_id, field, old, new, actor):
    """Append a changelog entry to the pending transaction.

    Does not commit: the caller (a public mutator) commits once, after its own
    row write and every `log()` call it makes, so a failure partway through
    leaves neither the row change nor its log entry durable.
    """
    conn.execute(
        "INSERT INTO changelog (ts, entity, entity_id, field, old, new, actor)"
        " VALUES (?,?,?,?,?,?,?)",
        (_now(), entity, str(entity_id), field,
         None if old is None else str(old), None if new is None else str(new), actor),
    )


def list_changes(conn, since_id=0):
    rows = conn.execute("SELECT * FROM changelog WHERE id > ? ORDER BY id", (since_id,))
    return [dict(r) for r in rows]


def _set_meta_raw(conn, key, value):
    conn.execute("INSERT INTO meta (key, value) VALUES (?,?)"
                 " ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, value))


def set_meta(conn, key, value):
    _set_meta_raw(conn, key, json.dumps(value, sort_keys=True, ensure_ascii=False))
    conn.commit()


def get_meta(conn, key, default=None):
    row = conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
    if row is None:
        return default
    try:
        return json.loads(row["value"])
    except json.JSONDecodeError:
        return row["value"]


def record_meeting(conn, on, *, label="", actor="ui"):
    """Append a meeting date to `meta['meetings']`, deduplicated and sorted.

    This list is what the staleness counter counts: how many meetings an item
    has survived. Nothing wrote it before, so every card read "0 mtg", which is
    worse than no counter at all because it reads as "nothing is stale".
    """
    on = str(on).strip()
    if not _DATE.match(on):
        raise ValueError(f"a meeting date must look like YYYY-MM-DD, got {on!r}")
    meetings = get_meta(conn, "meetings", default=[]) or []
    by_date = {m["date"]: m for m in meetings if m.get("date")}
    if on in by_date:
        if label:
            by_date[on]["label"] = label
    else:
        by_date[on] = {"date": on, "label": label}
        log(conn, "meeting", on, "recorded", None, on, actor)
    ordered = [by_date[d] for d in sorted(by_date)]
    set_meta(conn, "meetings", ordered)
    return ordered


def get_question(conn, qid):
    row = conn.execute("SELECT * FROM questions WHERE id = ?", (str(qid),)).fetchone()
    return None if row is None else dict(row)


def list_questions(conn, state=None):
    if state is None:
        rows = conn.execute("SELECT * FROM questions ORDER BY id")
    else:
        rows = conn.execute("SELECT * FROM questions WHERE state = ? ORDER BY id", (state,))
    return [dict(r) for r in rows]


def upsert_question(conn, *, id, title, why="", owner="", priority="", raised="",
                    state="open", clickup_id=None, clickup_status=None, due=None,
                    actor="sync"):
    """Insert or refresh a question's tracker-owned fields.

    UI-owned fields (difficulty when set by a user, closed_note, closed_on) are
    never touched here. `state` is tracker-owned by design: see sync.py.
    """
    qid = str(id)
    incoming = dict(title=title, why=why, owner=owner, priority=priority, raised=raised,
                    clickup_id=clickup_id, clickup_status=clickup_status, due=due,
                    state=state)
    existing = get_question(conn, qid)
    if existing is None:
        conn.execute(
            "INSERT INTO questions (id, title, why, owner, priority, raised, clickup_id,"
            " clickup_status, due, state, state_source, last_seen_sync, updated_at)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,'tracker',?,?)",
            (qid, title, why, owner, priority, raised, clickup_id, clickup_status, due,
             state, _today(), _now()),
        )
        log(conn, "question", qid, "created", None, title, actor)
        conn.commit()
        return
    for field in _TRACKER_FIELDS:
        if existing[field] != incoming[field]:
            log(conn, "question", qid, field, existing[field], incoming[field], actor)
    conn.execute(
        "UPDATE questions SET title=?, why=?, owner=?, priority=?, raised=?, clickup_id=?,"
        " clickup_status=?, due=?, state=?, state_source='tracker', last_seen_sync=?,"
        " updated_at=? WHERE id=?",
        (title, why, owner, priority, raised, clickup_id, clickup_status, due, state,
         _today(), _now(), qid),
    )
    conn.commit()


def set_question_state(conn, qid, state, *, source, note=None, on=None, actor="ui"):
    qid = str(qid)
    existing = get_question(conn, qid)
    if existing is None:
        raise KeyError(f"no question {qid!r}")
    if state not in ("open", "closed"):
        raise ValueError(f"state must be 'open' or 'closed', got {state!r}")
    closed_on = (on or _today()) if state == "closed" else None
    closed_note = note if state == "closed" else None
    # `reopened_on` is the mirror of `closed_on`: the breadcrumb a UI reopening
    # leaves behind. It has to outlive the sync that overrides it, because
    # section 7 dictating `closed` is exactly when the reopening becomes an edit
    # owed back to section 7 (see report._reopened_rows). upsert_question never
    # touches it, so it survives; closing the item in the UI clears it, just as
    # reopening clears closed_on.
    if state == "closed":
        reopened_on = None
    elif source == "ui" and existing["state"] == "closed":
        reopened_on = on or _today()
    else:
        reopened_on = existing["reopened_on"]
    if existing["state"] != state:
        log(conn, "question", qid, "state", existing["state"], state, actor)
    conn.execute(
        "UPDATE questions SET state=?, state_source=?, closed_on=?, closed_note=?,"
        " reopened_on=?, updated_at=? WHERE id=?",
        (state, source, closed_on, closed_note, reopened_on, _now(), qid),
    )
    conn.commit()


def set_question_difficulty(conn, qid, difficulty, *, source, actor="ui"):
    qid = str(qid)
    existing = get_question(conn, qid)
    if existing is None:
        raise KeyError(f"no question {qid!r}")
    if difficulty not in ("S", "M", "L", None):
        raise ValueError(f"difficulty must be S, M, L or None, got {difficulty!r}")
    if existing["difficulty"] != difficulty:
        log(conn, "question", qid, "difficulty", existing["difficulty"], difficulty, actor)
    conn.execute("UPDATE questions SET difficulty=?, difficulty_source=?, updated_at=?"
                 " WHERE id=?", (difficulty, source, _now(), qid))
    conn.commit()


def _agenda_row(row):
    d = dict(row)
    d["followups"] = json.loads(d["followups"]) if d["followups"] else []
    return d


def list_agenda(conn, status=None):
    if status is None:
        rows = conn.execute("SELECT * FROM agenda ORDER BY sort_order, id")
    else:
        rows = conn.execute("SELECT * FROM agenda WHERE status = ? ORDER BY sort_order, id",
                            (status,))
    return [_agenda_row(r) for r in rows]


def get_agenda(conn, aid):
    row = conn.execute("SELECT * FROM agenda WHERE id = ?", (aid,)).fetchone()
    return None if row is None else _agenda_row(row)


def add_agenda(conn, *, title, detail="", origin="manual", proposed_by="", created=None,
               status="proposed", actor="ui"):
    nxt = conn.execute("SELECT COALESCE(MAX(sort_order), -1) + 1 AS n FROM agenda"
                       ).fetchone()["n"]
    cur = conn.execute(
        "INSERT INTO agenda (title, detail, origin, proposed_by, created, sort_order, status)"
        " VALUES (?,?,?,?,?,?,?)",
        (title, detail, origin, proposed_by, created or _today(), nxt, status),
    )
    aid = cur.lastrowid
    log(conn, "agenda", aid, "created", None, title, actor)
    conn.commit()
    return aid


def _update_agenda(conn, aid, *, actor="ui", **fields):
    """Non-committing core of `update_agenda`. Leaves the write on the pending
    transaction so callers (e.g. `close_agenda`) can compose it with other
    writes under a single commit."""
    existing = get_agenda(conn, aid)
    if existing is None:
        raise KeyError(f"no agenda item {aid!r}")
    unknown = set(fields) - set(_AGENDA_FIELDS)
    if unknown:
        raise ValueError(f"unknown agenda fields: {sorted(unknown)}")
    if not fields:
        return
    values = dict(fields)
    if "followups" in values and not isinstance(values["followups"], str):
        values["followups"] = json.dumps(values["followups"] or [], ensure_ascii=False)
    for key, new in values.items():
        old = existing[key]
        if key == "followups":
            old = json.dumps(old, ensure_ascii=False)
        if old != new:
            log(conn, "agenda", aid, key, old, new, actor)
    assignments = ", ".join(f"{k}=?" for k in values)
    conn.execute(f"UPDATE agenda SET {assignments} WHERE id=?",
                 (*values.values(), aid))


def update_agenda(conn, aid, *, actor="ui", **fields):
    _update_agenda(conn, aid, actor=actor, **fields)
    conn.commit()


def reorder_agenda(conn, ordered_ids, *, actor="ui"):
    for position, aid in enumerate(ordered_ids):
        conn.execute("UPDATE agenda SET sort_order=? WHERE id=?", (position, aid))
    log(conn, "agenda", "*", "sort_order", None, ",".join(str(i) for i in ordered_ids), actor)
    conn.commit()


def close_agenda(conn, aid, *, resolution, resolved_by, followups=None, resolved_on=None,
                 actor="ui"):
    """Close an agenda item and mint the decision it becomes. Returns the decision id.

    The agenda update and the decision insert share a single transaction: if
    anything raises before both writes are in, the transaction is rolled back
    so the agenda item is never left `closed` without its decision.
    """
    existing = get_agenda(conn, aid)
    if existing is None:
        raise KeyError(f"no agenda item {aid!r}")
    if existing["status"] == "closed":
        # A double-click on "Close → Decisions" fires the second handler on the
        # still-mounted card before the reload replaces it. Without this the
        # store mints a second identical decision, which then reaches
        # pending-changes.md and is folded into section 7 twice. Guarded here
        # rather than in the browser: the browser is not the only caller.
        raise AlreadyClosed(
            f"agenda item {aid!r} is already closed; closing it again would mint "
            "a second decision")
    if not (resolution or "").strip():
        raise ValueError("an agenda item cannot be closed without a resolution")
    on = resolved_on or _today()
    try:
        _update_agenda(conn, aid, status="closed", resolution=resolution,
                       resolved_by=resolved_by, resolved_on=on, followups=followups or [],
                       actor=actor)
        did = _add_decision(conn, text=existing["title"], grounds=resolution, decided_on=on,
                            decided_by=resolved_by, followups=followups, from_agenda_id=aid,
                            source="ui", actor=actor)
    except Exception:
        conn.rollback()
        raise
    conn.commit()
    return did


def _decision_row(row):
    d = dict(row)
    d["followups"] = json.loads(d["followups"]) if d["followups"] else []
    return d


def get_decision(conn, did):
    row = conn.execute("SELECT * FROM decisions WHERE id = ?", (did,)).fetchone()
    return None if row is None else _decision_row(row)


def _add_decision(conn, *, text, grounds, decided_on, decided_by="", followups=None,
                  from_agenda_id=None, source="ui", actor="ui"):
    """Non-committing core of `add_decision`. See `_update_agenda`."""
    if not (grounds or "").strip():
        raise ValueError("a decision requires grounds; the grounds field is not optional")
    cur = conn.execute(
        "INSERT INTO decisions (text, grounds, decided_on, decided_by, followups,"
        " from_agenda_id, source) VALUES (?,?,?,?,?,?,?)",
        (text, grounds, decided_on, decided_by,
         json.dumps(followups or [], ensure_ascii=False), from_agenda_id, source),
    )
    did = cur.lastrowid
    log(conn, "decision", did, "created", None, text, actor)
    return did


def add_decision(conn, *, text, grounds, decided_on, decided_by="", followups=None,
                 from_agenda_id=None, source="ui", actor="ui"):
    did = _add_decision(conn, text=text, grounds=grounds, decided_on=decided_on,
                        decided_by=decided_by, followups=followups,
                        from_agenda_id=from_agenda_id, source=source, actor=actor)
    conn.commit()
    return did


def update_decision(conn, did, *, text=None, grounds=None, decided_by=None, actor="ui"):
    """Update a decision's text, grounds or attribution. Grounds may never be emptied."""
    existing = get_decision(conn, did)
    if existing is None:
        raise KeyError(f"no decision {did!r}")
    if grounds is not None and not grounds.strip():
        raise ValueError("a decision requires grounds; the grounds field is not optional")
    fields = {}
    if text is not None:
        fields["text"] = text
    if grounds is not None:
        fields["grounds"] = grounds
    if decided_by is not None:
        fields["decided_by"] = decided_by
    if not fields:
        return
    for key, new in fields.items():
        old = existing[key]
        if old != new:
            log(conn, "decision", did, key, old, new, actor)
    assignments = ", ".join(f"{k}=?" for k in fields)
    conn.execute(f"UPDATE decisions SET {assignments} WHERE id=?",
                 (*fields.values(), did))
    conn.commit()


def list_decisions(conn):
    rows = conn.execute("SELECT * FROM decisions ORDER BY decided_on DESC, id DESC")
    return [_decision_row(r) for r in rows]


def upsert_flag(conn, *, key, text, first_seen, resolved=0, ordinal=None):
    """Insert a flag, or refresh its text. `first_seen` is never overwritten.

    `ordinal` is the §7.1 number, display only, and does move: it is exactly
    the thing that renumbers when somebody inserts a disagreement, which is why
    `key` is a hash of the text instead (see `sources.handoff.flag_key`).
    """
    conn.execute(
        "INSERT INTO flags (key, text, first_seen, resolved, ordinal) VALUES (?,?,?,?,?)"
        " ON CONFLICT(key) DO UPDATE SET text=excluded.text, resolved=excluded.resolved,"
        " ordinal=excluded.ordinal",
        (str(key), text, first_seen, int(resolved), ordinal),
    )
    conn.commit()


def rekey_flag(conn, old_key, new_key, *, ordinal=None, actor="sync"):
    """Move a flag row (and anything keyed off it) from `old_key` to `new_key`.

    Written for the one-off migration off positional §7.1 keys. If `new_key`
    already exists the old row is simply dropped, so a store that has been
    partly migrated does not end up listing the same disagreement twice.
    Agenda origins are moved with it: an accepted `sync:flag:<old>` item would
    otherwise be orphaned and the flag re-proposed as a fresh candidate.
    """
    old_key, new_key = str(old_key), str(new_key)
    if old_key == new_key:
        return
    existing = conn.execute("SELECT * FROM flags WHERE key = ?", (old_key,)).fetchone()
    if existing is None:
        return
    target = conn.execute("SELECT 1 FROM flags WHERE key = ?", (new_key,)).fetchone()
    if target is None:
        conn.execute(
            "INSERT INTO flags (key, text, first_seen, resolved, ordinal) VALUES (?,?,?,?,?)",
            (new_key, existing["text"], existing["first_seen"], existing["resolved"],
             ordinal))
    conn.execute("DELETE FROM flags WHERE key = ?", (old_key,))
    old_origin, new_origin = f"sync:flag:{old_key}", f"sync:flag:{new_key}"
    clash = conn.execute("SELECT 1 FROM agenda WHERE origin = ?", (new_origin,)).fetchone()
    if clash is None:
        conn.execute("UPDATE agenda SET origin=? WHERE origin=?", (new_origin, old_origin))
    log(conn, "flag", old_key, "key", old_key, new_key, actor)
    conn.commit()


def list_flags(conn):
    """Flags in §7.1 order, with anything unnumbered (stale-item flags) last."""
    return [dict(r) for r in conn.execute(
        "SELECT * FROM flags ORDER BY (ordinal IS NULL OR ordinal = ''),"
        " CAST(ordinal AS INTEGER), key")]


def delete_flag(conn, key, *, actor="sync"):
    """Remove a flag row outright, for a flag whose premise has simply expired.

    Restricted to `stale:`-prefixed keys by construction: those are the only
    flags sync generates on its own (a machine observation that an item
    dropped out of section 7), so they are the only flags sync may retract on
    its own. A `### 7.1` disagreement flag can never reach this path, no
    matter what a caller passes — nothing in this codebase may resolve or
    remove one of those automatically.

    A no-op, not an error, when `key` is absent: sync calls this speculatively
    for every item it sees, whether or not a stale flag exists for it.
    """
    key = str(key)
    if not key.startswith("stale:"):
        raise ValueError(
            f"delete_flag only removes 'stale:'-prefixed flags (machine-generated, "
            f"self-expiring); refusing to delete {key!r}")
    existing = conn.execute("SELECT * FROM flags WHERE key = ?", (key,)).fetchone()
    if existing is None:
        return
    conn.execute("DELETE FROM flags WHERE key = ?", (key,))
    log(conn, "flag", key, "deleted", existing["text"], None, actor)
    conn.commit()
