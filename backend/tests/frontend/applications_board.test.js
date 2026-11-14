// Application tracker: the Board view's logic (grouping into columns, moving a card).
// Runs the real frontend/career/js/applications.js in a bare VM with stub fetch + document.
// Run:  node --test backend/tests/frontend
const test = require("node:test");
const assert = require("node:assert");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const FRONTEND = path.join(__dirname, "..", "..", "..", "frontend", "career");
const source = fs.readFileSync(path.join(FRONTEND, "js", "applications.js"), "utf8");
const html = fs.readFileSync(path.join(FRONTEND, "login.html"), "utf8");

function load(entries) {
  const calls = [];
  const sandbox = {
    document: { getElementById: () => null }, // no panel on the page: rendering is a no-op
    window: { alert() {}, confirm: () => true },
    authedFetch: async (url, opts = {}) => {
      calls.push({ url, method: opts.method || "GET", body: opts.body ? JSON.parse(opts.body) : null });
      return { ok: true, json: async () => entries };
    },
    formatErrorDetail: (d, fallback) => fallback,
  };
  vm.createContext(sandbox);
  vm.runInContext(source, sandbox);
  return { sandbox, calls };
}

const app = (id, status, applied_on, extra = {}) => ({ id, job_title: "Role " + id, company: "Co", applied_on, status, notes: null, scan_history_id: null, resume_version_id: null, ...extra });

test("the board has five columns in search order, and every column exists even when empty", () => {
  const { sandbox } = load([]);
  const columns = vm.runInContext("APPLICATION_BOARD_COLUMNS", sandbox);
  assert.deepStrictEqual(Array.from(columns), ["applied", "interview", "offer", "no_response", "rejected"]);
  const groups = sandbox.groupApplicationsByStatus([]);
  assert.deepStrictEqual(Array.from(Object.keys(groups)), Array.from(columns));
  for (const status of columns) assert.strictEqual(groups[status].length, 0);
});

test("applications land in their status column, newest first; an unknown status falls back to Applied", () => {
  const { sandbox } = load([]);
  const groups = sandbox.groupApplicationsByStatus([
    app(1, "applied", "2026-09-01"),
    app(2, "applied", "2026-10-01"),
    app(3, "interview", "2026-09-20"),
    app(4, "offer", "2026-09-25"),
    app(5, "mystery", "2026-08-01"),
  ]);
  const ids = (list) => Array.from(list, (a) => a.id);
  assert.deepStrictEqual(ids(groups.applied), [2, 1, 5]);
  assert.deepStrictEqual(ids(groups.interview), [3]);
  assert.deepStrictEqual(ids(groups.offer), [4]);
  assert.strictEqual(groups.rejected.length, 0);
});

test("moving a card saves only the status (everything else is sent unchanged) and refreshes the list", async () => {
  const entry = app(7, "applied", "2026-10-01", { company: "Stripe", notes: "Spoke to Sam" });
  const { sandbox, calls } = load([{ ...entry, status: "interview" }]);
  await sandbox.moveApplication(entry, "interview");
  const put = calls.find((c) => c.method === "PUT");
  assert.ok(put, "expected a PUT");
  assert.strictEqual(put.url, "/api/career/applications/7");
  assert.deepStrictEqual(put.body, {
    job_title: "Role 7", company: "Stripe", applied_on: "2026-10-01", status: "interview",
    notes: "Spoke to Sam", scan_history_id: null, resume_version_id: null,
  });
  assert.ok(calls.some((c) => c.method === "GET" && c.url === "/api/career/applications"), "list reloaded after the move");
});

test("dropping a card on its own column does nothing", async () => {
  const entry = app(8, "offer", "2026-10-02");
  const { sandbox, calls } = load([entry]);
  await sandbox.moveApplication(entry, "offer");
  assert.strictEqual(calls.length, 0);
});

test("the dashboard page has the List / Board switch, hidden until there is something to show", () => {
  assert.match(html, /id="application-view-toggle"[^>]*hidden/);
  assert.match(html, /id="application-view-list"/);
  assert.match(html, /id="application-view-board"/);
  assert.match(html, /id="application-list"/); // existing hook kept
});

// --- C-52 review fixes: the tracker's marker helper and the delete path --------------------------------------------

test("the tracker marks an application recorded from a saved job, comparing ids as numbers", () => {
  const { sandbox } = load([]);
  sandbox.window.recordedFromSavedJobIds = new Set([5]);
  assert.strictEqual(sandbox.isRecordedFromSavedJob(5), true);
  assert.strictEqual(sandbox.isRecordedFromSavedJob("5"), true);
  assert.strictEqual(sandbox.isRecordedFromSavedJob(6), false);
});

test("with no saved-link data loaded, nothing is marked", () => {
  const { sandbox } = load([]);
  assert.strictEqual(sandbox.isRecordedFromSavedJob(5), false);
});

// Delete (C-52 review correction): the marker and the saved-link refresh happen only after the server says yes.
// The card is built and its Delete button is pressed in this VM, so the behaviour is tested, not the source text.
const VISUAL_CARDS = fs.readFileSync(path.join(FRONTEND, "js", "visualCards.js"), "utf8");

