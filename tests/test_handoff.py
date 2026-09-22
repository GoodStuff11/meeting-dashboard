import pytest

from project_tracker.sources.handoff import HandoffParseError, parse_handoff

SAMPLE = """\
## 6. Do NOT re-add these

Nothing here should be parsed.

## 7. Open items (state at 2026-09-21)

Numbers are stable identifiers.

### Open — Jonathon

**1. Cost per gradient, exponential vs product form** — wall-clock per gradient for
path (a) vs (b). Lands in paragraph 17. *Asked 2026-09-10 in the channel; task `86akhc9zz`.*
**2. The small-dimension energy floor** — rerun at low dimension with tight tolerance.
*Task `86akhca00`.* **Answered 2026-09-21 but not yet written up.**

### Open — Tamra

**21. HVA benchmark: Cade's public code, or rebuilt?** Tamra · no task yet · raised
2026-09-14. Jonathon estimates about a day using their code.
**14b. The interim venue position** — a sub-item of 14. *Task `86akj18bz`.*

### Closed

**25. The certified data ledger is stale** — CLOSED 2026-09-21, no task was ever opened.
Regenerated the same day.
**23. Which loss do the runs use?** — CLOSED 2026-09-15, task `86akj1wtv`.

### 7.1 Flags — where this file, ClickUp and the code disagree (2026-09-21)

Listed, not resolved.

1. **Ten clusters or fourteen?** Item 7 asks for ten; the table covers 14.
2. ~~**Item 20 is closed but its standard is not met.**~~ RESOLVED 2026-09-21.
3. **Who owns updating this file?** The notes assign it to Eun-Ah; the task is Jonathon's.

## 8. Presentation choices worth keeping

Not parsed either.
"""


def test_parses_every_item_across_all_sections():
    items, _ = parse_handoff(SAMPLE)
    assert [i.id for i in items] == ["1", "2", "21", "14b", "25", "23"]


def test_ignores_content_outside_section_seven():
    items, _ = parse_handoff(SAMPLE)
    assert all("re-add" not in i.title for i in items)
    assert all("Presentation" not in i.title for i in items)


def test_assigns_owner_from_the_enclosing_heading():
    items, _ = parse_handoff(SAMPLE)
    by_id = {i.id: i for i in items}
    assert by_id["1"].owner == "Jonathon"
    assert by_id["21"].owner == "Tamra"
    assert by_id["25"].owner == ""


def test_state_follows_the_section():
    items, _ = parse_handoff(SAMPLE)
    by_id = {i.id: i for i in items}
    assert by_id["1"].state == "open"
    assert by_id["25"].state == "closed"


def test_sub_item_numbers_are_preserved_as_strings():
    items, _ = parse_handoff(SAMPLE)
    assert "14b" in {i.id for i in items}


def test_title_excludes_the_body():
    items, _ = parse_handoff(SAMPLE)
    by_id = {i.id: i for i in items}
    assert by_id["1"].title == "Cost per gradient, exponential vs product form"


def test_item_without_an_em_dash_still_parses_its_title():
    items, _ = parse_handoff(SAMPLE)
    by_id = {i.id: i for i in items}
    assert by_id["21"].title == "HVA benchmark: Cade's public code, or rebuilt?"


def test_extracts_clickup_task_ids_in_either_case():
    items, _ = parse_handoff(SAMPLE)
    by_id = {i.id: i for i in items}
    assert by_id["1"].clickup_id == "86akhc9zz"
    assert by_id["2"].clickup_id == "86akhca00"
    assert by_id["21"].clickup_id is None


def test_extracts_raised_dates_from_asked_or_raised():
    items, _ = parse_handoff(SAMPLE)
    by_id = {i.id: i for i in items}
    assert by_id["1"].raised == "2026-09-10"
    assert by_id["21"].raised == "2026-09-14"


def test_why_carries_the_body_text():
    items, _ = parse_handoff(SAMPLE)
    by_id = {i.id: i for i in items}
    assert "wall-clock per gradient" in by_id["1"].why


def test_parses_flags_and_marks_struck_through_ones_resolved():
    _, flags = parse_handoff(SAMPLE)
    assert [f.ordinal for f in flags] == ["1", "2", "3"]
    assert flags[0].resolved is False
    assert flags[1].resolved is True
    assert "Ten clusters or fourteen?" in flags[0].text


def test_flag_keys_are_derived_from_the_text_not_the_ordinal():
    """M9: §7.1 is hand-numbered, so inserting a disagreement at position 2
    renumbers every one below it. A key tied to the ordinal silently rewrites
    each later flag's text under an older flag's key."""
    _, before = parse_handoff(SAMPLE)
    renumbered = SAMPLE.replace(
        "1. **Ten clusters or fourteen?** Item 7 asks for ten; the table covers 14.\n",
        "1. **Ten clusters or fourteen?** Item 7 asks for ten; the table covers 14.\n"
        "2. **A brand new disagreement, inserted mid-list.** Nobody has settled it.\n",
    ).replace(
        "2. ~~**Item 20 is closed", "3. ~~**Item 20 is closed",
    ).replace(
        "3. **Who owns updating this file?**", "4. **Who owns updating this file?**",
    )
    _, after = parse_handoff(renumbered)

    by_key_before = {f.key: f.text for f in before}
    by_key_after = {f.key: f.text for f in after}
    assert [f.ordinal for f in after] == ["1", "2", "3", "4"]
    # every pre-existing flag keeps its key and its text
    for key, text in by_key_before.items():
        assert by_key_after[key] == text
    # and the inserted one is genuinely new
    assert len(set(by_key_after) - set(by_key_before)) == 1


