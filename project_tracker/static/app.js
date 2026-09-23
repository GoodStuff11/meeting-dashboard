"use strict";

/* The board. Three sections, one data load, and no save button anywhere.
 *
 * Two rules hold this file together, both of them about not losing work typed
 * during a meeting:
 *
 * 1. Anything typed is persisted on its own, debounced while typing and
 *    immediately on blur — not held in the DOM until some other button is
 *    pressed. Every mutation that changes the board reloads it, and a reload
 *    replaceChildren()s these sections, so a field whose only copy was on
 *    screen is a field that the next unrelated click destroys.
 * 2. A save never reloads the board. Re-rendering under someone's hands moves
 *    focus out of the field they are about to type in.
 *
 * `drafts` covers the gap between the two: the value typed since the last
 * successful save, so a re-render that lands mid-sentence puts the sentence
 * back. It is deliberately in memory only — the durable copy is the store's.
 *
 * One field has no durable copy: a question's closing note, which has no route
 * and no column to be saved to until Close is pressed. It is drafted like the
 * rest, so it survives a re-render and a failed close, but it does not survive
 * a reload of the tab. Whether it should is the group's call, not this file's;
 * until they make it, the README says so plainly rather than implying it is
 * safe.
 *
 * Agenda status: the store's enum is proposed | accepted | closed. This file
 * adds a fourth, "dismissed", for a sync proposal the group does not want on
 * the agenda. It is deliberate and not in the design spec: sync keys proposals
 * by origin and will never re-propose one it has already made, so a dismissed
 * row that is merely filtered out of the UI is destroyed with no way back.
 * Dismissed rows are therefore rendered, muted, with a Restore button.
 */

const PRIORITY_RANK = { high: 0, urgent: 0, normal: 1, medium: 1, "": 2, low: 3 };
const DIFFICULTY_RANK = { S: 0, M: 1, L: 2, null: 3 };
const HEAT = ["var(--heat-0)", "var(--heat-1)", "var(--heat-2)", "var(--heat-3)"];
const SAVE_DEBOUNCE_MS = 500;

let state = null;
const drafts = new Map();
const timers = new Map();

function el(tag, attrs = {}, children = []) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === "class") node.className = v;
    else if (k === "text") node.textContent = v;
    else if (k.startsWith("on")) node.addEventListener(k.slice(2), v);
    else if (v !== null && v !== undefined) node.setAttribute(k, v);
  }
  for (const c of [].concat(children)) if (c) node.appendChild(c);
  return node;
}

/* ---- §7 rich text: a closed, hand-measured subset of $inline math$,
 * **bold** and `code`, rendered with createElement/textContent/createTextNode
 * only — never by assigning markup to an element's HTML wholesale. Nothing
 * here throws: odd or unmatched input degrades to literal text instead. See
 * HANDOFF §7 for the source of truth on what actually appears in the ledger. */

// Zero-argument math commands: a straight substitution of the command token
// (backslash absorbs one trailing "command-terminator" space, same as LaTeX).
const MATH_SYMBOLS = {
  times: "×", le: "≤", ge: "≥", sim: "∼", sqrt: "√",
  langle: "⟨", rangle: "⟩", uparrow: "↑", downarrow: "↓",
  log: "log", dim: "dim", SU: "SU",
};
// One-argument math commands: consume the following {...} group, a single
// backslash-command, or a single plain character as their argument.
const MATH_ARG_COMMANDS = new Set(["mathbf", "mathrm", "mathcal"]);

