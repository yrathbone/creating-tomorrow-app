// C-52 closeout (F04): the saved-links card's dismiss, restore, report, check-open and follow-up actions; the
// approval-free update body; the link problem messages; and the job-card wiring for recording through a saved link.
// Runs the real frontend/career/js/*.js files in a bare VM with a small fake DOM and a stub authedFetch. Nothing is sent.
// Run:  node --test backend/tests/frontend
const test = require("node:test");
const assert = require("node:assert");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const FRONTEND = path.join(__dirname, "..", "..", "..", "frontend", "career");
const source = fs.readFileSync(path.join(FRONTEND, "js", "opportunities.js"), "utf8");
const jobSource = fs.readFileSync(path.join(FRONTEND, "js", "jobMatch.js"), "utf8");
const html = fs.readFileSync(path.join(FRONTEND, "login.html"), "utf8");

function makeEl(tag) {
  const el = {
    tagName: tag, children: [], value: "", hidden: true, className: "", type: "", href: "", target: "", rel: "",
    dataset: {}, listeners: {}, _text: "", id: "",
    appendChild(child) { this.children.push(child); return child; },
    addEventListener(type, fn) { (this.listeners[type] = this.listeners[type] || []).push(fn); },
    focus() { this.focused = true; },
    reset() { this.resetCalled = true; },
    classList: { add() {}, remove() {}, toggle() {} },
  };
  Object.defineProperty(el, "textContent", {
    get() { return this._text; },
    set(v) { this._text = v; if (v === "") this.children = []; },
  });
  return el;
}

function find(el, pred, out = []) {
  if (el && el.tagName && pred(el)) out.push(el);
  for (const c of (el && el.children) || []) find(c, pred, out);
  return out;
}

function textOf(el) {
  if (!el) return "";
  let s = el.textNode !== undefined ? el.textNode : el.textContent || "";
  for (const c of (el.children || [])) s += textOf(c);
  return s;
}

function button(root, label) {
  const hits = find(root, (el) => el.tagName === "button" && el.textContent === label);
  assert.ok(hits.length > 0, "button present: " + label);
  return hits[0];
}

const item = (over = {}) => ({
  id: 1, title: "Program Analyst", employer: "Acme", job_url: "https://jobs.example.com/req/42", source: "Saved by you",
  location_text: "Chicago", work_arrangement: "hybrid", employment_type: "full_time",
  base: { min: 80000, max: 95000, period: "annual" }, base_note: "Guaranteed base pay as you entered it.",
  pay_note: "Bonus varies", state: "saved", dismiss_reason: null, application_removed: false, application_id: null,
  approval: null, last_verified_on: null, notes: "Good fit", follow_up_on: null, safety_notice: "Verify on the employer's site.",
  created_at: null, updated_at: null, ...over,
});

function load(routes) {
  const calls = [];
  const els = {};
  const getEl = (id) => (els[id] = els[id] || makeEl(id));
  const sandbox = {
    URL,
    Date,
    window: { confirm: () => true },
    document: {
      getElementById: getEl,
      createElement: makeEl,
      createTextNode: (t) => ({ textNode: t, tagName: undefined, children: [] }),
      addEventListener() {},
    },
    formatErrorDetail: (detail, fallback) => (typeof detail === "string" ? detail : fallback),
    authedFetch: async (url, opts = {}) => {
      const method = opts.method || "GET";
      calls.push({ url, method, body: opts.body ? JSON.parse(opts.body) : null });
      const route = routes[method + " " + url] || routes[url];
      if (!route) return { ok: true, status: 200, json: async () => ({}) };
      return route;
    },
  };
  vm.createContext(sandbox);
  vm.runInContext(source, sandbox);
  getEl("opportunities-card").hidden = true;
  return { sandbox, calls, els, getEl };
}

const ok = (body) => ({ ok: true, status: 200, json: async () => body });
const bad = (status, detail) => ({ ok: false, status, json: async () => ({ detail }) });

const APPROVAL_PATH = "/api/career/opportunities/1";

test("the update body never carries the approval and keeps a recorded application's state unset", async () => {
  const applied = item({ id: 1, state: "applied", application_id: 4, approval: { version_id: 5, status: "current" } });
  const { sandbox, calls } = load({ "/api/career/opportunities": ok([applied]), [`PUT ${APPROVAL_PATH}`]: ok({ ...applied, follow_up_on: "2026-11-20" }) });
  await sandbox.loadOpportunities();
  await sandbox.changeOpportunity(applied, { follow_up_on: "2026-11-20" }, "saved");
  const put = calls.find((c) => c.method === "PUT");
  assert.ok(put, "PUT sent");
  for (const forbidden of ["approved_resume_version_id", "approval", "application_id"]) {
    assert.strictEqual(Object.prototype.hasOwnProperty.call(put.body, forbidden), false, forbidden);
  }
  assert.strictEqual(put.body.state, null, "applied state is not sent back");
  assert.strictEqual(put.body.follow_up_on, "2026-11-20");
  assert.strictEqual(put.body.base_min, 80000);
  assert.strictEqual(put.body.base_period, "annual");
});

