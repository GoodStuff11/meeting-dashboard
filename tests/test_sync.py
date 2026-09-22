import pytest

from project_tracker.store import (
    add_agenda,
    close_agenda,
    connect,
    delete_flag,
    get_question,
    list_agenda,
    list_decisions,
    list_flags,
    set_question_difficulty,
    set_question_state,
    update_agenda,
)
from project_tracker.sources.handoff import flag_key
from project_tracker.store import upsert_flag
from project_tracker.sync import estimate_difficulty, sync

# The two §7.1 entries in the fixture below, as their bodies are parsed. Flag
# keys are a hash of the disagreement's headline, so these are how a test names
# a flag without knowing its hand-written ordinal.
FLAG_1 = "**Ten clusters or fourteen?** Someone has to say which set the paper shows."
FLAG_2 = "~~**Item 20's standard is not met.**~~ RESOLVED 2026-09-21."

HANDOFF = """\
## 7. Open items (state at 2026-09-21)

### Open — Jonathon

**1. Cost per gradient** — wall-clock per gradient for path (a) vs (b).
*Asked 2026-09-10; task `86akhc9zz`.*
**2. Write the answer into paragraph 17** — a writing task, nothing to run.
*Task `86akhca00`.*

### Open — Tamra

**21. Implement the HVA ansatz from scratch** — rebuild Cade's circuit builder in our
codebase. raised 2026-09-14.

### Closed

**25. The certified data ledger is stale** — CLOSED 2026-09-21.

### 7.1 Flags — disagreements (2026-09-21)

1. **Ten clusters or fourteen?** Someone has to say which set the paper shows.
2. ~~**Item 20's standard is not met.**~~ RESOLVED 2026-09-21.

## 8. Next
"""


@pytest.fixture
def handoff(tmp_path):
    path = tmp_path / "HANDOFF.md"
    path.write_text(HANDOFF)
    return path


@pytest.fixture
def conn(tmp_path):
    c = connect(tmp_path / "d.db")
    yield c
    c.close()


def test_first_sync_adds_every_item(conn, handoff):
    result = sync(conn, handoff_path=handoff, today="2026-09-21")
    assert sorted(result.added) == ["1", "2", "21", "25"]
    assert get_question(conn, "25")["state"] == "closed"
    assert get_question(conn, "1")["owner"] == "Jonathon"


def test_second_sync_adds_nothing_and_is_idempotent(conn, handoff):
    sync(conn, handoff_path=handoff, today="2026-09-21")
    result = sync(conn, handoff_path=handoff, today="2026-09-21")
    assert result.added == []


def test_tracker_text_overwrites_the_stored_description(conn, handoff, tmp_path):
    sync(conn, handoff_path=handoff, today="2026-09-21")
    handoff.write_text(HANDOFF.replace("**1. Cost per gradient**",
                                       "**1. Cost per gradient, restated**"))
    sync(conn, handoff_path=handoff, today="2026-09-21")
    assert get_question(conn, "1")["title"] == "Cost per gradient, restated"


def test_ui_closure_not_in_section_seven_is_reverted_and_reported(conn, handoff):
    sync(conn, handoff_path=handoff, today="2026-09-21")
    set_question_state(conn, "1", "closed", source="ui", note="settled in the meeting",
                       on="2026-09-21", actor="ui")
    result = sync(conn, handoff_path=handoff, today="2026-09-21")
    assert get_question(conn, "1")["state"] == "open"
    assert len(result.reverted) == 1
    assert result.reverted[0]["id"] == "1"
    assert result.reverted[0]["note"] == "settled in the meeting"


def test_ui_reopen_not_in_section_seven_is_reverted_and_reported(conn, handoff):
    """M4: the mirror of the reverted closure. Section 7 says closed, the group
    reopened the item in the meeting; the tracker still wins, but the reopening
    is owed to section 7 rather than silently dropped."""
    sync(conn, handoff_path=handoff, today="2026-09-21")
    set_question_state(conn, "25", "open", source="ui", on="2026-09-21", actor="ui")
    result = sync(conn, handoff_path=handoff, today="2026-09-22")
    assert get_question(conn, "25")["state"] == "closed"
    assert [r["id"] for r in result.reopened] == ["25"]
    assert result.reopened[0]["reopened_on"] == "2026-09-21"
    assert "25" not in result.updated