// Named operators (\log, \dim) and the relations we've actually seen used
// infix (\le, \ge) are set upright *and* padded — that padding is what
// distinguishes "dim ℋ" from what would otherwise read as a variable product
// "dimℋ". The bare "=" character gets the same padding (it's a relation in
// TeX too, and $U=8$ already typesets as "U = 8" in the compiled manuscript)
// but is handled separately below, since it's typed literally rather than as
// a backslash command. \times and \sim are deliberately not padded: \times is
// used tight against its operands everywhere in the ledger (4×3, 3×10^4),
// and \sim is used as a unary "approximately" prefix (∼10^{-13}, |g|∼10^{-3}),
// not a binary relation between two operands — padding it would make that
// case look worse, not better. Ordinary binary operators (+, -, /) are also
// left alone: TeX gives them narrower spacing than a relation, and widening
// the relation rule to cover them isn't what's being asked for here.
const SPACED_SYMBOLS = new Set(["log", "dim", "le", "ge"]);
const THIN_SPACE = " ";

// Unicode Mathematical Alphanumeric Symbols reserves a handful of script
// capitals at their legacy Letterlike-Symbols codepoints instead of the plane
// they otherwise occupy (fonts render these more reliably than the plane-1
// codepoints). \mathcal H is the one that actually appears in the ledger.
const SCRIPT_CAPITALS = { B: "ℬ", E: "ℰ", F: "ℱ", H: "ℋ", I: "ℐ", L: "ℒ", M: "ℳ", R: "ℛ" };

function scriptCapital(letter) {
  if (Object.prototype.hasOwnProperty.call(SCRIPT_CAPITALS, letter)) return SCRIPT_CAPITALS[letter];
  if (/^[A-Z]$/.test(letter)) return String.fromCodePoint(0x1d49c + (letter.charCodeAt(0) - 65));
  return letter;
}

// A character that a spaced symbol should not sit directly against: a letter
// or digit (in any script — this is what makes ℋ, from \mathcal H, count as
// "alphanumeric" for this purpose without a separate special case), or the
// named delimiter on the relevant side.
function isAlnumOrClosing(ch) {
  return ch != null && (/[\p{L}\p{N}]/u.test(ch) || ch === ")" || ch === "]" || ch === "}");
}
function isAlnumOrOpening(ch) {
  return ch != null && (/[\p{L}\p{N}]/u.test(ch) || ch === "(" || ch === "[" || ch === "{");
}

