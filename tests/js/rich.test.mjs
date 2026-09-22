/* Item 1: renderRich() covers a closed, hand-measured subset of the ledger's
 * $inline math$, **bold** and `code` -- not general LaTeX/markdown. These
 * tests exercise the real examples HANDOFF §7 actually contains, plus the
 * degrade-to-plain-text guarantees for input outside that subset. */

import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

import { board } from "./board.mjs";
import { find, start } from "./harness.mjs";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const APP_JS_SOURCE = fs.readFileSync(
  path.resolve(HERE, "../../project_tracker/static/app.js"), "utf8");

function rich(h, text) {
  return h.context.renderRich(text);
}

const THIN = " "; // THIN SPACE, used to pad named operators/relations

test("no innerHTML anywhere in app.js", () => {
  assert.doesNotMatch(APP_JS_SOURCE, /innerHTML/,
    "the XSS safety here is structural: textContent/createTextNode only");
});

test("$(L,n_\\uparrow,n_\\downarrow,U)$ renders both arrows as subscripts", async () => {
  const h = await start(board());
  const frag = rich(h, "$(L,n_\\uparrow,n_\\downarrow,U)$");
  const subs = find(frag, (n) => n.tagName === "sub");
  assert.equal(subs.length, 2);
  assert.equal(subs[0].textContent, "↑");
  assert.equal(subs[1].textContent, "↓");
  assert.equal(frag.textContent, "(L,n↑,n↓,U)");
});

test("$\\mathbf k$ bolds a single letter", async () => {
  const h = await start(board());
  const frag = rich(h, "$\\mathbf k$");
  const strong = find(frag, (n) => n.tagName === "strong");
  assert.equal(strong.length, 1);
  assert.equal(strong[0].textContent, "k");
  assert.equal(frag.textContent, "k");
});

test("$4\\times3$ renders the multiplication sign", async () => {
  const h = await start(board());
  assert.equal(rich(h, "$4\\times3$").textContent, "4×3");
});

test("$2n_{df}+5$ renders a braced subscript and leaves + untouched", async () => {
  // + is a binary *operator*, not a relation — TeX gives it narrower spacing
  // than =/\le/\ge, and the relation-padding rule must not widen to cover it.
  const h = await start(board());
  const frag = rich(h, "$2n_{df}+5$");
  const subs = find(frag, (n) => n.tagName === "sub");
  assert.equal(subs.length, 1);
  assert.equal(subs[0].textContent, "df");
  assert.equal(frag.textContent, "2ndf+5");
});

test("$O(N^{1.5})$ renders a braced superscript", async () => {
  const h = await start(board());
  const frag = rich(h, "$O(N^{1.5})$");
  const sups = find(frag, (n) => n.tagName === "sup");
  assert.equal(sups.length, 1);
  assert.equal(sups[0].textContent, "1.5");
  assert.equal(frag.textContent, "O(N1.5)");
});

test("$O(\\sqrt N)$ renders the radical sign", async () => {
  const h = await start(board());
  assert.equal(rich(h, "$O(\\sqrt N)$").textContent, "O(√N)");
});

test("$O(N\\log N)$ keeps log upright, drops the backslash, and pads it", async () => {
  // \log is a named operator: LaTeX sets it upright *and* with a thin space
  // on each side, which is what tells "N log N" apart from a run-together
  // "NlogN". The source space after \log is a LaTeX command terminator (it's
  // swallowed), so without this padding the rendering collapses solid.
  const h = await start(board());
  assert.equal(rich(h, "$O(N\\log N)$").textContent, `O(N${THIN}log${THIN}N)`);
});

test("$n_{df}\\le24$ renders a braced subscript then a padded ≤ sign", async () => {
  const h = await start(board());
  const frag = rich(h, "$n_{df}\\le24$");
  const subs = find(frag, (n) => n.tagName === "sub");
  assert.equal(subs.length, 1);
  assert.equal(subs[0].textContent, "df");
  assert.equal(frag.textContent, `ndf${THIN}≤${THIN}24`);
});

test("$3\\times10^4$ renders a single-character superscript", async () => {
  const h = await start(board());
  const frag = rich(h, "$3\\times10^4$");
  const sups = find(frag, (n) => n.tagName === "sup");
  assert.equal(sups.length, 1);
  assert.equal(sups[0].textContent, "4");
  assert.equal(frag.textContent, "3×104");
});

test("$\\dim\\mathcal H\\ge392$ pads both \\dim and \\ge, not just one", async () => {
  // \dim is a named operator (padded); \ge is a relation used infix here
  // (also padded) — without both, "dim ℋ≥392" would still read as wrong as
  // the original "dimℋ≥392" did.
  const h = await start(board());
  assert.equal(rich(h, "$\\dim\\mathcal H\\ge392$").textContent,
    `dim${THIN}ℋ${THIN}≥${THIN}392`);
});

