/* M8 — §7.1 flags are listed, and a dismissed proposal is recoverable. */

import assert from "node:assert/strict";
import test from "node:test";

import { board } from "./board.mjs";
import { button, find, start } from "./harness.mjs";

test("every §7.1 flag is listed, with its text and when it was first seen", async () => {
  const h = await start(board());
  const text = h.roots.questions.textContent;

  assert.match(text, /The HVA work has no off-machine copy/,
    "the spec's guarantee is that flags are listed, not merely counted");
  assert.match(text, /decides the venue exists on one disk/);
  assert.match(text, /2026-09-21/);
});

test("a resolved flag is de-emphasised rather than hidden", async () => {
  const h = await start(board());
  const text = h.roots.questions.textContent;

  assert.match(text, /Item 20 is closed but its standard is not met/);
  const muted = find(h.roots.questions, (n) => /resolved/.test(n.className || ""));
  assert.ok(muted.length, "a resolved flag should be visibly de-emphasised");
});

test("a dismissed proposal is still on screen, with a way back", async () => {
  const h = await start(board());
  const text = h.roots.agenda.textContent;
  assert.match(text, /A candidate somebody dismissed/,
    "sync will never re-propose it, so hiding it destroys it");

  await button(h.roots.agenda, "Restore").fire("click");
  await h.settle();

  const patches = h.calls("PATCH", "/api/agenda/3");
  assert.equal(patches.length, 1);
  assert.equal(patches[0].body.status, "proposed");
});

test("dismissed proposals do not crowd the live agenda", async () => {
  const h = await start(board());
  const dismissedGroup = find(h.roots.agenda, (n) => /dismissed/.test(n.className || ""));
  assert.ok(dismissedGroup.length, "they belong in their own muted, collapsed group");
});