/** Parse the inside of a single $...$ span into DOM nodes. Never throws. */
function parseMathString(str) {
  const nodes = [];
  const spacedIndices = []; // positions in `nodes` holding a SPACED_SYMBOLS token
  let buf = "";
  let i = 0;
  const flush = () => {
    if (buf) nodes.push(document.createTextNode(buf));
    buf = "";
  };

  function readCommandName(pos) {
    const m = /^[a-zA-Z]+/.exec(str.slice(pos));
    return m ? { name: m[0], next: pos + m[0].length } : null;
  }
  function skipOneSpace(pos) {
    return str[pos] === " " ? pos + 1 : pos;
  }
  /** Read one "argument atom": a {...} group, a backslash command, or a
   * single character. Returns null (never throws) if nothing usable follows. */
  function readAtom(pos) {
    if (pos >= str.length) return null;
    if (str[pos] === "{") {
      const close = str.indexOf("}", pos + 1);
      if (close === -1) return null;
      return { nodes: parseMathString(str.slice(pos + 1, close)), next: close + 1 };
    }
    if (str[pos] === "\\") {
      const cmd = readCommandName(pos + 1);
      if (!cmd) return { nodes: [document.createTextNode("\\")], next: pos + 1 };
      const after = skipOneSpace(cmd.next);
      const text = Object.prototype.hasOwnProperty.call(MATH_SYMBOLS, cmd.name)
        ? MATH_SYMBOLS[cmd.name] : cmd.name;
      return { nodes: [document.createTextNode(text)], next: after };
    }
    return { nodes: [document.createTextNode(str[pos])], next: pos + 1 };
  }

  while (i < str.length) {
    const c = str[i];
    if (c === "\\") {
      const cmd = readCommandName(i + 1);
      if (!cmd) { buf += c; i += 1; continue; }
      const after = skipOneSpace(cmd.next);
      if (MATH_ARG_COMMANDS.has(cmd.name)) {
        const atom = readAtom(after);
        if (!atom) { buf += cmd.name; i = after; continue; }
        flush();
        if (cmd.name === "mathbf") {
          const strong = document.createElement("strong");
          for (const n of atom.nodes) strong.appendChild(n);
          nodes.push(strong);
        } else if (cmd.name === "mathcal") {
          const raw = atom.nodes.map((n) => n.textContent).join("");
          nodes.push(document.createTextNode(
            /^[A-Z]$/.test(raw) ? scriptCapital(raw) : raw));
        } else {
          // \mathrm: upright text, i.e. the argument unwrapped as-is.
          for (const n of atom.nodes) nodes.push(n);
        }
        i = atom.next;
        continue;
      }
      if (Object.prototype.hasOwnProperty.call(MATH_SYMBOLS, cmd.name)) {
        if (SPACED_SYMBOLS.has(cmd.name)) {
          // Isolate it as its own node so the padding pass below can look at
          // exactly what sits on either side of it.
          flush();
          spacedIndices.push(nodes.length);
          nodes.push(document.createTextNode(MATH_SYMBOLS[cmd.name]));
        } else {
          buf += MATH_SYMBOLS[cmd.name];
        }
      } else {
        // Unrecognised command: drop the backslash, keep the word.
        buf += cmd.name;
      }
      i = after;
      continue;
    }
    if (c === "_" || c === "^") {
      const atom = readAtom(i + 1);
      if (!atom) { buf += c; i += 1; continue; }
      flush();
      const wrap = document.createElement(c === "_" ? "sub" : "sup");
      for (const n of atom.nodes) wrap.appendChild(n);
      nodes.push(wrap);
      i = atom.next;
      continue;
    }
    if (c === "=") {
      // "=" is typed literally, not as a backslash command, but in TeX it's
      // a relation like \le/\ge and gets the same \thickmuskip padding — the
      // manuscript these three read is the compiled one, where $U=8$ already
      // typesets as "U = 8". So it's padded the same way, not left tight.
      flush();
      spacedIndices.push(nodes.length);
      nodes.push(document.createTextNode(c));
      i += 1;
      continue;
    }
    buf += c;
    i += 1;
  }
  flush();

  // Pad each named-operator/relation token with a thin space on whichever
  // side would otherwise butt it against something alphanumeric (or a
  // delimiter), working right-to-left so an inserted space is already
  // visible to the next (leftward) token's own check — which is what keeps
  // two adjacent spaced tokens from ever getting a doubled-up gap.
  for (let k = spacedIndices.length - 1; k >= 0; k -= 1) {
    const idx = spacedIndices[k];
    const before = nodes[idx - 1];
    const after = nodes[idx + 1];
    const prevChar = before ? before.textContent.slice(-1) : null;
    const nextChar = after ? after.textContent.slice(0, 1) : null;
    const segment = [];
    if (isAlnumOrClosing(prevChar)) segment.push(document.createTextNode(THIN_SPACE));
    segment.push(nodes[idx]);
    if (isAlnumOrOpening(nextChar)) segment.push(document.createTextNode(THIN_SPACE));
    nodes.splice(idx, 1, ...segment);
  }

  return nodes;
}

