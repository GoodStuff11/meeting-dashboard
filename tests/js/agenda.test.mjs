/* B2: an agenda resolution must never be unsaved state. */

import assert from "node:assert/strict";
import test from "node:test";

import { board } from "./board.mjs";
import { button, fields, start } from "./harness.mjs";

function agendaFields(h) {
  const textareas = fields(h.roots.agenda, "textarea");
  const inputs = fields(h.roots.agenda, "input");
  return { resolution: textareas[0], followups: inputs[0] };
}

test("typing a resolution saves it, debounced, without waiting for Close", async () => {
  const h = await start(board());
  const { resolution } = agendaFields(h);

  await resolution.type("Ten, as in Figs. 2-4");
  assert.equal(h.calls("PATCH").length, 0, "a save on every keystroke would be a write storm");

  await h.settle(600);
  const saves = h.calls("PATCH", "/api/agenda/1");
  assert.equal(saves.length, 1);
  assert.equal(saves[0].body.resolution, "Ten, as in Figs. 2-4");
});

test("blurring a field saves it immediately", async () => {
  const h = await start(board());
  const { followups } = agendaFields(h);

  followups.value = "Eun-Ah";
  await followups.blur();
  await h.settle();

  const saves = h.calls("PATCH", "/api/agenda/1");
  assert.equal(saves.length, 1);
  assert.deepEqual(saves[0].body.followups, ["Eun-Ah"]);
});

test("a save does not re-render the board under the typist", async () => {
  const h = await start(board());
  const loadsBefore = h.calls("GET", "/api/state").length;
  const { resolution } = agendaFields(h);

  await resolution.type("half a thought");
  await h.settle(600);

  assert.equal(h.calls("GET", "/api/state").length, loadsBefore,
    "a blur-triggered save that re-renders steals focus from the next field");
});

test("follow-ups are saved as a list, not a string", async () => {
  const h = await start(board());
  const { followups } = agendaFields(h);

  followups.value = "Jonathon, Tamra";
  await followups.blur();
  await h.settle();

  assert.deepEqual(h.calls("PATCH", "/api/agenda/1")[0].body.followups,
    ["Jonathon", "Tamra"]);
});

test("both remaining fields are pre-filled from the store", async () => {
  const b = board();
  b.agenda[0].resolution = "Ten, as in Figs. 2-4";
  b.agenda[0].followups = ["Jonathon"];
  const h = await start(b);
  const { resolution, followups } = agendaFields(h);

  assert.equal(resolution.value, "Ten, as in Figs. 2-4");
  assert.equal(followups.value, "Jonathon");
});

test("there is no resolved-by input on an agenda card", async () => {
  const h = await start(board());
  const resolvedBy = fields(h.roots.agenda, "input")
    .filter((n) => (n.getAttribute("placeholder") || "") === "Resolved by");
  assert.equal(resolvedBy.length, 0, "\"Resolved by\" was removed entirely");
});

test("an unrelated action does not wipe a resolution being typed", async () => {
  const h = await start(board());
  await agendaFields(h).resolution.type("half a thought, mid-meeting");

  // Somebody accepts a proposed item. mutate() reloads and replaceChildren()s
  // the whole agenda section.
  await button(h.roots.agenda, "Accept").fire("click");
  await h.settle();

  assert.equal(agendaFields(h).resolution.value, "half a thought, mid-meeting");
});

test("closing an item sends what is on screen", async () => {
  const h = await start(board());
  const { resolution, followups } = agendaFields(h);
  await resolution.type("Ten, as in Figs. 2-4");
  followups.value = "Jonathon";

  await button(h.roots.agenda, "Close → Decisions").fire("click");
  await h.settle();

  const closes = h.calls("POST", "/api/agenda/1/close");
  assert.equal(closes.length, 1);
  assert.equal(closes[0].body.resolution, "Ten, as in Figs. 2-4");
  assert.equal(closes[0].body.resolved_by, undefined,
    "resolved_by is no longer sent by the UI at all");
  assert.deepEqual(closes[0].body.followups, ["Jonathon"]);
});

test("closing an item does not leave a queued save to fire at a closed row", async () => {
  const h = await start(board());
  await agendaFields(h).resolution.type("Ten, as in Figs. 2-4");
  await button(h.roots.agenda, "Close → Decisions").fire("click");
  await h.settle();
  const after = h.calls("PATCH", "/api/agenda/1").length;

  await h.settle(2000);
  assert.equal(h.calls("PATCH", "/api/agenda/1").length, after);
});

test("adding an agenda item by hand sends its description as detail", async () => {
  const h = await start(board());
  const title = fields(h.roots.agenda, "input").pop(); // the add-form's title input
  const detail = fields(h.roots.agenda, "textarea").pop(); // the add-form's textarea

  title.value = "Check the §7 rendering with Jonathon";
  detail.value = "Show him the rendered math before the meeting.";
  await button(h.roots.agenda, "Add").fire("click");
  await h.settle();

  const posts = h.calls("POST", "/api/agenda");
  assert.equal(posts.length, 1);
  assert.equal(posts[0].body.title, "Check the §7 rendering with Jonathon");
  assert.equal(posts[0].body.detail, "Show him the rendered math before the meeting.");
});

test("the add-form clears both fields after a successful add", async () => {
  const h = await start(board());
  const title = fields(h.roots.agenda, "input").pop();
  const detail = fields(h.roots.agenda, "textarea").pop();

  title.value = "Another action item";
  detail.value = "Some description";
  await button(h.roots.agenda, "Add").fire("click");
  await h.settle();

  // A successful add reloads the board, which rebuilds the add-form fresh —
  // either way, what's on screen afterwards must be blank, not carried over.
  const freshTitle = fields(h.roots.agenda, "input").pop();
  const freshDetail = fields(h.roots.agenda, "textarea").pop();
  assert.equal(freshTitle.value, "");
  assert.equal(freshDetail.value, "");
});

test("no agenda card shows the sync origin key as a tag", async () => {
  const h = await start(board());
  const text = h.roots.agenda.textContent;
  assert.doesNotMatch(text, /sync:flag/,
    "origin is kept in the data but must not be rendered");
});

/* An accepted agenda item had no way off the board except Close, which mints a
 * decision — so a mistyped row could only be removed by recording something
 * false. Remove dismisses it instead, reusing the state proposals already use. */

test("an accepted agenda item can be removed without minting a decision", async () => {
  const h = await start(board());
  const remove = button(h.roots.agenda, "Remove");
  assert.ok(remove, "accepted agenda items need a Remove control");

  await remove.fire("click");

  const patches = h.calls("PATCH", "/api/agenda/1");
  assert.equal(patches.length, 1);
  assert.equal(patches[0].body.status, "dismissed");
  assert.equal(h.calls("POST", "/api/agenda/1/close").length, 0,
    "Remove must not close the item — closing is what creates a decision");
});

test("removing an item drops its queued draft save", async () => {
  const h = await start(board());
  const resolution = fields(h.roots.agenda, "textarea")[0];

  await resolution.type("half-typed");
  await button(h.roots.agenda, "Remove").fire("click");
  await h.settle(600);

  const writes = h.calls("PATCH", "/api/agenda/1");
  assert.equal(writes.length, 1, "the debounced save must not land after the dismissal");
  assert.equal(writes[0].body.status, "dismissed");
});