def test_a_ui_reopen_leaves_a_breadcrumb_that_survives_the_sync(conn, handoff):
    sync(conn, handoff_path=handoff, today="2026-09-21")
    set_question_state(conn, "25", "open", source="ui", on="2026-09-21", actor="ui")
    sync(conn, handoff_path=handoff, today="2026-09-22")
    assert get_question(conn, "25")["reopened_on"] == "2026-09-21"


def test_closing_a_question_in_the_ui_clears_any_reopen_breadcrumb(conn, handoff):
    sync(conn, handoff_path=handoff, today="2026-09-21")
    set_question_state(conn, "25", "open", source="ui", on="2026-09-21", actor="ui")
    set_question_state(conn, "25", "closed", source="ui", note="done", on="2026-09-22",
                       actor="ui")
    assert get_question(conn, "25")["reopened_on"] is None


def test_a_user_set_difficulty_is_never_overwritten(conn, handoff):
    sync(conn, handoff_path=handoff, today="2026-09-21")
    set_question_difficulty(conn, "21", "S", source="user", actor="ui")
    sync(conn, handoff_path=handoff, today="2026-09-21")
    row = get_question(conn, "21")
    assert row["difficulty"] == "S"
    assert row["difficulty_source"] == "user"


def test_agent_estimates_difficulty_for_items_it_has_not_been_told_about(conn, handoff):
    sync(conn, handoff_path=handoff, today="2026-09-21")
    assert get_question(conn, "21")["difficulty"] == "L"
    assert get_question(conn, "21")["difficulty_source"] == "agent"
    assert get_question(conn, "2")["difficulty"] == "S"


def test_item_dropped_from_section_seven_is_flagged_not_deleted(conn, handoff):
    sync(conn, handoff_path=handoff, today="2026-09-21")
    # Removing just the item text (and not the now-empty "### Open — Tamra"
    # heading) would leave a subsection with zero items, which
    # sources.handoff._parse_items (Task 3, already committed) deliberately
    # rejects as a malformed document rather than silently dropping — so the
    # whole subsection is removed here, matching how a person would actually
    # edit HANDOFF.md when an owner's last open item disappears.
    handoff.write_text(HANDOFF.replace(
        "### Open — Tamra\n\n"
        "**21. Implement the HVA ansatz from scratch** — rebuild Cade's circuit builder in our\n"
        "codebase. raised 2026-09-14.\n\n", ""))
    result = sync(conn, handoff_path=handoff, today="2026-09-21")
    assert result.stale == ["21"]
    assert get_question(conn, "21") is not None
    assert any("21" in f["text"] for f in list_flags(conn))


def test_item_restored_to_section_seven_clears_its_stale_flag(conn, handoff):
    sync(conn, handoff_path=handoff, today="2026-09-21")
    dropped = HANDOFF.replace(
        "### Open — Tamra\n\n"
        "**21. Implement the HVA ansatz from scratch** — rebuild Cade's circuit builder in our\n"
        "codebase. raised 2026-09-14.\n\n", "")
    handoff.write_text(dropped)
    result = sync(conn, handoff_path=handoff, today="2026-09-21")
    assert result.stale == ["21"]
    assert any(f["key"] == "stale:21" for f in list_flags(conn))

    handoff.write_text(HANDOFF)
    result = sync(conn, handoff_path=handoff, today="2026-09-21")
    assert "21" not in result.stale
    assert not any(f["key"] == "stale:21" for f in list_flags(conn))
    row = get_question(conn, "21")
    assert row is not None
    assert row["state"] == "open"


def test_a_section_seven_one_flag_is_never_deleted_even_when_items_reappear(conn, handoff):
    sync(conn, handoff_path=handoff, today="2026-09-21")
    dropped = HANDOFF.replace(
        "### Open — Tamra\n\n"
        "**21. Implement the HVA ansatz from scratch** — rebuild Cade's circuit builder in our\n"
        "codebase. raised 2026-09-14.\n\n", "")
    handoff.write_text(dropped)
    sync(conn, handoff_path=handoff, today="2026-09-21")
    handoff.write_text(HANDOFF)
    sync(conn, handoff_path=handoff, today="2026-09-21")
    keys = {f["key"] for f in list_flags(conn)}
    assert flag_key(FLAG_1) in keys
    assert flag_key(FLAG_2) in keys