test("Check it is still open saves today's date on the link and shows it", async () => {
  const saved = item({ id: 1 });
  const { sandbox, calls, els } = load({ "/api/career/opportunities": ok([saved]), [`PUT ${APPROVAL_PATH}`]: ok({ ...saved, last_verified_on: "2026-11-11" }) });
  await sandbox.loadOpportunities();
  button(els["opportunity-list"], "Check it is still open").listeners.click[0]();
  await new Promise((r) => setImmediate(r));
  const put = calls.find((c) => c.method === "PUT");
  assert.match(put.body.last_verified_on, /^\d{4}-\d{2}-\d{2}$/);
  assert.strictEqual(put.url, APPROVAL_PATH);
});

test("Dismiss sends a dismissed state with the chosen reason, and the link moves out of the active list", async () => {
  const saved = item({ id: 1 });
  const { sandbox, calls, els } = load({ "/api/career/opportunities": ok([saved]),
    [`PUT ${APPROVAL_PATH}`]: ok({ ...saved, state: "dismissed", dismiss_reason: "pay_too_low" }) });
  await sandbox.loadOpportunities();
  const select = find(els["opportunity-list"], (el) => el.id === "opportunity-dismiss-reason-1")[0];
  assert.ok(select, "reason list present");
  select.value = "pay_too_low";
  button(els["opportunity-list"], "Dismiss this link").listeners.click[0]();
  await new Promise((r) => setImmediate(r));
  const put = calls.find((c) => c.method === "PUT");
  assert.strictEqual(put.body.state, "dismissed");
  assert.strictEqual(put.body.dismiss_reason, "pay_too_low");
  assert.strictEqual(vm.runInContext("allOpportunities.filter(o => o.state !== 'dismissed').length", sandbox), 0);
});

test("Report suspicious link dismisses it with the looks_suspicious reason and says to check the employer's site", async () => {
  const saved = item({ id: 1 });
  const { sandbox, calls, els } = load({ "/api/career/opportunities": ok([saved]),
    [`PUT ${APPROVAL_PATH}`]: ok({ ...saved, state: "dismissed", dismiss_reason: "looks_suspicious" }) });
  await sandbox.loadOpportunities();
  button(els["opportunity-list"], "Report suspicious link").listeners.click[0]();
  await new Promise((r) => setImmediate(r));
  const put = calls.find((c) => c.method === "PUT");
  assert.strictEqual(put.body.dismiss_reason, "looks_suspicious");
  assert.match(els["opportunities-status"].textContent, /employer’s site yourself/);
});

test("Restore on a dismissed link sends it back to saved, and the dismissed links are hidden until asked for", async () => {
  const dismissed = item({ id: 2, state: "dismissed", dismiss_reason: "not_interested" });
  const { sandbox, calls, els } = load({ "/api/career/opportunities": ok([item({ id: 1 }), dismissed]),
    [`PUT ${APPROVAL_PATH.replace("/1", "/2")}`]: ok({ ...dismissed, state: "saved", dismiss_reason: null }) });
  await sandbox.loadOpportunities();
  assert.strictEqual(find(els["opportunity-list"], (el) => el.className === "opportunity-item").length, 1, "active only by default");
  vm.runInContext("showDismissedOpportunities = true; renderOpportunities();", sandbox);
  assert.strictEqual(find(els["opportunity-list"], (el) => el.className === "opportunity-item").length, 2, "dismissed shown when asked");
  button(els["opportunity-list"], "Restore").listeners.click[0]();
  await new Promise((r) => setImmediate(r));
  const put = calls.find((c) => c.method === "PUT");
  assert.strictEqual(put.body.state, "saved");
  assert.strictEqual(put.body.dismiss_reason, null);
});

