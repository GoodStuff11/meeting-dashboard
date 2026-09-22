import json

from project_tracker.sources import Item
from project_tracker.sources.clickup import cache_age_days, load_cache, merge, save_cache


def _items():
    return [
        Item(id="1", title="Cost per gradient", clickup_id="86akhc9zz"),
        Item(id="21", title="HVA benchmark", clickup_id=None),
    ]


def test_save_and_load_cache_round_trip(tmp_path):
    path = tmp_path / "clickup-cache.json"
    save_cache(path, {"86akhc9zz": {"status": "in progress", "priority": "high",
                                    "due": "2026-09-30"}}, pulled_on="2026-09-21")
    cache = load_cache(path)
    assert cache["tasks"]["86akhc9zz"]["priority"] == "high"
    assert cache["pulled_on"] == "2026-09-21"


def test_load_cache_returns_an_empty_shape_when_absent(tmp_path):
    cache = load_cache(tmp_path / "missing.json")
    assert cache == {"pulled_on": None, "tasks": {}}


def test_load_cache_does_not_share_mutable_state(tmp_path):
    """Regression test: load_cache must return a fresh dict, not share module state."""
    missing_path = tmp_path / "missing.json"

    # Load from missing file, mutate the returned dict
    cache1 = load_cache(missing_path)
    cache1["tasks"]["leaked_key"] = "polluted"

    # Load again from the same missing file
    cache2 = load_cache(missing_path)

    # The second load should be clean, not polluted by the first
    assert cache2["tasks"] == {}, \
        f"Expected empty tasks dict, but got {cache2['tasks']}. " \
        "This indicates mutable state is being shared across load_cache calls."
    assert cache2 is not cache1, "load_cache must return a new dict each time"


def test_merge_applies_status_priority_and_due(tmp_path):
    cache = {"pulled_on": "2026-09-21",
             "tasks": {"86akhc9zz": {"status": "in progress", "priority": "high",
                                     "due": "2026-09-30"}}}
    merged = {i.id: i for i in merge(_items(), cache)}
    assert merged["1"].clickup_status == "in progress"
    assert merged["1"].priority == "high"
    assert merged["1"].due == "2026-09-30"


def test_merge_leaves_items_without_a_task_untouched(tmp_path):
    cache = {"pulled_on": "2026-09-21", "tasks": {}}
    merged = {i.id: i for i in merge(_items(), cache)}
    assert merged["21"].clickup_status is None
    assert merged["21"].priority == ""


def test_merge_does_not_mutate_the_input_items():
    items = _items()
    cache = {"pulled_on": "x", "tasks": {"86akhc9zz": {"priority": "high"}}}
    merged = merge(items, cache)

    # Input items must not be modified
    assert items[0].priority == "", "Input item[0] was mutated in priority field"
    assert items[1].priority == "", "Input item[1] was mutated in priority field"

    # Returned items must be different objects (not the same object)
    # Even the no-match branch (items[1]) must return a new object
    assert merged[0] is not items[0], "merge must return new Item for matched task"
    assert merged[1] is not items[1], "merge must return new Item for items without ClickUp task"


def test_save_cache_is_deterministic(tmp_path):
    path = tmp_path / "c.json"
    tasks = {"b": {"priority": "low"}, "a": {"priority": "high"}}
    save_cache(path, tasks, pulled_on="2026-09-21")
    first = path.read_bytes()
    save_cache(path, tasks, pulled_on="2026-09-21")
    assert path.read_bytes() == first
    assert list(json.loads(path.read_text())["tasks"]) == ["a", "b"]


def test_cache_age_days_counts_from_pulled_on(tmp_path):
    path = tmp_path / "c.json"
    save_cache(path, {}, pulled_on="2026-09-14")
    assert cache_age_days(path, today="2026-09-21") == 7


def test_cache_age_days_is_none_without_a_cache(tmp_path):
    assert cache_age_days(tmp_path / "missing.json", today="2026-09-21") is None
