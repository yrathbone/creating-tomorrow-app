// My Opportunities (C-52), smallest member flow: the saved-links card. Runs the real
// frontend/career/js/opportunities.js in a bare VM with a small fake DOM and a stub authedFetch.
// Nothing is sent anywhere.
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
  const el = {
    tagName: tag, children: [], value: "", hidden: true, className: "", type: "", href: "", target: "", rel: "",
    dataset: {}, listeners: {}, _text: "",
    appendChild(child) { this.children.push(child); return child; },
    addEventListener(type, fn) { (this.listeners[type] = this.listeners[type] || []).push(fn); },
    focus() { this.focused = true; },
    reset() { this.resetCalled = true; },
    classList: { add() {}, remove() {}, toggle() {} },
  };
  // Like a real DOM: setting textContent replaces the children, so "" clears them.
  Object.defineProperty(el, "textContent", {
    get() { return this._text; },
    set(v) { this._text = v; if (v === "") this.children = []; },
  });
  return el;
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

test("the card shows saved links, and a https posting becomes a link with safe attributes", async () => {
  const { sandbox, els } = load({ "/api/career/opportunities": ok([item()]) });
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
    const { sandbox, els } = load({ "/api/career/opportunities": ok([item({ job_url: u })]) });
    await sandbox.loadOpportunities();
    assert.strictEqual(find(els["opportunity-list"], (el) => el.tagName === "a").length, 0, u);
  }
});

test("saved text is written as text, never parsed as markup", async () => {
  const hostile = "<img src=x onerror=alert(1)>";
  const { sandbox, els } = load({ "/api/career/opportunities": ok([item({ title: hostile, employer: hostile })]) });
  await sandbox.loadOpportunities();
  const strong = find(els["opportunity-list"], (el) => el.tagName === "strong")[0];
  assert.strictEqual(strong.textContent, hostile);
  assert.strictEqual(find(els["opportunity-list"], (el) => el.tagName === "img").length, 0);
});

test("safeHttpsHref accepts plain https and rejects every other shape", () => {
  const { sandbox } = load({});
  assert.strictEqual(sandbox.safeHttpsHref("https://jobs.example.com/a?b=1"), "https://jobs.example.com/a?b=1");
  for (const u of ["http://x.example.com", "ftp://x.example.com", "https://a:b@x.example.com", "javascript:alert(1)", "", null, "https://",
    "https://localhost./", "https://127.0.0.1./", "https://LOCALHOST./x", "https://127.0.0.1/", "https://[::1]/", "https://jobs.example.com./x",
    "https://0177.0.0.1/", "https://0x7f.1/", "https://intranet.lan/x", "https://a..example.com/x", "https://example.com:8443/x",
    "https://0x7f.0x0.0x0.0x1/", "https://192.168.0x1.0x1/", "https://0X7F.0X0.0X0.0X1/", "https://0x7f000001/"]) {
    assert.strictEqual(sandbox.safeHttpsHref(u), null, String(u));
  }
});

test("the add form sends only the manual fields, with no approval, application or state fields", async () => {
  const { sandbox, calls, els } = load({ "POST /api/career/opportunities": ok(item({ id: 9 })), "/api/career/opportunities": ok([]) });
  els["opportunity-title"] = { value: "Analyst" };
  els["opportunity-url"] = { value: "https://jobs.example.com/x" };
  els["opportunity-base-min"] = { value: "" };
  els["opportunity-base-max"] = { value: "" };
  els["opportunity-employer"] = { value: "Acme" };
  const created = await sandbox.submitOpportunityForm({ preventDefault() {} });
  assert.ok(created);
  const post = calls.find((c) => c.method === "POST");
  assert.ok(post, "POST sent");
  for (const forbidden of ["state", "approved_resume_version_id", "application_id", "dismiss_reason"]) {
    assert.strictEqual(Object.prototype.hasOwnProperty.call(post.body, forbidden), false, forbidden);
  }
  assert.strictEqual(post.body.title, "Analyst");
  assert.strictEqual(post.body.job_url, "https://jobs.example.com/x");
});