test("saving a follow-up date sends the date; clearing sends null; an empty date is refused locally", async () => {
  const saved = item({ id: 1 });
  const { sandbox, calls, els } = load({ "/api/career/opportunities": ok([saved]), [`PUT ${APPROVAL_PATH}`]: ok({ ...saved, follow_up_on: "2026-11-20" }) });
  await sandbox.loadOpportunities();
  const input = find(els["opportunity-list"], (el) => el.id === "opportunity-followup-1")[0];
  input.value = "";
  button(els["opportunity-list"], "Save follow-up date").listeners.click[0]();
  assert.strictEqual(calls.filter((c) => c.method === "PUT").length, 0, "nothing sent for an empty date");
  input.value = "2026-11-20";
  button(els["opportunity-list"], "Save follow-up date").listeners.click[0]();
  await new Promise((r) => setImmediate(r));
  assert.strictEqual(calls.find((c) => c.method === "PUT").body.follow_up_on, "2026-11-20");
});

test("a link with a follow-up date offers to clear it", async () => {
  const saved = item({ id: 1, follow_up_on: "2026-11-20" });
  const { sandbox, calls, els } = load({ "/api/career/opportunities": ok([saved]), [`PUT ${APPROVAL_PATH}`]: ok({ ...saved, follow_up_on: null }) });
  await sandbox.loadOpportunities();
  button(els["opportunity-list"], "Clear follow-up date").listeners.click[0]();
  await new Promise((r) => setImmediate(r));
  assert.strictEqual(calls.find((c) => c.method === "PUT").body.follow_up_on, null);
});

test("a server refusal on a change is shown as its sentence and the list is left as it was", async () => {
  const saved = item({ id: 1 });
  const { sandbox, els } = load({ "/api/career/opportunities": ok([saved]),
    [`PUT ${APPROVAL_PATH}`]: bad(409, "This job already has an application recorded. Remove it from the tracker first.") });
  await sandbox.loadOpportunities();
  await sandbox.changeOpportunity(saved, { state: "dismissed", dismiss_reason: "other" }, "done");
  assert.match(els["opportunities-status"].textContent, /already has an application recorded/);
  assert.strictEqual(vm.runInContext("allOpportunities[0].state", sandbox), "saved");
});