def test_delete_flag_on_a_missing_stale_key_is_a_noop(conn):
    delete_flag(conn, "stale:does-not-exist", actor="sync")
    assert not any(f["key"] == "stale:does-not-exist" for f in list_flags(conn))


def test_delete_flag_refuses_a_non_stale_key(conn):
    with pytest.raises(ValueError):
        delete_flag(conn, "1", actor="sync")


def test_flags_are_imported_with_their_resolved_state(conn, handoff):
    sync(conn, handoff_path=handoff, today="2026-09-21")
    flags = {f["ordinal"]: f for f in list_flags(conn) if f["ordinal"]}
    assert flags["1"]["resolved"] == 0
    assert flags["2"]["resolved"] == 1


def test_sync_proposes_agenda_items_for_unresolved_flags(conn, handoff):
    result = sync(conn, handoff_path=handoff, today="2026-09-21")
    origins = {a["origin"] for a in list_agenda(conn)}
    assert f"sync:flag:{flag_key(FLAG_1)}" in origins
    assert f"sync:flag:{flag_key(FLAG_2)}" not in origins
    assert f"sync:flag:{flag_key(FLAG_1)}" in result.agenda_proposed


def test_agenda_proposals_are_not_duplicated_on_a_second_sync(conn, handoff):
    sync(conn, handoff_path=handoff, today="2026-09-21")
    sync(conn, handoff_path=handoff, today="2026-09-21")
    origins = [a["origin"] for a in list_agenda(conn)]
    assert origins.count(f"sync:flag:{flag_key(FLAG_1)}") == 1


def test_inserting_a_flag_does_not_re_target_the_ones_below_it(conn, handoff):
    """M9: an ordinary hand-edit to §7.1 renumbers every flag below the insert."""
    sync(conn, handoff_path=handoff, today="2026-09-21")
    first_seen = {f["key"]: f["first_seen"] for f in list_flags(conn)}
    handoff.write_text(HANDOFF.replace(
        "1. **Ten clusters or fourteen?** Someone has to say which set the paper shows.\n",
        "1. **Ten clusters or fourteen?** Someone has to say which set the paper shows.\n"
        "2. **Inserted mid-list.** Nobody has settled it.\n",
    ).replace("2. ~~**Item 20's standard", "3. ~~**Item 20's standard"))
    sync(conn, handoff_path=handoff, today="2026-09-28")

    rows = {f["key"]: f for f in list_flags(conn)}
    # the old flags keep their keys, their text and their first_seen date
    assert rows[flag_key(FLAG_1)]["first_seen"] == first_seen[flag_key(FLAG_1)]
    assert "Ten clusters" in rows[flag_key(FLAG_1)]["text"]
    assert rows[flag_key(FLAG_1)]["ordinal"] == "1"
    assert rows[flag_key(FLAG_2)]["ordinal"] == "3"
    # and the genuinely new one is proposed, dated today, not backdated
    inserted = [f for f in list_flags(conn) if "Inserted mid-list" in f["text"]][0]
    assert inserted["first_seen"] == "2026-09-28"
    assert f"sync:flag:{inserted['key']}" in {a["origin"] for a in list_agenda(conn)}


def test_legacy_numeric_flag_keys_are_migrated_without_duplicating_anything(conn, handoff):
    """A store written before M9 keys flags '1', '2' and its agenda origins
    'sync:flag:1'. Both must land on the hashed key, once."""
    upsert_flag(conn, key="1", text=FLAG_1, first_seen="2026-09-01", resolved=0)
    aid = add_agenda(conn, title="Curated title", origin="sync:flag:1",
                     proposed_by="sync", status="accepted")

    sync(conn, handoff_path=handoff, today="2026-09-21")

    keys = [f["key"] for f in list_flags(conn)]
    assert keys.count(flag_key(FLAG_1)) == 1
    assert "1" not in keys
    row = [f for f in list_flags(conn) if f["key"] == flag_key(FLAG_1)][0]
    assert row["first_seen"] == "2026-09-01", "a migrated flag is not newly seen"

    origins = [a["origin"] for a in list_agenda(conn)]
    assert origins.count(f"sync:flag:{flag_key(FLAG_1)}") == 1
    assert "sync:flag:1" not in origins
    moved = [a for a in list_agenda(conn) if a["id"] == aid][0]
    assert moved["status"] == "accepted" and moved["title"] == "Curated title"