def test_resolving_a_flag_does_not_change_its_key():
    """Resolution strikes the headline through and appends prose. If that moved
    the key, the unresolved flag would linger forever beside its resolved twin."""
    _, before = parse_handoff(SAMPLE)
    resolved = SAMPLE.replace(
        "1. **Ten clusters or fourteen?** Item 7 asks for ten; the table covers 14.",
        "1. ~~**Ten clusters or fourteen?**~~ RESOLVED 2026-09-21: the ten in Figs. 2-4.")
    _, after = parse_handoff(resolved)
    assert after[0].key == before[0].key
    assert after[0].resolved is True


def test_an_explicit_high_priority_marker_is_parsed():
    """S6: without this, item 14 — which decides the venue — sorts to the bottom."""
    text = """\
## 7. Open items (state at 2026-09-21)

### Open — Jonathon

**14. HVA at strong coupling on our cluster** — Cade-style HVA on the cluster.
**Decides the venue** (section 1). ~3 days. *Task `86akhca0p`, high priority.*
**15. Something else entirely** — no marker anywhere in this body.

## 8. Next
"""
    items, _ = parse_handoff(text)
    by_id = {i.id: i for i in items}
    assert by_id["14"].priority == "high"
    assert by_id["15"].priority == ""


def test_a_bolded_or_top_priority_marker_is_parsed_too():
    text = """\
## 7. Open items (state at 2026-09-21)

### Open — Jonathon

**1. One** — this is **high priority** and must not be missed.
**2. Two** — top priority, said in prose.
**3. Three** — the word priority appears, but not as a marker.

## 8. Next
"""
    items, _ = parse_handoff(text)
    by_id = {i.id: i for i in items}
    assert by_id["1"].priority == "high"
    assert by_id["2"].priority == "high"
    assert by_id["3"].priority == ""


def test_missing_section_seven_raises():
    with pytest.raises(HandoffParseError):
        parse_handoff("# A file\n\n## 1. Something else\n\nNo section seven here.\n")


def test_duplicate_item_numbers_raise():
    bad = SAMPLE.replace("**2. The small-dimension energy floor**",
                         "**1. The small-dimension energy floor**")
    with pytest.raises(HandoffParseError):
        parse_handoff(bad)


def test_a_section_with_no_items_raises():
    bad = """\
## 7. Open items (state at 2026-09-21)

### Open — Jonathon

Prose with no item headers at all.

## 8. Next
"""
    with pytest.raises(HandoffParseError):
        parse_handoff(bad)


import json
from pathlib import Path  # noqa: F401

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
EXPECTED_ITEMS = 30
EXPECTED_FLAGS = 7


@pytest.mark.skipif(REAL is None, reason="no HANDOFF.md configured")
def test_parses_the_real_handoff_without_losing_items():
    items, flags = parse_handoff(REAL.read_text())
    assert len(items) == EXPECTED_ITEMS
    assert len(flags) == EXPECTED_FLAGS
    assert "14b" in {i.id for i in items}
    assert {i.state for i in items} == {"open", "closed"}
    assert any(i.clickup_id for i in items)


@pytest.mark.skipif(REAL is None, reason="no HANDOFF.md configured")
def test_real_item_14_is_read_as_high_priority():
    """Its body says "*Task `86akhca0p`, high priority.*" and it decides the venue."""
    items, _ = parse_handoff(REAL.read_text())
    assert {i.id: i for i in items}["14"].priority == "high"


def test_malformed_header_missing_period_raises_and_names_the_line():
    bad = """\
## 7. Open items (state at 2026-09-21)

### Open — Jonathon

**1. Cost per gradient, exponential vs product form** — wall-clock per gradient.
**2 The small-dimension energy floor** — this header is missing its period.
**3. A third item, fine on its own** — nothing wrong here.

## 8. Next
"""
    with pytest.raises(HandoffParseError) as excinfo:
        parse_handoff(bad)
    message = str(excinfo.value)
    assert "The small-dimension energy floor" in message


def test_malformed_header_stray_space_raises_and_names_the_line():
    bad = """\
## 7. Open items (state at 2026-09-21)

### Open — Jonathon

**1. Cost per gradient, exponential vs product form** — wall-clock per gradient.
** 2. The small-dimension energy floor** — stray space after the opening bold marker.
**3. A third item, fine on its own** — nothing wrong here.

## 8. Next
"""
    with pytest.raises(HandoffParseError) as excinfo:
        parse_handoff(bad)
    message = str(excinfo.value)
    assert "The small-dimension energy floor" in message


def test_dated_progress_notes_do_not_trip_the_malformed_header_guard():
    ok = """\
## 7. Open items (state at 2026-09-21)

### Open — Jonathon

**1. Cost per gradient, exponential vs product form** — wall-clock per gradient.
**2026-09-21:** the timing data has been generated and looks consistent with
the earlier estimate. *Task `86akhc9zz`.*
**2. The small-dimension energy floor** — rerun at low dimension with tight tolerance.

## 8. Next
"""
    items, _ = parse_handoff(ok)
    assert [i.id for i in items] == ["1", "2"]