/** Scan §7 prose for $math$, **bold** and `code` spans. Returns DOM nodes. */
function scanRich(str) {
  const nodes = [];
  let buf = "";
  let i = 0;
  const flush = () => {
    if (buf) nodes.push(document.createTextNode(buf));
    buf = "";
  };

  while (i < str.length) {
    const c = str[i];
    if (c === "$") {
      const close = str.indexOf("$", i + 1);
      if (close === -1) { buf += c; i += 1; continue; } // unmatched $ is literal
      flush();
      for (const n of parseMathString(str.slice(i + 1, close))) nodes.push(n);
      i = close + 1;
      continue;
    }
    if (c === "*" && str[i + 1] === "*") {
      const close = str.indexOf("**", i + 2);
      if (close === -1) { buf += c; i += 1; continue; }
      flush();
      const strong = document.createElement("strong");
      for (const n of scanRich(str.slice(i + 2, close))) strong.appendChild(n);
      nodes.push(strong);
      i = close + 2;
      continue;
    }
    if (c === "`") {
      const close = str.indexOf("`", i + 1);
      if (close === -1) { buf += c; i += 1; continue; }
      flush();
      const code = document.createElement("code");
      code.textContent = str.slice(i + 1, close);
      nodes.push(code);
      i = close + 1;
      continue;
    }
    buf += c;
    i += 1;
  }
  flush();
  return nodes;
}

/** Render §7-authored text (a title, a why, a flag, an agenda detail, a
 * decision) as a DocumentFragment of real DOM nodes. Safe on any input:
 * nested/odd markup degrades to plain text rather than throwing. */
function renderRich(text) {
  const frag = document.createDocumentFragment();
  const str = text === null || text === undefined ? "" : String(text);
  if (!str.includes("\n")) {
    // One block: inline nodes straight into the fragment, no wrapper, which
    // is what every title and every single-paragraph why still gets.
    for (const n of scanRich(str)) frag.appendChild(n);
    return frag;
  }
  // Block structure as the sync parser writes it (handoff.py `_blocks`): a
  // blank line between paragraphs, one `- ` line per bullet. Each paragraph
  // becomes a <p>, each run of bullets one <ul>. Inline markup is scanned per
  // block, so a stray `$` or `**` cannot leak across a paragraph boundary.
  let list = null;
  for (const line of str.split("\n")) {
    if (!line.trim()) { list = null; continue; }
    const bullet = /^[-*]\s+(?=\S)/.exec(line);
    if (bullet) {
      if (!list) { list = document.createElement("ul"); frag.appendChild(list); }
      const li = document.createElement("li");
      for (const n of scanRich(line.slice(bullet[0].length))) li.appendChild(n);
      list.appendChild(li);
    } else {
      list = null;
      const p = document.createElement("p");
      for (const n of scanRich(line)) p.appendChild(n);
      frag.appendChild(p);
    }
  }
  return frag;
}

/** Like el(), but the text is rendered rich instead of set as plain textContent. */
function richEl(tag, attrs, text) {
  const node = el(tag, attrs);
  node.appendChild(renderRich(text));
  return node;
}

function showError(message) {
  const bar = document.getElementById("error");
  bar.textContent = message;
  bar.hidden = !message;
}

async function api(path, options) {
  const response = await fetch(path, options);
  const body = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(body.error || `${response.status} on ${path}`);
  return body;
}