def test_a_reworded_headline_still_migrates_the_legacy_row_exactly_once(conn, handoff):
    """N1: the legacy key *is* the §7.1 ordinal, so that is the join.

    Hashing the row's own stored text assumes nobody edited the headline since
    the last sync under the old code. On that ordinary weekly edit the legacy
    row would land on a hash §7.1 no longer produces, the real flag would be
    inserted under its own hash, and the orphan would be permanent — nothing in
    this codebase can delete a non-`stale:` flag.
    """
    upsert_flag(conn, key="1", text=FLAG_1, first_seen="2026-09-01", resolved=0)
    aid = add_agenda(conn, title="Curated title", origin="sync:flag:1",
                     proposed_by="sync", status="accepted")
    reworded = ("**Ten clusters, fourteen, or some other set entirely?** Someone has to "
                "say which set the paper shows.")
    handoff.write_text(HANDOFF.replace(FLAG_1, reworded))

    sync(conn, handoff_path=handoff, today="2026-09-21")

    rows = [f for f in list_flags(conn) if "clusters" in f["text"]]
    assert len(rows) == 1, "a reworded headline must not leave an undeletable orphan"
    assert rows[0]["key"] == flag_key(reworded)
    assert rows[0]["text"] == reworded
    assert rows[0]["first_seen"] == "2026-09-01", "the disagreement is not newly seen"
    assert rows[0]["ordinal"] == "1"

    origins = [a["origin"] for a in list_agenda(conn)]
    assert origins.count(f"sync:flag:{flag_key(reworded)}") == 1
    assert "sync:flag:1" not in origins
    assert [a for a in list_agenda(conn) if a["id"] == aid][0]["title"] == "Curated title"


def test_a_legacy_flag_whose_ordinal_is_gone_is_left_alone(conn, handoff):
    """Nothing to join it to: leave it visible rather than hide it under a hash
    that §7.1 will never produce."""
    upsert_flag(conn, key="9", text="**Something §7.1 no longer lists.**",
                first_seen="2026-09-01", resolved=0)
    sync(conn, handoff_path=handoff, today="2026-09-21")
    assert "9" in {f["key"] for f in list_flags(conn)}


def test_sync_never_touches_an_accepted_agenda_item(conn, handoff):
    sync(conn, handoff_path=handoff, today="2026-09-21")
    aid = [a["id"] for a in list_agenda(conn)
           if a["origin"] == f"sync:flag:{flag_key(FLAG_1)}"][0]
    update_agenda(conn, aid, status="accepted", title="Curated title")
    sync(conn, handoff_path=handoff, today="2026-09-21")
    row = [a for a in list_agenda(conn) if a["id"] == aid][0]
    assert row["status"] == "accepted"
    assert row["title"] == "Curated title"


def test_sync_never_removes_a_decision(conn, handoff):
    sync(conn, handoff_path=handoff, today="2026-09-21")
    aid = add_agenda(conn, title="Settle it", status="accepted")
    close_agenda(conn, aid, resolution="Settled", resolved_by="Eun-Ah",
                 resolved_on="2026-09-21")
    sync(conn, handoff_path=handoff, today="2026-09-21")
    assert len(list_decisions(conn)) == 1


def test_sync_writes_the_json_export_when_given_a_path(conn, handoff, tmp_path):
    out = tmp_path / "dashboard.json"
    sync(conn, handoff_path=handoff, json_path=out, today="2026-09-21")
    assert out.exists()
    assert '"questions"' in out.read_text()


def test_estimate_difficulty_reads_the_verbs():
    assert estimate_difficulty("rerun at low dimension with a tighter tolerance") == "S"
    assert estimate_difficulty("write the answer into paragraph 17") == "S"
    assert estimate_difficulty("implement the HVA ansatz from scratch") == "L"
    assert estimate_difficulty("rebuild Cade's circuit builder in our codebase") == "L"
    assert estimate_difficulty("decide whether the caption is right") == "M"
