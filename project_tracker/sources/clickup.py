"""Cached ClickUp snapshot.

Nothing here touches the network. Pulling from ClickUp is expensive and needs a
connector this process does not have, so an agent that *does* have one writes
the snapshot with `save_cache`, and every later sync reads it for free.
"""

import json
from dataclasses import replace
from datetime import date
from pathlib import Path


def load_cache(path):
    """Load cache from disk. Returns a fresh dict on every call.

    If the file is missing, returns {"pulled_on": None, "tasks": {}}.
    If the file exists but is malformed JSON, raises JSONDecodeError.
    The returned dict is always a new object (never shared with the module).
    """
    path = Path(path)
    if not path.exists():
        return {"pulled_on": None, "tasks": {}}
    doc = json.loads(path.read_text())
    return {"pulled_on": doc.get("pulled_on"), "tasks": doc.get("tasks") or {}}


def save_cache(path, tasks, *, pulled_on=None):
    """Write a snapshot. `tasks` maps ClickUp task id -> {status, priority, due}."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    doc = {"pulled_on": pulled_on or date.today().isoformat(), "tasks": tasks}
    path.write_text(json.dumps(doc, indent=2, sort_keys=True, ensure_ascii=False) + "\n")


def merge(items, cache):
    """Return new Items with ClickUp status, priority and due date applied."""
    tasks = cache.get("tasks") or {}
    out = []
    for item in items:
        task = tasks.get(item.clickup_id) if item.clickup_id else None
        if not task:
            out.append(replace(item))
            continue
        out.append(replace(
            item,
            clickup_status=task.get("status"),
            priority=task.get("priority") or item.priority,
            due=task.get("due"),
        ))
    return out


def cache_age_days(path, today=None):
    cache = load_cache(path)
    if not cache["pulled_on"]:
        return None
    then = date.fromisoformat(cache["pulled_on"])
    now = date.fromisoformat(today) if today else date.today()
    return (now - then).days