test("$\\dim\\mathcal H=50$ pads \\dim, mathcal H, and the bare = too", async () => {
  // "=" is typed directly in the source, not a backslash command, but in TeX
  // it's a relation in the same class as \le/\ge and gets the same padding —
  // the compiled manuscript these three actually read already sets "U = 8"
  // for $U=8$, so the padded rendering is the faithful one, not the tight one.
  const h = await start(board());
  assert.equal(rich(h, "$\\dim\\mathcal H=50$").textContent,
    `dim${THIN}ℋ${THIN}=${THIN}50`);
});

test("$10^{-13}$ renders a negative-exponent superscript", async () => {
  const h = await start(board());
  const frag = rich(h, "$10^{-13}$");
  const sups = find(frag, (n) => n.tagName === "sup");
  assert.equal(sups.length, 1);
  assert.equal(sups[0].textContent, "-13");
  assert.equal(frag.textContent, "10-13");
});

test("$U=8$ pads the = relation, matching the compiled manuscript", async () => {
  const h = await start(board());
  assert.equal(rich(h, "$U=8$").textContent, `U${THIN}=${THIN}8`);
});

test("$S^z$ renders a single-character superscript", async () => {
  const h = await start(board());
  const frag = rich(h, "$S^z$");
  const sups = find(frag, (n) => n.tagName === "sup");
  assert.equal(sups.length, 1);
  assert.equal(sups[0].textContent, "z");
  assert.equal(frag.textContent, "Sz");
});

test("an unmatched $ is literal, not swallowed", async () => {
  const h = await start(board());
  assert.equal(rich(h, "the ledger costs $5 total").textContent,
    "the ledger costs $5 total");
});

test("an unrecognised \\command loses its backslash but keeps the word", async () => {
  const h = await start(board());
  assert.equal(rich(h, "$\\foobar$").textContent, "foobar");
});

test("**bold** becomes a <strong>", async () => {
  const h = await start(board());
  const frag = rich(h, "This is **important**, noted.");
  const strong = find(frag, (n) => n.tagName === "strong");
  assert.equal(strong.length, 1);
  assert.equal(strong[0].textContent, "important");
  assert.equal(frag.textContent, "This is important, noted.");
});

test("`code` becomes a <code>", async () => {
  const h = await start(board());
  const frag = rich(h, "keyed by `origin`, not id");
  const code = find(frag, (n) => n.tagName === "code");
  assert.equal(code.length, 1);
  assert.equal(code[0].textContent, "origin");
  assert.equal(frag.textContent, "keyed by origin, not id");
});

test("odd nested markup degrades to plain text instead of throwing", async () => {
  const h = await start(board());
  assert.doesNotThrow(() => rich(h, "**unclosed bold $also unclosed `and code"));
  assert.doesNotThrow(() => rich(h, "$$$$$$"));
  assert.doesNotThrow(() => rich(h, "\\mathbf\\mathrm\\mathcal"));
});

test("a stray \\command surviving outside $...$ stays literal in prose", async () => {
  // Zero backslash-command sequences occur outside $...$ anywhere in the real
  // ledger; mangling ordinary prose on the strength of a backslash character
  // would be worse than the (nonexistent) case this would theoretically fix.
  const h = await start(board());
  assert.equal(rich(h, "a path like C:\\dim\\log on Windows").textContent,
    "a path like C:\\dim\\log on Windows");
});

test("$\\sim10^{-13}$ stays tight: \\sim is a unary prefix here, not a padded relation", async () => {
  const h = await start(board());
  const frag = rich(h, "$\\sim10^{-13}$");
  const sups = find(frag, (n) => n.tagName === "sup");
  assert.equal(sups.length, 1);
  assert.equal(sups[0].textContent, "-13");
  // Pinned: no leading space (start of span) and no trailing space either —
  // \sim is not in the padded set at all, unlike \le/\ge/=, so a later
  // change to relation spacing must not silently start padding this prefix
  // use.
  assert.equal(frag.textContent, "∼10-13");
});

test("$|g|\\sim10^{-3}$ also keeps \\sim tight, mid-expression", async () => {
  // A second real usage, not just the start-of-span case above: \sim reads
  // as "about" between |g| and the estimate, still a unary-flavoured prefix
  // rather than an infix relation, so it stays unpadded here too.
  const h = await start(board());
  const frag = rich(h, "$|g|\\sim10^{-3}$");
  const sups = find(frag, (n) => n.tagName === "sup");
  assert.equal(sups.length, 1);
  assert.equal(sups[0].textContent, "-3");
  assert.equal(frag.textContent, "|g|∼10-3");
});

test("a padded operator at the very start or end of a span gets no outer space", async () => {
  const h = await start(board());
  assert.equal(rich(h, "$\\log$").textContent, "log",
    "nothing precedes or follows it, so no space either side");
});

test("two adjacent padded operators get exactly one space between them, not two", async () => {
  const h = await start(board());
  assert.equal(rich(h, "$\\dim\\log$").textContent, `dim${THIN}log`);
});