test("the add form refuses a non-https link without calling the server", async () => {
  const { sandbox, calls, getEl } = load({});
  getEl("opportunity-title").value = "Analyst";
  getEl("opportunity-url").value = "http://jobs.example.com/x";
  const result = await sandbox.submitOpportunityForm({ preventDefault() {} });
  assert.strictEqual(result, null);
  assert.strictEqual(calls.length, 0);
  assert.match(getEl("opportunities-status").textContent, /https:\/\//);
});

test("the add form refuses pay that is not a whole number", async () => {
  const { sandbox, calls, getEl } = load({});
  getEl("opportunity-title").value = "Analyst";
  getEl("opportunity-url").value = "https://jobs.example.com/x";
  getEl("opportunity-base-min").value = "80000.5";
  const result = await sandbox.submitOpportunityForm({ preventDefault() {} });
  assert.strictEqual(result, null);
  assert.strictEqual(calls.length, 0);
});

test("remove sends one DELETE and drops the link from the list", async () => {
  const { sandbox, calls, els } = load({
    "/api/career/opportunities": ok([item({ id: 1 }), item({ id: 2, title: "Other role" })]),
    "DELETE /api/career/opportunities/1": ok({ deleted: true }),
  });
  await sandbox.loadOpportunities();
  await sandbox.deleteOpportunity(vm.runInContext("allOpportunities[0]", sandbox));
  const deletes = calls.filter((c) => c.method === "DELETE");
  assert.deepStrictEqual(deletes.map((d) => d.url), ["/api/career/opportunities/1"]);
  assert.strictEqual(els["opportunity-list"].children.length, 1);
});

test("the add form shows the safety notice verbatim, inside the form", () => {
  const formAt = html.indexOf('id="opportunity-form"');
  const saveAt = html.indexOf('id="opportunity-save-btn"');
  const notice = html.indexOf("Creating Tomorrow does not endorse employers or guarantee the authenticity of listings. Verify opportunities through the employer’s official website before sharing sensitive information. Never pay to apply for a job or receive a job offer.");
  assert.ok(notice > formAt && notice < saveAt, "notice sits inside the form, above the save button");
});

test("the page has the card hidden by default, with no approval or comparison controls, and loads the script after applications", () => {
  const card = html.match(/<div class="card span-2 opportunities-card" id="opportunities-card"[^>]*>/);
  assert.ok(card, "card markup present");
  assert.match(card[0], /\shidden>/);
  const cardBlock = html.slice(html.indexOf('id="opportunities-card"'), html.indexOf('id="general-resume-card"'));
  for (const removed of ["opportunities-context", "opportunities-tracker-btn", "job-target-add-btn", "approve", "record-application"]) {
    assert.strictEqual(cardBlock.includes(removed), false, removed);
  }
  const applicationsAt = html.indexOf('<script src="js/applications.js">');
  const opportunitiesAt = html.indexOf('<script src="js/opportunities.js">');
  assert.ok(applicationsAt > 0 && opportunitiesAt > applicationsAt);
});

test("Compare this job hands the saved link to the job card, and nothing else", async () => {
  const { sandbox, els } = load({ "/api/career/opportunities": ok([item({ id: 7 })]) });
  const seen = [];
  sandbox.startJobFromOpportunity = (o) => seen.push(o.id);
  await sandbox.loadOpportunities();
  const btn = find(els["opportunity-list"], (el) => el.tagName === "button" && el.textContent === "Compare this job")[0];
  assert.ok(btn, "compare button present");
  btn.listeners.click[0]();
  assert.deepStrictEqual(seen, [7]);
});

test("approving a resume sends only the approval, so a stale copy of the link cannot overwrite newer details", async () => {
  const saved = item({ id: 9, notes: "Good fit", base: { min: 80000, max: 95000, period: "annual" }, pay_note: "Bonus varies", state: "saved" });
  const { sandbox, calls } = load({
    "/api/career/opportunities": ok([saved]),
    "PUT /api/career/opportunities/9/approval": ok({ ...saved, approval: { version_id: 41, status: "current" } }),
  });
  await sandbox.loadOpportunities();
  const msg = await sandbox.approveOpportunityResume(9, 41);
  const put = calls.find((c) => c.method === "PUT");
  assert.ok(put, "PUT sent");
  assert.strictEqual(put.url, "/api/career/opportunities/9/approval");
  assert.deepStrictEqual(Object.keys(put.body), ["approved_resume_version_id"]);
  assert.strictEqual(put.body.approved_resume_version_id, 41);
  assert.match(msg, /Approved/);
});

test("approval for a recorded application is refused with the server's sentence, and the link is left as it was", async () => {
  const applied = item({ id: 11, state: "applied", application_id: 3 });
  const { sandbox, els } = load({
    "/api/career/opportunities": ok([applied]),
    "PUT /api/career/opportunities/11/approval": bad(409, { message: "An application is already recorded for this job, so its resume approval cannot change." }),
  });
  await sandbox.loadOpportunities();
  const msg = await sandbox.approveOpportunityResume(11, 41);
  assert.match(msg, /already recorded|cannot change/);
  assert.strictEqual(vm.runInContext("allOpportunities[0].state", sandbox), "applied");
});

test("the approval state is shown in words, and an applied link says the approval is fixed", async () => {
  const { sandbox, els } = load({ "/api/career/opportunities": ok([
    item({ id: 1, approval: { version_id: 5, status: "changed_since_approval" } }),
    item({ id: 2, state: "applied", application_id: 4 }),
  ]) });
  await sandbox.loadOpportunities();
  const text = textOf(els["opportunity-list"]);
  assert.ok(text.includes("has changed since. Approve it again"));
  assert.ok(text.includes("Its approved resume can no longer be changed here."));
});

test("the job card has the saved-link context and the approval control, both hidden by default", () => {
  const ctx = html.match(/<p id="job-opportunity-context"[^>]*>/);
  assert.ok(ctx && /\shidden>/.test(ctx[0]), "context line present and hidden");
  const approval = html.match(/<div id="job-opportunity-approval"[^>]*>/);
  assert.ok(approval && /\shidden>/.test(approval[0]), "approval block present and hidden");
  const doneAt = html.indexOf('id="job-build-done-state"');
  const approvalAt = html.indexOf('id="job-opportunity-approval"');
  assert.ok(approvalAt > doneAt, "approval control sits in the finished-resume step");
});

test("the module never builds markup from strings and never calls the approval or application routes", () => {
  for (const banned of ["innerHTML", "outerHTML", "insertAdjacentHTML", "document.write", "eval(", "record-application", "/resume-versions", "/suggestions"]) {
    assert.strictEqual(source.includes(banned), false, banned);
  }
});
