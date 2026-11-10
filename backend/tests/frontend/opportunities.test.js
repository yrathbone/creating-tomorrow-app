// My Opportunities (C-52): the saved-links card. Runs the real frontend/career/js/opportunities.js
// in a bare VM with a small fake DOM and a stub authedFetch. Nothing is sent anywhere.
// Run:  node --test backend/tests/frontend
const test = require("node:test");
const assert = require("node:assert");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const FRONTEND = path.join(__dirname, "..", "..", "..", "frontend", "career");
const source = fs.readFileSync(path.join(FRONTEND, "js", "opportunities.js"), "utf8");
const html = fs.readFileSync(path.join(FRONTEND, "login.html"), "utf8");

function makeEl(tag) {
  return {
    tagName: tag, children: [], textContent: "", value: "", hidden: true, className: "", type: "", href: "", target: "", rel: "",
    dataset: {}, listeners: {},
    appendChild(child) { this.children.push(child); return child; },
    addEventListener(type, fn) { (this.listeners[type] = this.listeners[type] || []).push(fn); },
    focus() { this.focused = true; },
    reset() { this.resetCalled = true; },
    classList: { add() {}, remove() {}, toggle() {} },
  };
}

// Recursively collects elements (not text nodes) that match the predicate.
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

test("the card stays hidden when the server answers 404 (feature switched off)", async () => {
  const { sandbox, calls, els } = load({ "/api/career/opportunities": bad(404, "Not found.") });
  await sandbox.loadOpportunities();
  assert.strictEqual(els["opportunities-card"].hidden, true);
  assert.deepStrictEqual(calls.map((c) => c.url), ["/api/career/opportunities"]);
});

test("the card shows saved links; an https posting becomes a link with safe attributes", async () => {
  const { sandbox, els } = load({
    "/api/career/opportunities": ok([item()]),
    "/api/career/resume-versions": ok([]),
  });
  await sandbox.loadOpportunities();
  assert.strictEqual(els["opportunities-card"].hidden, false);
  const list = els["opportunity-list"];
  assert.strictEqual(list.children.length, 1);
  assert.strictEqual(textOf(list.children[0]).includes("Program Analyst"), true);
  const links = find(list, (el) => el.tagName === "a");
  assert.strictEqual(links.length, 1);
  assert.strictEqual(links[0].href, "https://jobs.example.com/req/42");
  assert.strictEqual(links[0].target, "_blank");
  assert.strictEqual(links[0].rel, "noopener noreferrer nofollow");
});

test("a link that is not https gets no anchor element at all", async () => {
  const bogus = ["http://jobs.example.com/x", "javascript:alert(1)", "https://user:pw@jobs.example.com/x", "not a url"];
  for (const u of bogus) {
    const { sandbox, els } = load({
      "/api/career/opportunities": ok([item({ job_url: u })]),
      "/api/career/resume-versions": ok([]),
    });
    await sandbox.loadOpportunities();
    assert.strictEqual(find(els["opportunity-list"], (el) => el.tagName === "a").length, 0, u);
  }
});

test("saved text is written as text, never parsed as markup", async () => {
  const hostile = "<img src=x onerror=alert(1)>";
  const { sandbox, els } = load({
    "/api/career/opportunities": ok([item({ title: hostile, employer: hostile })]),
    "/api/career/resume-versions": ok([]),
  });
  await sandbox.loadOpportunities();
  const strong = find(els["opportunity-list"], (el) => el.tagName === "strong")[0];
  assert.strictEqual(strong.textContent, hostile);
  assert.strictEqual(find(els["opportunity-list"], (el) => el.tagName === "img").length, 0);
});

test("safeHttpsHref accepts plain https and rejects every other shape", () => {
  const { sandbox } = load({});
  assert.strictEqual(sandbox.safeHttpsHref("https://jobs.example.com/a?b=1"), "https://jobs.example.com/a?b=1");
  for (const u of ["http://x.example.com", "ftp://x.example.com", "https://a:b@x.example.com", "javascript:alert(1)", "", null, "https://"]) {
    assert.strictEqual(sandbox.safeHttpsHref(u), null, String(u));
  }
});

