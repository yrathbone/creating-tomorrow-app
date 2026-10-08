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