function makeEl(tag) {
  let text = "";
  const el = {
    tagName: tag, children: [], className: "", hidden: false, disabled: false, value: "", type: "",
    dataset: {}, style: {}, listeners: {}, attrs: {},
    appendChild(child) { this.children.push(child); return child; },
    addEventListener(type, fn) { (this.listeners[type] = this.listeners[type] || []).push(fn); },
    setAttribute(k, v) { this.attrs[k] = String(v); },
    classList: { add() {}, remove() {}, toggle() {}, contains() { return false; } },
    focus() {}, select() {}, reset() {},
  };
  Object.defineProperty(el, "textContent", {
    get() { return text; },
    set(v) { text = v; if (v === "") this.children = []; },
  });
  return el;
}

function loadTracker({ entries, deleteResult, marker }) {
  const calls = [];
  const alerts = [];
  const opp = { loads: 0 };
  const els = {};
  const getEl = (id) => (els[id] = els[id] || makeEl(id));
  const sandbox = {
    document: {
      getElementById: (id) => (id === "application-list" || id === "application-summary" ? getEl(id) : null),
      createElement: makeEl,
      createTextNode: (t) => ({ textNode: t, children: [] }),
    },
    window: { alert: (m) => alerts.push(m), confirm: () => true, recordedFromSavedJobIds: new Set(marker) },
    authedFetch: async (url, opts = {}) => {
      const method = opts.method || "GET";
      calls.push({ url, method });
      if (method === "DELETE") {
        if (deleteResult instanceof Error) throw deleteResult;
        return deleteResult;
      }
      return { ok: true, status: 200, json: async () => entries };
    },
    formatErrorDetail: (detail, fallback) => (typeof detail === "string" ? detail : fallback),
    loadOpportunities: async () => { opp.loads += 1; },
  };
  vm.createContext(sandbox);
  vm.runInContext(VISUAL_CARDS, sandbox);
  vm.runInContext(source, sandbox);
  return { sandbox, calls, alerts, opp, els };
}

function deleteButton(t) {
  const found = [];
  const walk = (el) => { if (el.className === "entry-remove-btn") found.push(el); el.children.forEach(walk); };
  walk(t.els["application-list"]);
  assert.strictEqual(found.length, 1, "one Delete button on the card");
  return found[0];
}

const deleted = { ok: true, status: 204, json: async () => ({}) };

test("a successful delete removes the marker and refreshes the saved links, with no alert", async () => {
  const t = loadTracker({ entries: [app(5, "applied", "2026-10-01")], deleteResult: deleted, marker: [5] });
  await t.sandbox.loadApplications();
  await deleteButton(t).listeners.click[0]();
  assert.strictEqual(t.sandbox.window.recordedFromSavedJobIds.has(5), false, "marker removed");
  assert.strictEqual(t.opp.loads, 1, "saved links refreshed once");
  assert.deepStrictEqual(t.alerts, []);
  assert.deepStrictEqual(t.calls.map((c) => c.method), ["GET", "DELETE", "GET"]);
});

test("a refused delete (HTTP error) keeps the marker, shows the server's reason, and does not refresh", async () => {
  const reason = "This application can't be removed right now.";
  const t = loadTracker({
    entries: [app(5, "applied", "2026-10-01")],
    deleteResult: { ok: false, status: 409, json: async () => ({ detail: reason }) },
    marker: [5],
  });
  await t.sandbox.loadApplications();
  await deleteButton(t).listeners.click[0]();
  assert.strictEqual(t.sandbox.window.recordedFromSavedJobIds.has(5), true, "marker kept");
  assert.strictEqual(t.opp.loads, 0, "no saved-link refresh");
  assert.deepStrictEqual(t.alerts, [reason]);
  assert.deepStrictEqual(t.calls.map((c) => c.method), ["GET", "DELETE"], "no list reload after a refusal");
});

test("a failed delete with no readable reason still keeps the marker and shows a plain message", async () => {
  const t = loadTracker({
    entries: [app(5, "applied", "2026-10-01")],
    deleteResult: { ok: false, status: 500, json: async () => { throw new Error("not json"); } },
    marker: [5],
  });
  await t.sandbox.loadApplications();
  await deleteButton(t).listeners.click[0]();
  assert.strictEqual(t.sandbox.window.recordedFromSavedJobIds.has(5), true, "marker kept");
  assert.deepStrictEqual(t.alerts, ["Couldn’t remove that application."]);
});

test("a network error during delete keeps the marker and shows a connection message", async () => {
  const t = loadTracker({ entries: [app(5, "applied", "2026-10-01")], deleteResult: new Error("Failed to fetch"), marker: [5] });
  await t.sandbox.loadApplications();
  await deleteButton(t).listeners.click[0]();
  assert.strictEqual(t.sandbox.window.recordedFromSavedJobIds.has(5), true, "marker kept");
  assert.strictEqual(t.opp.loads, 0);
  assert.deepStrictEqual(t.alerts, ["Couldn’t remove that application. Check your connection and try again."]);
});
