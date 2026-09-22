/* S-prompt, M7b, S10 — the open-questions column. */

import assert from "node:assert/strict";
import test from "node:test";

import { board } from "./board.mjs";
import { button, buttons, fields, find, start } from "./harness.mjs";

test("closing a question uses an inline note, not a blocking dialog", async () => {
  // `window` and `prompt` are absent from the harness context on purpose: a
  // browser with dialogs suppressed makes window.prompt() return undefined and
  // the Close button inert, with no error shown and the §7 note lost.
  const h = await start(board());
  const note = fields(h.roots.questions, "textarea")[0];
  assert.ok(note, "an open question needs a visible note field");

  await note.type("settled in the meeting");
  await button(h.roots.questions, "Close").fire("click");
  await h.settle();

  const closes = h.calls("POST", "/api/questions/14/state");
  assert.equal(closes.length, 1);
  assert.equal(closes[0].body.state, "closed");
  assert.equal(closes[0].body.note, "settled in the meeting");
});

test("a half-typed closing note survives an unrelated re-render", async () => {
  const h = await start(board());
  await fields(h.roots.questions, "textarea")[0].type("settled in the me");

  await buttons(h.roots.questions, "Reopen")[0].fire("click");
  await h.settle();

  assert.equal(fields(h.roots.questions, "textarea")[0].value, "settled in the me");
});

test("a failed close keeps the note that is still on screen", async () => {
  const h = await start(board());
  await fields(h.roots.questions, "textarea")[0].type("settled in the meeting");

  h.replies = [{ ok: false, status: 500, error: "the server fell over" }];
  await button(h.roots.questions, "Close").fire("click");
  await h.settle();
  assert.match(h.roots.error.textContent, /fell over/);

  // Whatever the person does next re-renders the card. The note must come back.
  await buttons(h.roots.questions, "Reopen")[0].fire("click");
  await h.settle();
  assert.equal(fields(h.roots.questions, "textarea")[0].value, "settled in the meeting");
});

test("the staleness badge is hidden while no meetings are recorded", async () => {
  const h = await start(board());
  assert.equal(find(h.roots.questions, (n) => n.className === "heat").length, 0,
    "a counter frozen at 0 mtg reads as 'nothing is stale'");
});

test("the staleness badge appears once meetings are on record", async () => {
  const b = board();
  b.meta.meetings = [{ date: "2026-09-14", label: "" }, { date: "2026-09-21", label: "" }];
  b.questions[0].staleness = 2;
  const h = await start(b);

  const heat = find(h.roots.questions, (n) => n.className === "heat");
  assert.equal(heat.length, 1);
  assert.match(heat[0].textContent, /2 mtg/);
});

test("the blank difficulty option offers the agent's estimate, not a blank", async () => {
  const h = await start(board());
  const blank = find(h.roots.questions,
    (n) => n.tagName === "option" && n.getAttribute("value") === "")[0];
  assert.ok(blank, "the blank option should still exist");
  assert.match(blank.textContent.toLowerCase(), /estimate/);
});

test("the difficulty select shows full words but keeps S/M/L/null on the wire", async () => {
  const h = await start(board());
  const options = find(h.roots.questions, (n) => n.tagName === "option");
  const byValue = Object.fromEntries(
    options.map((o) => [o.getAttribute("value"), o.textContent]));

  assert.equal(byValue.S, "Small");
  assert.equal(byValue.M, "Medium");
  assert.equal(byValue.L, "Large");
  assert.deepEqual(Object.keys(byValue).sort(), ["", "L", "M", "S"]);

  const select = find(h.roots.questions, (n) => n.tagName === "select")[0];
  await select.fire("change", { target: { value: "" } });
  await h.settle();
  const patches = h.calls("POST", "/api/questions/14/difficulty");
  assert.equal(patches[0].body.difficulty, null);
});

test("the difficulty select is labelled, not bare", async () => {
  const h = await start(board());
  assert.match(h.roots.questions.textContent, /Estimated difficulty/);
});

test("the headings read 'Open questions' and 'Closed questions'", async () => {
  const h = await start(board());
  const headings = find(h.roots.questions, (n) => n.tagName === "h2").map((n) => n.textContent);
  assert.ok(headings.some((t) => /^Open questions — \d+$/.test(t)), headings.join(" | "));
  assert.ok(headings.some((t) => /^Closed questions — \d+$/.test(t)), headings.join(" | "));
});

test("flags are rendered after both question groups, not before", async () => {
  const h = await start(board());
  const headings = find(h.roots.questions, (n) => n.tagName === "h2").map((n) => n.textContent);
  const flagsIndex = headings.findIndex((t) => /^Flags/.test(t));
  const closedIndex = headings.findIndex((t) => /^Closed questions/.test(t));
  assert.ok(flagsIndex > -1 && closedIndex > -1);
  assert.ok(flagsIndex > closedIndex, "flags should follow the closed-questions heading");
});

test("tags read 'Assignee: X' and 'Priority: X', not the bare value", async () => {
  const h = await start(board());
  const tags = find(h.roots.questions, (n) => n.className === "tag").map((n) => n.textContent);
  assert.ok(tags.includes("Assignee: Jonathon"));
  assert.ok(tags.includes("Priority: high"));
});

test("a question's title and why render §7 rich text, not raw markup", async () => {
  const b = board();
  b.questions[0].title = "How two-body is a $4\\times4$ Hubbard eigenstate?";
  b.questions[0].why = "See `origin` and **the note**.";
  const h = await start(b);

  const text = h.roots.questions.textContent;
  assert.match(text, /How two-body is a 4×4 Hubbard eigenstate\?/);
  assert.doesNotMatch(text, /\$4\\times4\$/);
  assert.ok(find(h.roots.questions, (n) => n.tagName === "code").length >= 1);
  assert.ok(find(h.roots.questions, (n) => n.tagName === "strong").length >= 1);
});

/* The raised date carries margin-left:auto, so it only sits at the end of the
 * meta row while it is the last child. Appending anything after it — the
 * difficulty control, as it used to be — pushes that control past the date
 * instead, which is what it looked like on screen. */

test("the raised date is the last thing in its meta row", async () => {
  const h = await start(board());
  const rows = find(h.roots.questions, (n) => n.className === "meta");
  assert.ok(rows.length, "expected meta rows on the question cards");

  // Compare positions, not the nodes themselves: these carry parentNode
  // back-references, and a failed assert.equal on two of them sends the test
  // runner's diff into a cyclic structure instead of printing a failure.
  for (const row of rows) {
    const at = row.children.findIndex((c) => c.className === "raised");
    if (at === -1) continue;
    assert.equal(at, row.children.length - 1,
      "margin-left:auto only right-aligns the date while nothing follows it");
  }
});

test("a closed question spells its difficulty out rather than showing a bare letter", async () => {
  const h = await start(board());
  const text = h.roots.questions.textContent;

  assert.match(text, /Estimated difficulty: Small/,
    "the closed fixture question is difficulty S — a bare 'S' means nothing to a reader");

  const bare = find(h.roots.questions, (n) => ["S", "M", "L"].includes(n.textContent.trim()));
  assert.equal(bare.length, 0,
    "no element should render a difficulty as a bare single letter");
});
