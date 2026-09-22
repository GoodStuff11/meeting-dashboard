"""Render what the dashboard owes HANDOFF.md section 7.

The dashboard never edits section 7 — item numbers are born there and an agent
rewriting that ledger unreviewed is how it gets corrupted. Instead every state
change the UI made that the tracker does not know about lands here, in prose a
person can fold in.

This file renders every decision on every call, not only those since some marker.
While an incremental approach (a "everything after this point" marker in `meta`)
might be more efficient, it would risk silently omitting decisions that a person never got round to folding in — since there is
no acknowledgement step anywhere in the system to confirm which changes were
actually applied to section 7. Repetition is visible noise a reader can skim
past; omission is silent loss, which is the exact failure this whole design
exists to prevent.

The same argument applies, more sharply, to the state collisions: a UI closure
section 7 overrode, and its mirror, a UI reopening. Those are re-derived from
store state on every render (see `_reverted_rows` and `_reopened_rows`) rather
than taken on trust from the one sync that happened to notice them — because
that sync is also the sync that resolves them, so a second `./dashboard update`
would otherwise rewrite this file with the record gone.
"""

from datetime import date
from pathlib import Path

from . import store


def _natural(qid):
    """Sort '2' before '14' before '14b', the way section 7 lists them."""
    digits = "".join(c for c in str(qid) if c.isdigit())
    return (int(digits) if digits else 0, str(qid))


def _reverted_rows(conn, result):
    """Every UI closure that section 7 has overridden, from the store itself.

    `result.reverted` only ever holds what *this* sync noticed, and the same
    sync flips the row back to open/tracker — so the next sync sees nothing and
    would rewrite this file without the closure in it. The store keeps the
    signature: `state='open'` with a non-null `closed_on`/`closed_note` can only
    come from a UI closure that was handed back, because `upsert_question` never
    writes those fields and reopening in the UI clears them.

    Merged with `result.reverted` (first, deduplicated by id) so a revert this
    sync noticed and one it inherited both appear exactly once.

    The one thing this over-reports: a question the UI closed, that section 7
    then closed too, and that section 7 later reopens, keeps its `closed_on` and
    so is listed again. That is a redundant line in a file whose whole argument
    is that repetition is cheap and omission is not.
    """
    rows = {str(row["id"]): row for row in result.reverted}
    for row in store.list_questions(conn, state="open"):
        qid = str(row["id"])
        if qid in rows or not (row["closed_on"] or row["closed_note"]):
            continue
        rows[qid] = {"id": qid, "title": row["title"],
                     "note": row["closed_note"] or "",
                     "closed_on": row["closed_on"] or ""}
    return [rows[k] for k in sorted(rows, key=_natural)]


def _reopened_rows(conn, result):
    """The mirror of `_reverted_rows`: UI reopenings section 7 has overridden.

    Signature: `state='closed'` with a non-null `reopened_on`, which only
    `set_question_state` writes and only for a UI reopening.
    """
    rows = {str(row["id"]): row for row in result.reopened}
    for row in store.list_questions(conn, state="closed"):
        qid = str(row["id"])
        if qid in rows or not row["reopened_on"]:
            continue
        rows[qid] = {"id": qid, "title": row["title"],
                     "reopened_on": row["reopened_on"] or ""}
    return [rows[k] for k in sorted(rows, key=_natural)]


def render_pending(conn, result, *, today=None):
    today = today or date.today().isoformat()
    lines = [f"# Pending changes — {today}", "",
             "Written by the meeting dashboard. Nothing here has been applied to",
             "`HANDOFF.md`; §7 is where items are born and closed, so these are edits",
             "owed to it.", ""]
    body = []

    reverted = _reverted_rows(conn, result)
    if reverted:
        body.append("## Owed to `HANDOFF.md` §7 — closed in the UI, still open in §7")
        body.append("")
        for row in reverted:
            note = row.get("note") or "(no note recorded)"
            body.append(f"- **item {row['id']} — {row['title']}** closed "
                        f"{row.get('closed_on') or 'in the UI'}: {note}")
        body.append("")
        body.append("These were reverted to open, because §7 dictates state. Close them in")
        body.append("§7 to make the closure stick.")
        body.append("")

    reopened = _reopened_rows(conn, result)
    if reopened:
        body.append("## Owed to `HANDOFF.md` §7 — reopened in the UI, still closed in §7")
        body.append("")
        for row in reopened:
            body.append(f"- **item {row['id']} — {row['title']}** was reopened in the UI "
                        f"{row.get('reopened_on') or '(date not recorded)'}")
        body.append("")
        body.append("These were closed again, because §7 dictates state. Reopen them in §7")
        body.append("to make the reopening stick.")
        body.append("")

    decisions = store.list_decisions(conn)
    if decisions:
        body.append("## Owed to `HANDOFF.md` §7 — decisions taken in the UI")
        body.append("")
        for d in decisions:
            who = d["decided_by"] or "unattributed"
            body.append(f"- **{d['decided_on']} — {d['text']}** ({who}). "
                        f"Grounds: {d['grounds']}")
            if d["followups"]:
                body.append(f"  - Follow-up: {', '.join(d['followups'])}")
        body.append("")
        body.append("These decisions will keep appearing in this file every time it is")
        body.append("regenerated, because nothing in the dashboard can tell whether one was")
        body.append("actually folded into §7. The only way to make an entry stop appearing is")
        body.append("to put it in §7.")
        body.append("")

    if result.stale:
        body.append("## In the dashboard, no longer in §7")
        body.append("")
        for qid in result.stale:
            row = store.get_question(conn, qid)
            title = row["title"] if row else ""
            body.append(f"- **item {qid} — {title}**. Kept and flagged, not deleted.")
        body.append("")
        body.append("Either it was removed from §7 by mistake, or it should be retired here.")
        body.append("Listed, not resolved.")
        body.append("")

    if not body:
        body = ["Nothing owed. The dashboard and §7 agree.", ""]

    return "\n".join(lines + body).rstrip() + "\n"


def write_pending(conn, result, path, *, today=None):
    text = render_pending(conn, result, today=today)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return text