function send(path, payload, method = "POST") {
  return api(path, {
    method,
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

/** A change to the board: write it, then reload so everything agrees.
 *
 * Returns whether the write landed, so a caller holding the only copy of
 * something — a closing note, which has nowhere to be saved until Close is
 * pressed — knows not to let go of it. */
async function mutate(path, payload, method = "POST") {
  try {
    showError("");
    await send(path, payload, method);
    await load();
    return true;
  } catch (err) {
    showError(err.message);
    return false;
  }
}

/** A field save: write it, and do *not* reload. See rule 2 above. */
async function persist(path, payload, draftKey, value) {
  try {
    showError("");
    await send(path, payload, "PATCH");
    if (drafts.get(draftKey) === value) drafts.delete(draftKey);
  } catch (err) {
    showError(err.message);
  }
}

function cancelSave(key) {
  if (timers.has(key)) {
    clearTimeout(timers.get(key));
    timers.delete(key);
  }
}

/** Remember what is on screen and schedule (or make) its save. */
function saveField(entity, id, field, value, { now = false } = {}) {
  const key = `${entity}:${id}:${field}`;
  drafts.set(key, value);
  cancelSave(key);
  if (entity !== "a") return; // a question's closing note has nowhere to go yet
  const write = () => {
    timers.delete(key);
    return persist(`/api/agenda/${id}`, { [field]: value }, key, value);
  };
  if (now) return write();
  timers.set(key, setTimeout(write, SAVE_DEBOUNCE_MS));
}

function draft(entity, id, field, stored) {
  const key = `${entity}:${id}:${field}`;
  return drafts.has(key) ? drafts.get(key) : stored;
}

function forgetDrafts(entity, id) {
  for (const key of [...drafts.keys()]) {
    if (key.startsWith(`${entity}:${id}:`)) {
      cancelSave(key);
      drafts.delete(key);
    }
  }
}

function peopleList(text) {
  return (text || "").split(",").map((s) => s.trim()).filter(Boolean);
}

function sortQuestions(questions) {
  return questions.slice().sort((a, b) => {
    const p = (PRIORITY_RANK[a.priority] ?? 2) - (PRIORITY_RANK[b.priority] ?? 2);
    if (p !== 0) return p;
    const d = (DIFFICULTY_RANK[a.difficulty] ?? 3) - (DIFFICULTY_RANK[b.difficulty] ?? 3);
    if (d !== 0) return d;
    return (b.staleness || 0) - (a.staleness || 0);
  });
}

const DIFFICULTY_LABELS = { S: "Small", M: "Medium", L: "Large" };

function difficultyPicker(question) {
  const select = el("select", {
    onchange: (e) =>
      mutate(`/api/questions/${question.id}/difficulty`, { difficulty: e.target.value || null }),
  });
  for (const value of ["", "S", "M", "L"]) {
    // The blank option hands the item back to the agent's estimate; the server
    // reads a null difficulty as source="agent" for exactly that reason. The
    // wire value stays S/M/L/null either way — only the label shown is a word.
    const option = el("option", { value, text: value ? DIFFICULTY_LABELS[value] : "let the agent estimate" });
    if ((question.difficulty || "") === value) option.selected = true;
    select.appendChild(option);
  }
  const label = el("label", { class: "difficulty" });
  label.appendChild(document.createTextNode("Estimated difficulty"));
  label.appendChild(select);
  return label;
}

function questionCard(question) {
  const closed = question.state === "closed";
  // With no meetings recorded the counter is not zero, it is unknown — and a
  // badge reading "0 mtg" on every card reads as "nothing here is stale".
  const counting = (state.meta.meetings || []).length > 0;
  const heat = el("span", {
    class: "heat",
    text: `${question.staleness || 0} mtg`,
    style: `background:${HEAT[Math.min(question.staleness || 0, 3)]}`,
  });
  const meta = el("div", { class: "meta" }, [
    question.owner ? el("span", { class: "tag", text: `Assignee: ${question.owner}` }) : null,
    question.priority ? el("span", { class: "tag", text: `Priority: ${question.priority}` }) : null,
    closed || !counting ? null : heat,
    question.clickup_status ? el("span", { text: `ClickUp: ${question.clickup_status}` }) : null,
    question.due ? el("span", { text: `due ${question.due}` }) : null,
    closed && question.closed_on ? el("span", { text: `closed ${question.closed_on}` }) : null,
  ]);

  // A closed question shows the difficulty it was judged at, spelled out the
  // same way the picker spells it — a bare "L" means nothing to a reader.
  if (!closed) meta.appendChild(difficultyPicker(question));
  else if (question.difficulty) {
    meta.appendChild(el("span", {
      text: `Estimated difficulty: ${DIFFICULTY_LABELS[question.difficulty] || question.difficulty}`,
    }));
  }

  // Appended last, after the difficulty control, because `.raised` carries
  // margin-left:auto: anything added after it would be pushed to its right and
  // the date would no longer sit at the end of the row.
  if (question.raised) {
    meta.appendChild(el("span", { class: "raised", text: `raised ${question.raised}` }));
  }

  // An inline note, not window.prompt(): a browser with dialogs suppressed —
  // the normal state once somebody ticks "prevent this page from creating
  // dialogs" — makes a prompt-driven button silently inert, and this note is
  // the entire payload of the write-back owed to §7.
  const note = closed ? null : el("textarea", {
    rows: 2,
    class: "note",
    placeholder: "How did it close? (recorded, and owed to HANDOFF §7)",
    oninput: (e) => saveField("q", question.id, "note", e.target.value),
  });
  if (note) note.value = draft("q", question.id, "note", "");

  const toggle = el("button", {
    class: "act",
    text: closed ? "Reopen" : "Close",
    onclick: async () => {
      if (closed) return mutate(`/api/questions/${question.id}/state`, { state: "open" });
      // The note is only dropped once the close has actually landed: a failed
      // POST must not take the note with it while it is still on screen.
      const ok = await mutate(`/api/questions/${question.id}/state`,
        { state: "closed", note: note.value });
      if (ok) forgetDrafts("q", question.id);
      return ok;
    },
  });

  return el("div", { class: closed ? "card closed" : "card" }, [
    el("div", { class: "row" }, [
      el("span", { class: "num", text: question.id }),
      richEl("span", { class: "title" }, question.title),
      toggle,
    ]),
    question.why ? richEl("div", { class: "why" }, question.why) : null,
    meta,
    note,
    closed && question.closed_note
      ? el("div", { class: "grounds", text: question.closed_note })
      : null,
  ]);
}

function flagCard(flag) {
  const resolved = Boolean(flag.resolved);
  return el("div", { class: resolved ? "card flag resolved" : "card flag" }, [
    el("div", { class: "row" }, [
      flag.ordinal ? el("span", { class: "num", text: `§7.1.${flag.ordinal}` }) : null,
      // A div, not a span: a flag may now carry paragraphs and bullets.
      richEl("div", { class: "title" }, flag.text),
    ]),
    el("div", { class: "meta" }, [
      el("span", { text: `first seen ${flag.first_seen || "unknown"}` }),
      el("span", { class: "tag", text: resolved ? "resolved" : "open" }),
    ]),
  ]);
}

function renderFlags(root) {
  const flags = state.flags || [];
  if (!flags.length) return;
  const open = flags.filter((f) => !f.resolved).length;
  root.appendChild(el("h2", { text: `Flags — ${open} open of ${flags.length}` }));
  root.appendChild(el("div", {
    class: "empty",
    text: "The group's live disagreements. Listed, never resolved automatically.",
  }));
  for (const flag of flags) root.appendChild(flagCard(flag));
}

function renderQuestions() {
  const root = document.getElementById("questions");
  root.replaceChildren();
  const open = sortQuestions(state.questions.filter((q) => q.state === "open"));
  const closed = state.questions
    .filter((q) => q.state === "closed")
    .sort((a, b) => (b.closed_on || "").localeCompare(a.closed_on || ""));

  root.appendChild(el("h2", { text: `Open questions — ${open.length}` }));
  if (!open.length) root.appendChild(el("div", { class: "empty", text: "Nothing open." }));
  for (const q of open) root.appendChild(questionCard(q));

  root.appendChild(el("h2", { text: `Closed questions — ${closed.length}` }));
  if (!closed.length) root.appendChild(el("div", { class: "empty", text: "Nothing closed yet." }));
  for (const q of closed) root.appendChild(questionCard(q));

  // Deprioritised: flags aren't important enough to merit a meeting slot, so
  // they sit below both question groups instead of at the top of the tab.
  renderFlags(root);
}

function agendaCard(item) {
  const resolution = el("textarea", {
    rows: 2,
    placeholder: "How was it resolved? (becomes the decision's grounds)",
    oninput: (e) => saveField("a", item.id, "resolution", e.target.value),
    onblur: (e) => saveField("a", item.id, "resolution", e.target.value, { now: true }),
  });
  resolution.value = draft("a", item.id, "resolution", item.resolution || "");

  const followups = el("input", {
    type: "text",
    placeholder: "Follow-up people, comma separated (optional)",
    oninput: (e) => saveField("a", item.id, "followups", peopleList(e.target.value)),
    onblur: (e) => saveField("a", item.id, "followups", peopleList(e.target.value),
      { now: true }),
  });
  const storedFollowups = (item.followups || []).join(", ");
  const draftedFollowups = draft("a", item.id, "followups", null);
  followups.value = draftedFollowups === null ? storedFollowups : draftedFollowups.join(", ");

  const close = el("button", {
    class: "act",
    text: "Close → Decisions",
    onclick: () => {
      if (!resolution.value.trim()) {
        showError("An agenda item needs a resolution before it can be closed.");
        return;
      }
      // Drop any queued save first: the row is about to be closed, and a
      // debounced PATCH landing afterwards would write to a closed item.
      forgetDrafts("a", item.id);
      return mutate(`/api/agenda/${item.id}/close`, {
        resolution: resolution.value,
        followups: peopleList(followups.value),
      });
    },
  });

  // Removing is a dismissal, not a deletion: closing an item mints a decision,
  // so a mistyped or duplicated row had no way off the agenda that did not also
  // put something false into the record. Dismissed rows stay restorable.
  const remove = el("button", {
    class: "act",
    text: "Remove",
    title: "Take this off the agenda without recording a decision",
    onclick: () => {
      forgetDrafts("a", item.id);
      return mutate(`/api/agenda/${item.id}`, { status: "dismissed" }, "PATCH");
    },
  });

  return el("div", { class: "card" }, [
    el("div", { class: "row" }, [
      el("span", { class: "title", text: item.title }),
      remove,
      close,
    ]),
    item.detail ? richEl("div", { class: "why" }, item.detail) : null,
    resolution,
    followups,
  ]);
}

function proposedCard(item) {
  // item.origin (e.g. "sync:flag:1ff433f121") is deliberately not rendered:
  // it's an internal dedup key for sync, not something a physicist needs to
  // see. It stays in state.agenda untouched — only the UI stops showing it.
  return el("div", { class: "card" }, [
    el("div", { class: "row" }, [
      el("span", { class: "title", text: item.title }),
      el("button", {
        class: "act",
        text: "Accept",
        onclick: () => mutate(`/api/agenda/${item.id}`, { status: "accepted" }, "PATCH"),
      }),
      el("button", {
        class: "act",
        text: "Dismiss",
        onclick: () => mutate(`/api/agenda/${item.id}`, { status: "dismissed" }, "PATCH"),
      }),
    ]),
    item.detail ? richEl("div", { class: "why" }, item.detail) : null,
  ]);
}

function dismissedCard(item) {
  // See proposedCard: item.origin is kept in the data but not shown here either.
  return el("div", { class: "card dismissed" }, [
    el("div", { class: "row" }, [
      el("span", { class: "title", text: item.title }),
      el("button", {
        class: "act",
        text: "Restore",
        onclick: () => mutate(`/api/agenda/${item.id}`, { status: "proposed" }, "PATCH"),
      }),
    ]),
  ]);
}

function renderAgenda() {
  const root = document.getElementById("agenda");
  root.replaceChildren();
  const accepted = state.agenda.filter((a) => a.status === "accepted");
  const proposed = state.agenda.filter((a) => a.status === "proposed");
  const dismissed = state.agenda.filter((a) => a.status === "dismissed");

  root.appendChild(el("h2", { text: "Agenda" }));
  if (!accepted.length) {
    root.appendChild(el("div", { class: "empty", text: "Nothing on the agenda." }));
  }
  for (const item of accepted) root.appendChild(agendaCard(item));

  const title = el("input", { type: "text", placeholder: "Add an action item for the meeting" });
  const detail = el("textarea", { rows: 2, placeholder: "Description (optional)" });
  root.appendChild(
    el("div", { class: "card" }, [
      title,
      detail,
      el("button", {
        class: "act",
        text: "Add",
        onclick: async () => {
          if (!title.value.trim()) return;
          const ok = await mutate("/api/agenda",
            { title: title.value, detail: detail.value, status: "accepted" });
          if (ok) {
            title.value = "";
            detail.value = "";
          }
          return ok;
        },
      }),
    ])
  );

  if (proposed.length) {
    root.appendChild(el("h2", { text: `Proposed by sync — ${proposed.length}` }));
    for (const item of proposed) root.appendChild(proposedCard(item));
  }

  if (dismissed.length) {
    // Kept on screen, muted: sync keys its proposals by origin and will never
    // make this one again, so hiding it would be deleting it.
    const group = el("details", { class: "dismissed-group" }, [
      el("summary", { text: `Dismissed — ${dismissed.length}` }),
    ]);
    for (const item of dismissed) group.appendChild(dismissedCard(item));
    root.appendChild(group);
  }
}

function renderDecisions() {
  const root = document.getElementById("decisions");
  root.replaceChildren();
  if (!state.decisions.length) {
    root.appendChild(el("div", { class: "empty", text: "No decisions recorded yet." }));
    return;
  }
  const byDate = new Map();
  for (const d of state.decisions) {
    if (!byDate.has(d.decided_on)) byDate.set(d.decided_on, []);
    byDate.get(d.decided_on).push(d);
  }
  for (const [day, decisions] of byDate) {
    const group = el("div", { class: "daygroup" }, [el("div", { class: "date", text: day })]);
    for (const d of decisions) {
      const grounds = el("div", { class: "grounds" });
      grounds.appendChild(document.createTextNode("Grounds: "));
      grounds.appendChild(renderRich(d.grounds));
      group.appendChild(
        el("div", { class: "card" }, [
          el("div", { class: "row" }, [richEl("span", { class: "title" }, d.text)]),
          grounds,
          el("div", { class: "meta" }, [
            d.decided_by ? el("span", { class: "tag", text: d.decided_by }) : null,
            (d.followups || []).length
              ? el("span", { text: `follow-up: ${d.followups.join(", ")}` })
              : null,
          ]),
        ])
      );
    }
    root.appendChild(group);
  }
}

function renderSubtitle() {
  const parts = [];
  if (state.meta.last_sync) parts.push(`synced ${state.meta.last_sync}`);
  if (state.meta.last_clickup_pull) parts.push(`ClickUp ${state.meta.last_clickup_pull}`);
  const meetings = (state.meta.meetings || []).length;
  parts.push(meetings
    ? `${meetings} meeting${meetings === 1 ? "" : "s"} on record`
    : "no meetings recorded — run ./dashboard meeting YYYY-MM-DD");
  // Flags aren't important enough to merit being brought up in a meeting —
  // the count used to live here; the flags themselves are still listed, just
  // at the bottom of the Open questions tab, not summarised in the header.
  document.getElementById("subtitle").textContent = parts.join(" · ");
}

function render() {
  renderSubtitle();
  renderQuestions();
  renderAgenda();
  renderDecisions();
}

async function load() {
  try {
    state = await api("/api/state");
    render();
  } catch (err) {
    showError(err.message);
  }
}

for (const button of document.querySelectorAll("nav button")) {
  button.addEventListener("click", () => {
    for (const other of document.querySelectorAll("nav button")) {
      const selected = other === button;
      other.setAttribute("aria-selected", String(selected));
      document.getElementById(other.dataset.panel).hidden = !selected;
    }
  });
}

load();