test("an update carries every stored field, sends no state unless asked, and keeps the approval", () => {
  const { sandbox } = load({});
  const payload = sandbox.buildUpdatePayload(item({
    approval: { status: "changed_since_approval", version_id: 7 },
    state: "saved",
  }));
  assert.strictEqual(payload.title, "Program Analyst");
  assert.strictEqual(payload.base_min, 80000);
  assert.strictEqual(payload.base_max, 95000);
  assert.strictEqual(payload.base_period, "annual");
  assert.strictEqual(payload.approved_resume_version_id, 7);
  assert.strictEqual(payload.dismiss_reason, null);
  assert.strictEqual(Object.prototype.hasOwnProperty.call(payload, "state"), false);
});

test("an update of a dismissed link keeps its reason; a removed approval clears the id", () => {
  const { sandbox } = load({});
  const dismissed = sandbox.buildUpdatePayload(item({ state: "dismissed", dismiss_reason: "pay_too_low" }));
  assert.strictEqual(dismissed.dismiss_reason, "pay_too_low");
  const removed = sandbox.buildUpdatePayload(item({ approval: { status: "version_removed", version_id: 9 } }));
  assert.strictEqual(removed.approved_resume_version_id, null);
});

test("re-approving a changed résumé clears the approval first, then approves the same version", async () => {
  const stored = item({ approval: { status: "changed_since_approval", version_id: 7 } });
  const { sandbox, calls } = load({
    "PUT /api/career/opportunities/1": ok(stored),
  });
  await sandbox.approveResume(stored, 7);
  const puts = calls.filter((c) => c.method === "PUT");
  assert.strictEqual(puts.length, 2);
  assert.strictEqual(puts[0].body.approved_resume_version_id, null);
  assert.strictEqual(puts[1].body.approved_resume_version_id, 7);
});

test("approving a résumé for a link that was never approved needs one save", async () => {
  const { sandbox, calls } = load({ "PUT /api/career/opportunities/1": ok(item()) });
  await sandbox.approveResume(item(), 3);
  const puts = calls.filter((c) => c.method === "PUT");
  assert.strictEqual(puts.length, 1);
  assert.strictEqual(puts[0].body.approved_resume_version_id, 3);
});

test("recording an application posts once and says so when it was already recorded", async () => {
  const { sandbox, calls, els } = load({
    "POST /api/career/opportunities/1/record-application": ok({ already_recorded: true, opportunity: item({ state: "applied" }), application: { id: 5 } }),
    "/api/career/applications": ok([]),
  });
  await sandbox.recordApplication(item());
  const posts = calls.filter((c) => c.method === "POST");
  assert.strictEqual(posts.length, 1);
  assert.strictEqual(els["opportunities-status"].textContent, "This job is already in your tracker.");
});

test("a refused application shows the server's message", async () => {
  const { sandbox, els } = load({
    "POST /api/career/opportunities/1/record-application": bad(409, { message: "Approve a current résumé first." }),
  });
  await sandbox.recordApplication(item());
  assert.strictEqual(els["opportunities-status"].textContent, "Approve a current résumé first.");
});

test("the add form refuses a non-https link without calling the server", async () => {
  const { sandbox, calls, els, getEl } = load({});
  getEl("opportunity-title").value = "Analyst";
  getEl("opportunity-url").value = "http://jobs.example.com/x";
  const result = await sandbox.submitOpportunityForm({ preventDefault() {} });
  assert.strictEqual(result, null);
  assert.strictEqual(calls.length, 0);
  assert.match(els["opportunities-status"].textContent, /https:\/\//);
});

test("the add form refuses pay that is not a whole number", async () => {
  const { sandbox, calls, els, getEl } = load({});
  getEl("opportunity-title").value = "Analyst";
  getEl("opportunity-url").value = "https://jobs.example.com/x";
  getEl("opportunity-base-min").value = "80000.5";
  const result = await sandbox.submitOpportunityForm({ preventDefault() {} });
  assert.strictEqual(result, null);
  assert.strictEqual(calls.length, 0);
});

test("the page has the card hidden by default, and the feature script loads after the applications script", () => {
  const card = html.match(/<div class="card span-2 opportunities-card" id="opportunities-card"[^>]*>/);
  assert.ok(card, "card markup present");
  assert.match(card[0], /\shidden>/);
  const applicationsAt = html.indexOf('<script src="js/applications.js">');
  const opportunitiesAt = html.indexOf('<script src="js/opportunities.js">');
  assert.ok(applicationsAt > 0 && opportunitiesAt > applicationsAt);
});

test("the module never builds markup from strings", () => {
  for (const banned of ["innerHTML", "outerHTML", "insertAdjacentHTML", "document.write", "eval("]) {
    assert.strictEqual(source.includes(banned), false, banned);
  }
});
