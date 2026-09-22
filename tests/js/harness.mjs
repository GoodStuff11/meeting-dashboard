/* A DOM small enough to run app.js against, and no smaller.
 *
 * app.js is a plain script served to a browser: no modules, no build step (the
 * design's stdlib-only rule applies to the front end too). So it is read off
 * disk and run in a vm context holding just the handful of globals it touches —
 * document, fetch, setTimeout. That is enough to drive the interactions that
 * lose meeting work: typing in a resolution box, an unrelated re-render landing
 * on top of it, a double-clicked Close button.
 */

import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import vm from "node:vm";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const APP_JS = path.resolve(HERE, "../../project_tracker/static/app.js");

class Node {
  constructor(tagName) {
    this.tagName = tagName;
    this.children = [];
    this.attributes = {};
    this.listeners = {};
    this.className = "";
    this.hidden = false;
    this.value = "";
    this.selected = false;
    this.style = "";
    this.parentNode = null;
    this._text = "";
  }

  appendChild(child) {
    this.children.push(child);
    child.parentNode = this;
    return child;
  }

  replaceChildren(...nodes) {
    for (const child of this.children) child.parentNode = null;
    this.children = [];
    for (const node of nodes) this.appendChild(node);
  }

  setAttribute(name, value) {
    this.attributes[name] = String(value);
    if (name === "value") this.value = String(value);
  }

  getAttribute(name) {
    return this.attributes[name];
  }

  addEventListener(type, fn) {
    (this.listeners[type] ||= []).push(fn);
  }

  querySelectorAll() {
    return [];
  }

  focus() {
    if (this.ownerHarness) this.ownerHarness.activeElement = this;
  }

  set textContent(value) {
    this._text = value === null || value === undefined ? "" : String(value);
    this.children = [];
  }

  get textContent() {
    return this._text + this.children.map((c) => c.textContent).join("");
  }

  /** Fire every listener for `type`, awaiting anything async they return. */
  async fire(type, event = {}) {
    const handlers = this.listeners[type] || [];
    const results = [];
    for (const handler of handlers) results.push(await handler({ target: this, ...event }));
    return results;
  }

  /** Type `text` into a field: what a browser does on each keystroke. */
  async type(text) {
    this.value = text;
    await this.fire("input");
  }

  async blur() {
    await this.fire("blur");
  }
}

function walk(node, out = []) {
  out.push(node);
  for (const child of node.children) walk(child, out);
  return out;
}

export function find(root, predicate) {
  return walk(root).filter(predicate);
}

export function findByText(root, needle) {
  return find(root, (n) => n.textContent.includes(needle));
}

export function button(root, label) {
  const hits = find(root, (n) => n.tagName === "button" && n.textContent.trim() === label);
  assert.ok(hits.length, `no button labelled ${JSON.stringify(label)}`);
  return hits[0];
}

export function buttons(root, label) {
  return find(root, (n) => n.tagName === "button" && n.textContent.trim() === label);
}

export function fields(root, tagName) {
  return find(root, (n) => n.tagName === tagName);
}

/** Boot app.js against a fake board. Returns the harness. */
export async function start(state) {
  const roots = {};
  for (const id of ["error", "subtitle", "questions", "agenda", "decisions"]) {
    roots[id] = new Node("div");
  }

  const harness = {
    roots,
    requests: [],
    state: structuredClone(state),
    activeElement: null,
    /** Every request the page has made, as {method, path, body}. */
    calls(method, pathPrefix) {
      return harness.requests.filter(
        (r) => (!method || r.method === method) &&
          (!pathPrefix || r.path.startsWith(pathPrefix)));
    },
    async settle(ms = 0) {
      if (ms) await clock.advance(ms);
      for (let i = 0; i < 20; i += 1) await new Promise((r) => setImmediate(r));
    },
  };

  // A clock we can wind forward, so a 500ms debounce is testable in 0ms.
  const timers = new Map();
  let nextTimer = 1;
  let now = 0;
  const clock = {
    setTimeout(fn, delay) {
      const id = nextTimer++;
      timers.set(id, { fn, at: now + (delay || 0) });
      return id;
    },
    clearTimeout(id) {
      timers.delete(id);
    },
    async advance(ms) {
      now += ms;
      const due = [...timers.entries()].filter(([, t]) => t.at <= now);
      due.sort((a, b) => a[1].at - b[1].at);
      for (const [id, timer] of due) {
        timers.delete(id);
        await timer.fn();
      }
    },
    pending() {
      return timers.size;
    },
  };
  harness.clock = clock;

  const document = {
    createElement(tagName) {
      const node = new Node(tagName);
      node.ownerHarness = harness;
      return node;
    },
    // renderRich() builds mixed text/element content, so the harness needs
    // real fragment and text nodes too, not just element nodes.
    createDocumentFragment() {
      const node = new Node(undefined);
      node.ownerHarness = harness;
      return node;
    },
    createTextNode(data) {
      const node = new Node(undefined);
      node.ownerHarness = harness;
      node.textContent = data;
      return node;
    },
    getElementById(id) {
      return roots[id] || null;
    },
    querySelectorAll() {
      return [];
    },
  };

  async function fakeFetch(url, options = {}) {
    const method = (options.method || "GET").toUpperCase();
    const body = options.body ? JSON.parse(options.body) : null;
    harness.requests.push({ method, path: url, body });
    if (method === "GET" && url === "/api/state") {
      return {
        ok: true,
        status: 200,
        json: async () => structuredClone(harness.state),
      };
    }
    const reply = harness.replies && harness.replies.shift();
    if (reply && !reply.ok) {
      return { ok: false, status: reply.status, json: async () => ({ error: reply.error }) };
    }
    return { ok: true, status: 200, json: async () => ({ ok: true }) };
  }

  const context = vm.createContext({
    document,
    fetch: fakeFetch,
    setTimeout: clock.setTimeout,
    clearTimeout: clock.clearTimeout,
    console,
    structuredClone,
  });
  vm.runInContext(fs.readFileSync(APP_JS, "utf8"), context, { filename: "app.js" });
  harness.context = context;
  await harness.settle();
  return harness;
}
