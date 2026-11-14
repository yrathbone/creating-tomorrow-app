// My Opportunities: the count line shows only supported states. Saved links and applied links are counted separately;
// dismissed links are not in the count and appear on the "Show dismissed links" button instead.
// Runs the real frontend/career/js/opportunities.js in a bare VM with a small fake DOM and a stub authedFetch.
// Nothing is sent anywhere. Run:  node --test backend/tests/frontend
const test = require("node:test");
const assert = require("node:assert");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const FRONTEND = path.join(__dirname, "..", "..", "..", "frontend", "career");
const source = fs.readFileSync(path.join(FRONTEND, "js", "opportunities.js"), "utf8");

function makeEl(tag) {
  const el = {
    tagName: tag, children: [], value: "", hidden: true, className: "", type: "", href: "", target: "", rel: "",
    dataset: {}, listeners: {}, _text: "",
    appendChild(child) { this.children.push(child); return child; },
    addEventListener(type, fn) { (this.listeners[type] = this.listeners[type] || []).push(fn); },
    focus() {}, reset() {},
    classList: { add() {}, remove() {}, toggle() {} },
  };
  Object.defineProperty(el, "textContent", {
    get() { return this._text; },
    set(v) { this._text = v; if (v === "") this.children = []; },
  });
  return el;
}

function textOf(el) {
  if (!el) return "";
  let s = el.textNode !== undefined ? el.textNode : el.textContent || "";
  for (const c of (el.children || [])) s += textOf(c);
  return s;
}

const item = (id, state) => ({
  id, title: "Role " + id, employer: "Acme", job_url: "https://jobs.example.com/req/" + id, source: "Saved by you",
  location_text: "", work_arrangement: null, employment_type: null, base: null, base_note: "", pay_note: "",
  state, dismiss_reason: state === "dismissed" ? "other" : null, application_removed: false, application_id: state === "applied" ? id : null,
  approval: null, last_verified_on: null, notes: "", follow_up_on: null, safety_notice: "", created_at: null, updated_at: null,
});

async function render(links) {
  const els = {};
  const getEl = (id) => (els[id] = els[id] || makeEl(id));
  const sandbox = {
    URL,
    window: { confirm: () => true },
    document: { getElementById: getEl, createElement: makeEl, createTextNode: (t) => ({ textNode: t, children: [] }), addEventListener() {} },
    formatErrorDetail: (detail, fallback) => (typeof detail === "string" ? detail : fallback),
    authedFetch: async () => ({ ok: true, status: 200, json: async () => links }),
  };
  vm.createContext(sandbox);
  vm.runInContext(source, sandbox);
  getEl("opportunities-card").hidden = true;
  await sandbox.loadOpportunities();
  const chips = (els["opportunity-count"].children || []).map((c) => ({ text: textOf(c), cls: c.className }));
  return { els, chips };
}

test("empty: no links shows zero saved, no applied chip, the empty message, and no dismissed count", async () => {
  const { els, chips } = await render([]);
  assert.deepStrictEqual(chips.map((c) => c.text), ["0 saved links"]);
  assert.strictEqual(els["opportunity-empty"].hidden, false);
  assert.strictEqual(els["opportunity-show-dismissed"].textContent, "Show dismissed links (0)");
});

test("saved only: counts saved links and shows no applied chip", async () => {
  const { els, chips } = await render([item(1, "saved"), item(2, "saved")]);
  assert.deepStrictEqual(chips.map((c) => c.text), ["2 saved links"]);
  assert.strictEqual(chips[0].cls, "opportunity-chip opportunity-chip-saved");
  assert.strictEqual(els["opportunity-empty"].hidden, true);
});

test("one saved link uses the singular", async () => {
  const { chips } = await render([item(1, "saved")]);
  assert.deepStrictEqual(chips.map((c) => c.text), ["1 saved link"]);
});

test("applied only: no saved link is counted, and the applied chip shows the applied link", async () => {
  const { chips } = await render([item(1, "applied")]);
  assert.deepStrictEqual(chips.map((c) => c.text), ["0 saved links", "1 applied"]);
  assert.strictEqual(chips[1].cls, "opportunity-chip opportunity-chip-applied");
});

test("mixed: applied links are not counted as saved", async () => {
  const { chips } = await render([item(1, "saved"), item(2, "saved"), item(3, "applied")]);
  assert.deepStrictEqual(chips.map((c) => c.text), ["2 saved links", "1 applied"]);
});

test("dismissed links are left out of the count and counted on the dismissed button", async () => {
  const { els, chips } = await render([item(1, "saved"), item(2, "dismissed"), item(3, "dismissed")]);
  assert.deepStrictEqual(chips.map((c) => c.text), ["1 saved link"]);
  assert.strictEqual(els["opportunity-show-dismissed"].textContent, "Show dismissed links (2)");
});

test("dismissed and applied together: applied is counted, dismissed is not", async () => {
  const { chips } = await render([item(1, "applied"), item(2, "dismissed")]);
  assert.deepStrictEqual(chips.map((c) => c.text), ["0 saved links", "1 applied"]);
});