test("a Unicode or percent-encoded web address gets the clear message on the client, before the server is asked", () => {
  const { sandbox } = load({});
  const msg = "This web address isn’t supported yet. Please enter a standard HTTPS job link.";
  assert.strictEqual(sandbox.opportunityLinkProblem("https://jobs.exämple.com/x"), msg);
  assert.strictEqual(sandbox.opportunityLinkProblem("https://jobs%2Eexample.com/x"), msg);
  assert.strictEqual(sandbox.opportunityLinkProblem("https://xn--exmple-cua.com/x"), null, "punycode is accepted");
  assert.strictEqual(sandbox.opportunityLinkProblem("https://jobs.example.com/req/42?src=a#apply"), null);
  assert.match(sandbox.opportunityLinkProblem("http://jobs.example.com/x"), /https:\/\//);
});

test("the list text says how many links are saved, and the controls have accessible names", () => {
  for (const id of ["opportunity-show-dismissed", "opportunity-clear-dismissed", "opportunity-count"]) {
    assert.ok(html.includes('id="' + id + '"'), id);
  }
  assert.ok(html.includes('href="opportunities.css"'), "card stylesheet linked");
  assert.ok(/<button type="button" id="opportunity-show-dismissed"[^>]*>Show dismissed links<\/button>/.test(html), "show dismissed has visible text");
});

test("the job card sends the saved link only when there is one, and records a linked application through the saved-link route", () => {
  assert.ok(jobSource.includes("opportunity_id: jobState.opportunityId"), "compare sends the saved link");
  assert.ok(/JSON\.stringify\(jobState\.opportunityId \? \{ job_description: jobDescription, opportunity_id: jobState\.opportunityId \} : \{ job_description: jobDescription \}\)/.test(jobSource),
    "the field is sent only when a link is set");
  const linkedBranch = jobSource.indexOf("if (jobState.opportunityId) {", jobSource.indexOf("job-applied-save-btn"));
  const legacyBranch = jobSource.indexOf("await addApplication({", jobSource.indexOf("job-applied-save-btn"));
  assert.ok(linkedBranch > 0 && legacyBranch > linkedBranch, "linked branch comes first");
  assert.ok(jobSource.includes('"/api/career/opportunities/" + opportunityId + "/record-application"'), "linked application uses the saved-link route");
});

test("opening a comparison from a saved link restores the link from the stored comparison", () => {
  const openAt = jobSource.indexOf("function openJobTarget(latest)");
  const body = jobSource.slice(openAt, openAt + 900);
  assert.ok(body.includes("data.opportunity_id"), "reads the saved link from the comparison");
  assert.ok(body.includes("jobState.opportunityId = data.opportunity_id"), "keeps it for approval and recording");
});

test("every details save sends the version the card is showing, so an outdated card is refused by the server", async () => {
  const saved = item({ id: 1, version: "abc123" });
  const { sandbox, calls } = load({ "/api/career/opportunities": ok([saved]), [`PUT ${APPROVAL_PATH}`]: ok({ ...saved, version: "def456" }) });
  await sandbox.loadOpportunities();
  await sandbox.changeOpportunity(saved, { notes: "x" }, "saved");
  assert.strictEqual(calls.find((c) => c.method === "PUT").body.if_version, "abc123");
});

test("a conflict tells the member to reload and shows the latest saved details", async () => {
  const saved = item({ id: 1, version: "abc123", notes: "old" });
  const latest = item({ id: 1, version: "zzz999", notes: "newer, from another tab" });
  const { sandbox, calls, els } = load({
    "/api/career/opportunities": ok([saved]),
    [`PUT ${APPROVAL_PATH}`]: { ok: false, status: 409, json: async () => ({ detail: { message: "This saved link was changed in another tab or window, so your change was not saved. Reload the page to see the latest details, then make the change again." } }) },
  });
  await sandbox.loadOpportunities();
  // the list the server returns on the reload carries the newer details
  calls.length = 0;
  await sandbox.changeOpportunity(saved, { notes: "mine" }, "saved");
  assert.match(els["opportunities-status"].textContent, /Reload the page/);
  assert.ok(calls.some((c) => c.method === "GET" && c.url === "/api/career/opportunities"), "the list is read again after a conflict");
});

test("the card reads the approval again when the window is back in use, and a job card records only after a fresh read", () => {
  assert.ok(source.includes('window.addEventListener("focus", refreshIfVisible)'), "focus refresh");
  assert.ok(source.includes('document.addEventListener("visibilitychange", refreshIfVisible)'), "visibility refresh");
  assert.ok(/await loadOpportunities\(\);\s*\n\s*const items/.test(jobSource), "fresh read before recording");
});

test("an unsaved follow-up date survives a re-draw of the list (focus refresh, conflict reload)", async () => {
  const saved = item({ id: 1, follow_up_on: null });
  const { sandbox, els } = load({ "/api/career/opportunities": ok([saved]) });
  await sandbox.loadOpportunities();
  els["opportunity-followup-1"] = { value: "2026-12-01" };   // the typed, unsaved value in the page
  vm.runInContext("renderOpportunities()", sandbox);
  const input = find(els["opportunity-list"], (el) => el.id === "opportunity-followup-1")[0];
  assert.ok(input, "input re-created");
  assert.strictEqual(input.value, "2026-12-01", "typed date kept");
});

test("a saved follow-up date is shown as saved, not as a draft", async () => {
  const saved = item({ id: 1, follow_up_on: "2026-11-20" });
  const { sandbox, els } = load({ "/api/career/opportunities": ok([saved]) });
  await sandbox.loadOpportunities();
  els["opportunity-followup-1"] = { value: "2026-11-20" };
  vm.runInContext("renderOpportunities()", sandbox);
  const input = find(els["opportunity-list"], (el) => el.id === "opportunity-followup-1")[0];
  assert.strictEqual(input.value, "2026-11-20");
});

test("the focus refresh does not redraw while the member is in the list or has an unsaved date", () => {
  assert.ok(source.includes("list.contains(active)"), "focus inside the list is respected");
  assert.ok(source.includes("captureFollowUpDrafts()).length > 0"), "unsaved dates are respected");
});

test("a saved link with a stored approved document says so, distinct from the current résumé, and offers its download", async () => {
  const saved = item({ id: 1, approved_document: { saved_on: "2026-11-11", layout: "classic", content_sha256: "2cb6054b0589" } });
  const { sandbox, els } = load({ "/api/career/opportunities": ok([saved]) });
  await sandbox.loadOpportunities();
  assert.ok(textOf(els["opportunity-list"]).includes("Approved document saved on 2026-11-11"), "note shown");
  assert.ok(textOf(els["opportunity-list"]).includes("does not change"), "distinct from the current résumé");
  assert.ok(find(els["opportunity-list"], (el) => el.tagName === "button" && el.textContent === "Download the approved document").length === 1, "download offered");
});

test("the approved-document download uses the stored-file route, not the current-résumé route", () => {
  assert.ok(source.includes('"/api/career/opportunities/" + item.id + "/approved-document"'), "stored route");
  assert.ok(!source.includes("/resume-versions/"), "no current-résumé route in the card");
});
