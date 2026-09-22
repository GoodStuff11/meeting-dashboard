"""Reconcile the store against the tracker.

The whole point of this module is that regenerating the dashboard is a
reconciliation, not a generation: no prose is re-authored, and the only things
that change are the fields the tracker owns. What the UI owns — resolutions,
decisions, curated agenda, hand-set difficulty — survives untouched.
"""

import re
from dataclasses import dataclass, field
from datetime import date

from . import store
from .export import export_json
from .sources import clickup as clickup_source
from .sources.handoff import flag_title, read_handoff

# NOTE: "caption" is deliberately absent from _SMALL. Judging whether a
# caption is right is a decision, not a writing chore — see
# test_estimate_difficulty_reads_the_verbs, which expects "decide whether
# the caption is right" to land on "M".
_SMALL = re.compile(
    r"\b(rerun|re-run|regenerate|regenerated|relabel|rename|write|written|writing|"
    r"one line|note|record|cite|check|confirm)\b", re.I)
_LARGE = re.compile(
    r"\b(implement|implementation|rebuild|build|from scratch|new appendix|benchmark|"
    r"port|derive|a week|refactor)\b", re.I)


@dataclass
class SyncResult:
    added: list = field(default_factory=list)
    updated: list = field(default_factory=list)
    reverted: list = field(default_factory=list)
    reopened: list = field(default_factory=list)
    stale: list = field(default_factory=list)
    flags: list = field(default_factory=list)
    agenda_proposed: list = field(default_factory=list)


def estimate_difficulty(text):
    """Guess S/M/L from how the item describes the work. Always overridable."""
    text = text or ""
    if _LARGE.search(text):
        return "L"
    if _SMALL.search(text):
        return "S"
    return "M"


def _migrate_flag_keys(conn, flags):
    """Move any flag still keyed by its §7.1 ordinal onto its hashed key.

    Stores written before flags were keyed by content hold rows keyed "1", "2",
    ... and agenda items with origin `sync:flag:1`. Migrating keeps the row's
    `first_seen` and its curated agenda item instead of leaving both behind
    beside a freshly proposed duplicate.

    The join is the ordinal, not the stored text: a legacy key *is* a §7.1
    position, so the incoming flag at that position is the same disagreement
    even if somebody reworded its headline since the last sync. Hashing the
    row's own stored text instead would, on exactly that ordinary weekly edit,
    move the legacy row onto a hash §7.1 no longer produces — leaving a second
    row for one disagreement that nothing in this codebase can ever remove,
    since `delete_flag` refuses any non-`stale:` key.

    A legacy row whose ordinal is no longer in §7.1 is left under its numeric
    key. There is nothing to join it to, and an unmigrated row is at least
    still the row a person can see and reason about.
    """
    by_ordinal = {flag.ordinal: flag for flag in flags}
    for row in store.list_flags(conn):
        if not row["key"].isdigit():
            continue
        incoming = by_ordinal.get(row["key"])
        if incoming is None:
            continue
        store.rekey_flag(conn, row["key"], incoming.key, ordinal=incoming.ordinal)


def sync(conn, *, handoff_path, clickup_cache_path=None, json_path=None, today=None):
    """Reconcile the store against HANDOFF.md section 7, plus a ClickUp cache if given."""
    today = today or date.today().isoformat()
    items, flags = read_handoff(handoff_path)
    if clickup_cache_path is not None:
        cache = clickup_source.load_cache(clickup_cache_path)
        items = clickup_source.merge(items, cache)
        store.set_meta(conn, "last_clickup_pull", cache.get("pulled_on"))

    result = SyncResult()
    known = {q["id"]: q for q in store.list_questions(conn)}
    seen = set()

    for item in items:
        seen.add(item.id)
        before = known.get(item.id)
        if before is None:
            result.added.append(item.id)
        elif before["state"] == "closed" and before["state_source"] == "ui" \
                and item.state == "open":
            # The UI closed it in a meeting; section 7 has not caught up. Hand it back
            # rather than dropping it, then let the tracker win.
            result.reverted.append({
                "id": item.id,
                "title": before["title"],
                "note": before["closed_note"] or "",
                "closed_on": before["closed_on"] or "",
            })
        elif before["state"] == "open" and before["state_source"] == "ui" \
                and item.state == "closed":
            # The mirror case: section 7 says closed, the group reopened it in the
            # meeting. The tracker still wins, but the reopening is a decision
            # somebody took and is owed back to section 7 — without this it would
            # fall into `updated`, which nothing renders.
            result.reopened.append({
                "id": item.id,
                "title": before["title"],
                "reopened_on": before["reopened_on"] or "",
            })
        elif any(before[f] != getattr(item, f) for f in ("title", "why", "owner", "state")):
            result.updated.append(item.id)

        store.upsert_question(
            conn, id=item.id, title=item.title, why=item.why, owner=item.owner,
            priority=item.priority, raised=item.raised, state=item.state,
            clickup_id=item.clickup_id, clickup_status=item.clickup_status, due=item.due,
            actor="sync")

        row = store.get_question(conn, item.id)
        if row["difficulty_source"] != "user":
            store.set_question_difficulty(
                conn, item.id, estimate_difficulty(f"{item.title} {item.why}"),
                source="agent", actor="sync")

        # This item is in the current parse, so any earlier "gone from section 7"
        # observation about it no longer holds. Retract it — speculatively, since
        # most items were never stale — before the loop below writes fresh stale
        # flags for whatever is *not* in `seen` this run.
        store.delete_flag(conn, f"stale:{item.id}", actor="sync")

    for qid, row in known.items():
        if qid not in seen:
            result.stale.append(qid)
            store.upsert_flag(
                conn, key=f"stale:{qid}",
                text=(f"Item {qid} ({row['title']}) is in the dashboard but no longer in "
                      "HANDOFF.md section 7. Listed, not resolved."),
                first_seen=today)

    _migrate_flag_keys(conn, flags)
    for flag in flags:
        result.flags.append(flag.key)
        store.upsert_flag(conn, key=flag.key, text=flag.text, first_seen=today,
                          resolved=1 if flag.resolved else 0, ordinal=flag.ordinal)

    existing_origins = {a["origin"] for a in store.list_agenda(conn)}
    for flag in flags:
        if flag.resolved:
            continue
        origin = f"sync:flag:{flag.key}"
        if origin in existing_origins:
            continue
        store.add_agenda(conn, title=flag_title(flag.text), detail=flag.text,
                         origin=origin, proposed_by="sync", created=today, actor="sync")
        result.agenda_proposed.append(origin)

    for row in store.list_questions(conn, state="open"):
        if row["priority"] != "high" and not (row["due"] and row["due"] <= today):
            continue
        origin = f"sync:item:{row['id']}"
        if origin in existing_origins:
            continue
        store.add_agenda(conn, title=f"Item {row['id']} — {row['title']}",
                         detail=row["why"], origin=origin, proposed_by="sync",
                         created=today, actor="sync")
        result.agenda_proposed.append(origin)

    store.set_meta(conn, "last_sync", today)
    if json_path is not None:
        export_json(conn, json_path)
    return result
