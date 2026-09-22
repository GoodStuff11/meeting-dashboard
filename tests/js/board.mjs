/* A board with one of everything, shaped exactly like /api/state. */

export function board(overrides = {}) {
  return {
    meta: { last_sync: "2026-09-21", last_clickup_pull: null, meetings: [], ...overrides.meta },
    questions: overrides.questions || [
      {
        id: "14", title: "HVA at strong coupling on our cluster",
        why: "Decides the venue.", owner: "Jonathon", priority: "high",
        raised: "2026-09-14", state: "open", state_source: "tracker",
        difficulty: "L", difficulty_source: "agent", closed_on: null,
        closed_note: null, reopened_on: null, clickup_status: null, due: null,
        staleness: 0,
      },
      {
        id: "25", title: "The certified data ledger is stale", why: "",
        owner: "", priority: "", raised: "2026-09-20", state: "closed",
        state_source: "tracker", difficulty: "S", difficulty_source: "agent",
        closed_on: "2026-09-21", closed_note: "regenerated", reopened_on: null,
        clickup_status: null, due: null, staleness: 0,
      },
    ],
    agenda: overrides.agenda || [
      {
        id: 1, title: "Ten clusters or fourteen?", detail: "Item 7 asks for ten.",
        origin: "sync:flag:aaaaaaaaaa", proposed_by: "sync", created: "2026-09-21",
        sort_order: 0, status: "accepted", resolution: "", followups: [],
        resolved_on: null, resolved_by: "",
      },
      {
        id: 2, title: "Who owns updating this file?", detail: "Eun-Ah or Jonathon.",
        origin: "sync:flag:bbbbbbbbbb", proposed_by: "sync", created: "2026-09-21",
        sort_order: 1, status: "proposed", resolution: "", followups: [],
        resolved_on: null, resolved_by: "",
      },
      {
        id: 3, title: "A candidate somebody dismissed", detail: "Still recoverable.",
        origin: "sync:flag:cccccccccc", proposed_by: "sync", created: "2026-09-21",
        sort_order: 2, status: "dismissed", resolution: "", followups: [],
        resolved_on: null, resolved_by: "",
      },
    ],
    decisions: overrides.decisions || [],
    flags: overrides.flags || [
      {
        key: "aaaaaaaaaa", ordinal: "1", first_seen: "2026-09-21", resolved: 0,
        text: "**The HVA work has no off-machine copy.** The implementation that "
          + "decides the venue exists on one disk.",
      },
      {
        key: "zzzzzzzzzz", ordinal: "2", first_seen: "2026-09-14", resolved: 1,
        text: "~~**Item 20 is closed but its standard is not met.**~~ RESOLVED "
          + "2026-09-21: fig4.csv regenerated.",
      },
    ],
  };
}
