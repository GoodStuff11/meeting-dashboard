"""Store <-> dashboard.json.

The JSON is the store of record: it is what git carries, so a collaborator who
clones the Overleaf repo has the database even though the .db file is ignored.
It must be byte-deterministic given store state, or every sync produces a noisy
diff and the file stops being reviewable.
"""

import hashlib
import json
from pathlib import Path

from . import store

SCHEMA = 1

# Meta key holding the sha256 of the last dashboard.json text this store wrote
# or imported. Local bookkeeping only: never added to _META_KEYS, since a hash
# of the JSON stored inside that same JSON would be self-referential and break
# byte-determinism (see export_json / ensure_db).
_EXPORT_HASH_KEY = "export_sha256"

# last_seen_sync and updated_at are deliberately excluded: store.upsert_question
# stamps both on every sync regardless of whether anything changed, so exporting
# them would make a no-op sync rewrite dashboard.json and break byte-determinism.
# Nothing reads them back on import; sync tracks what it has seen in memory.
_QUESTION_COLUMNS = ("id", "title", "why", "owner", "priority", "raised", "clickup_id",
                     "clickup_status", "due", "state", "state_source", "difficulty",
                     "difficulty_source", "closed_on", "closed_note", "reopened_on")
_AGENDA_COLUMNS = ("id", "title", "detail", "origin", "proposed_by", "created",
                   "sort_order", "status", "resolution", "followups", "resolved_on",
                   "resolved_by")
_DECISION_COLUMNS = ("id", "text", "grounds", "decided_on", "decided_by", "followups",
                     "from_agenda_id", "source")
_FLAG_COLUMNS = ("key", "text", "first_seen", "resolved", "ordinal")
_META_KEYS = ("meetings", "last_sync", "last_clickup_pull", "workflow_ran")


def _pick(row, columns):
    return {c: row.get(c) for c in columns}


def build_document(conn):
    meta = {k: store.get_meta(conn, k) for k in _META_KEYS}
    meta = {k: v for k, v in meta.items() if v is not None}
    return {
        "schema": SCHEMA,
        "meta": meta,
        "questions": [_pick(r, _QUESTION_COLUMNS) for r in store.list_questions(conn)],
        "agenda": [_pick(r, _AGENDA_COLUMNS) for r in store.list_agenda(conn)],
        "decisions": [_pick(r, _DECISION_COLUMNS) for r in store.list_decisions(conn)],
        "flags": [_pick(r, _FLAG_COLUMNS) for r in store.list_flags(conn)],
    }


def export_json(conn, json_path):
    """Write the store to `json_path` deterministically. Returns the document."""
    doc = build_document(conn)
    path = Path(json_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(doc, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    path.write_text(text)
    store.set_meta(conn, _EXPORT_HASH_KEY, hashlib.sha256(text.encode("utf-8")).hexdigest())
    return doc


def import_json(conn, json_path):
    """Replace the store's contents with the document at `json_path`.

    Replaces rather than merges: the JSON is authoritative when it is read.
    The changelog is deliberately not carried in the JSON, so it is left alone.

    The row replacement is atomic: if anything raises partway through, the
    transaction is rolled back so the store is never left with only some
    tables replaced (mirrors the pattern in `store.close_agenda`).
    """
    raw = Path(json_path).read_bytes()
    doc = json.loads(raw)
    try:
        conn.execute("DELETE FROM questions")
        conn.execute("DELETE FROM agenda")
        conn.execute("DELETE FROM decisions")
        conn.execute("DELETE FROM flags")
        for row in doc.get("questions", []):
            conn.execute(
                f"INSERT INTO questions ({','.join(_QUESTION_COLUMNS)})"
                f" VALUES ({','.join('?' * len(_QUESTION_COLUMNS))})",
                tuple(row.get(c) for c in _QUESTION_COLUMNS))
        for row in doc.get("agenda", []):
            values = dict(row)
            values["followups"] = json.dumps(values.get("followups") or [],
                                             ensure_ascii=False)
            conn.execute(
                f"INSERT INTO agenda ({','.join(_AGENDA_COLUMNS)})"
                f" VALUES ({','.join('?' * len(_AGENDA_COLUMNS))})",
                tuple(values.get(c) for c in _AGENDA_COLUMNS))
        for row in doc.get("decisions", []):
            values = dict(row)
            values["followups"] = json.dumps(values.get("followups") or [],
                                             ensure_ascii=False)
            conn.execute(
                f"INSERT INTO decisions ({','.join(_DECISION_COLUMNS)})"
                f" VALUES ({','.join('?' * len(_DECISION_COLUMNS))})",
                tuple(values.get(c) for c in _DECISION_COLUMNS))
        for row in doc.get("flags", []):
            conn.execute(
                f"INSERT INTO flags ({','.join(_FLAG_COLUMNS)})"
                f" VALUES ({','.join('?' * len(_FLAG_COLUMNS))})",
                tuple(row.get(c) for c in _FLAG_COLUMNS))
    except Exception:
        conn.rollback()
        raise
    conn.commit()
    store.set_meta(conn, _EXPORT_HASH_KEY, hashlib.sha256(raw).hexdigest())
    for key, value in (doc.get("meta") or {}).items():
        store.set_meta(conn, key, value)


def ensure_db(db_path, json_path):
    """Open the store, rebuilding it from JSON if the JSON's content is not what
    this database last imported or exported, or if the DB is absent.

    This is what makes `git pull && ./dashboard serve` work on a machine that has
    never run a sync: the .db is gitignored, the .json is not.

    Staleness is decided by content hash, not mtime: `export_json` always writes
    the .json *after* the store mutation that preceded it, so the .json's mtime
    trails the .db's in the ordinary case, and an mtime comparison would either
    re-import on every single startup or (once "fixed" by touching the .db) miss
    real edits made on disk between runs. A hash of the last-seen JSON text,
    stored in `meta` and refreshed by both `export_json` and `import_json`, does
    not have either failure mode.
    """
    db_path, json_path = Path(db_path), Path(json_path)
    existed = db_path.exists()
    conn = store.connect(db_path)
    stale = not existed
    if not stale and json_path.exists():
        current_hash = hashlib.sha256(json_path.read_bytes()).hexdigest()
        stale = current_hash != store.get_meta(conn, _EXPORT_HASH_KEY)
    if stale and json_path.exists():
        import_json(conn, json_path)
    return conn
