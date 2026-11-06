// Phase 02 batch 2.6B: keyboard focus and announcements in the job-targeted builder and the saved-résumé history lists.
// Runs frontend/career/js/jobMatch.js (and the focus parts of history.js) in a bare VM with stand-in page elements that record every
// focus() call and every change to the status text. This checks the page's DOM behavior and markup; it is NOT a screen-reader test.
// Run:  node --test backend/tests/frontend
const test = require("node:test");
const assert = require("node:assert");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const CAREER = path.join(__dirname, "..", "..", "..", "frontend", "career");
const read = (...p) => fs.readFileSync(path.join(CAREER, ...p), "utf8");

const PANELS = ["job-target-empty", "job-input-state", "job-loading-state", "job-match-state", "job-questions-state", "job-build-form-state",
  "job-keywords-state", "job-build-loading-state", "job-build-done-state"];

function world({ failing = [], keywordTerms = [{ term: "SQL" }], covered = {}, suggestions = { suggestions: [], applied: [] } } = {}) {
  const log = { focus: [], status: [], alerts: [], saved: [], fetches: [], bodies: {} };
  const els = {};
  const make = (id) => {
    const handlers = {};
    const base = {
      id, hidden: PANELS.includes(id) && id !== "job-target-empty", disabled: false, value: "", textContent: "", innerHTML: "", className: "", dataset: {}, style: {}, children: [],
      classList: { add() {}, remove() {}, toggle() {}, contains: () => false },
      scrollIntoView() {}, appendChild() {}, setAttribute() {}, getAttribute: () => null, querySelector: () => null, querySelectorAll: () => [],
      addEventListener(type, fn) { (handlers[type] = handlers[type] || []).push(fn); },
      focus(options) { log.focus.push({ id, options }); },
      matches: () => false,
      fire(type, event = {}) { return Promise.all((handlers[type] || []).map((fn) => fn(event))); },
    };
    return base;
  };
  const getEl = (id) => (els[id] = els[id] || make(id));
  let statusText = "";
  Object.defineProperty(getEl("job-status"), "textContent", { get: () => statusText, set: (v) => { statusText = v; log.status.push(v); } });
  for (const id of ["job-compare-error", "job-skip-error", "job-questions-error", "job-build-error", "job-keywords-error", "job-download-msg", "job-applied-msg", "job-skipped-note", "job-applied-form"]) getEl(id).hidden = true;
  getEl("job-description-input").value = "A fictional posting.";
  getEl("job-build-name").value = "María José Peña-Núñez";
  getEl("job-build-contact").value = "Naperville, IL | mj@example.com";
  getEl("job-applied-date").value = "2026-11-02";
  getEl("job-resume-template").value = "classic";

  const reply = (key, okBody) => (failing.includes(key)
    ? { ok: false, status: 503, json: async () => ({ detail: `The ${key} step failed. Please try again.` }) }
    : { ok: true, json: async () => okBody, blob: async () => ({}) });
  const sandbox = {
    window: { confirm: () => true },
    document: {
      getElementById: getEl,
      createElement: () => make("created"), createTextNode: () => make("text"), querySelector: () => null, querySelectorAll: () => [],
      body: { appendChild() {} },
    },
    URL: { createObjectURL: () => "blob:x", revokeObjectURL() {} },
    Event: function Event() {},
    alert: (m) => log.alerts.push(m),
    prefillResumeHeader() {}, startProcessingState() {}, stopProcessingState() {}, carryLayoutChoice() {}, escapeHtml: (t) => String(t),
    todayIso: () => "2026-11-02", addApplication: async () => { if (failing.includes("applied")) throw new Error("Couldn't add that application."); },
    loadScanHistory: async () => {}, loadResumeVersions: async () => {}, loadSkills: async () => {}, revealCareerProfileSections() {},
    allScanHistory: [],
    formatErrorDetail: (detail, fallback) => (typeof detail === "string" && detail ? detail : fallback),
    authedFetch: async (url, init) => {
      log.fetches.push(url);
      if (init && init.body) log.bodies[url] = init.body;
      if (/job-compare$/.test(url)) return reply("compare", { match_report: { match_level: "Average", match_rationale: "r", strengths: [], required_qualification_gaps: [] },
        categories: [], questions: [{ id: "q1", category: "c", question: "Did you?", type: "yes_no" }], job_title: "Senior Operations Analyst", scan_history_id: 77, job_fit: null });
      if (/job-discover$/.test(url)) return reply("discover", { stage: "confirm", discovered_facts: [] });
      if (/job-keyword-check$/.test(url)) return reply("keywords", { terms: keywordTerms, already_covered: 0, ...covered });
      if (/job-build-resume$/.test(url)) return reply("build", { resume_data: { name: "María José Peña-Núñez" }, role_selection: [], term_report: [], ats_match: null, resume_version_id: 5 });
      if (/resume-versions\/\d+\/suggestions$/.test(url)) return reply("suggestions", suggestions);
      if (/scan-history\/\d+\/skip$/.test(url)) return reply("skip", {});
      return reply("other", {});
    },
  };
  vm.createContext(sandbox);
  vm.runInContext(read("js", "resumeDownload.js") + "\n" + read("js", "evidenceView.js") + "\n" + read("js", "jobMatch.js") + "\nthis.__jobState = jobState; this.__setQuestions = (q) => { currentJobQuestions = q; };", sandbox);
  const visible = () => PANELS.filter((id) => !els[id].hidden);
  return { els, log, sandbox, getEl, visible, builds: () => log.fetches.filter((u) => /job-build-resume/.test(u)).length };
}
const focused = (w) => w.log.focus.map((f) => f.id);
const keyboard = { currentTarget: { matches: (s) => s === ":focus-visible" } };
const notKeyboard = { detail: 1, currentTarget: { matches: () => false } };

// ---- markup and style ------------------------------------------------------------------------------------------------------
test("the job card has a persistent polite status region and a heading that script focus can reach", () => {
  const html = read("login.html");
  const region = html.match(/<p id="job-status"[^>]*>/);
  assert.ok(region);
  assert.match(region[0], /role="status"/);
  assert.match(region[0], /aria-live="polite"/);
  assert.match(region[0], /aria-atomic="true"/);
  assert.doesNotMatch(region[0], /\bhidden\b|role="alert"|aria-live="assertive"/);
  assert.match(html, /<h2 id="job-card-heading" tabindex="-1">Discover Your Fit<\/h2>/);
  const card = html.slice(html.indexOf('class="card span-2 job-card"'), html.indexOf('id="general-resume-card"'));
  assert.ok(card.indexOf("job-status") < card.indexOf('id="job-target-empty"'), "the region must sit outside the panels that are shown and hidden");
});

test("the five job-flow error messages are alerts, the progress cards can take focus, and the skipped note is no longer a hidden status", () => {
  const html = read("login.html");
  for (const id of ["job-compare-error", "job-skip-error", "job-questions-error", "job-build-error", "job-keywords-error"]) {
    assert.match(html, new RegExp(`<div id="${id}" class="error" role="alert" hidden></div>`), id);
  }
  assert.match(html, /<div id="job-loading-state"[^>]*tabindex="-1"/);
  assert.match(html, /<div id="job-build-loading-state"[^>]*tabindex="-1"/);
  assert.match(html, /<p class="hint" id="job-skipped-note" hidden><\/p>/); // announced through the status region instead
  assert.match(html, /<p class="hint" id="job-applied-msg" tabindex="-1" hidden><\/p>/);
  assert.match(html, /<h3 id="panel-history-heading" tabindex="-1">/);
  assert.match(html, /<h3 id="panel-resumes-heading" tabindex="-1">Resumes Built<\/h3>/);
});

test("the focus rings for the new heading targets are in the dashboard stylesheet, solid blue and scoped", () => {
  const css = read("dashboard-v4.css");
  assert.match(css, /body\.dashboard-v4 #job-card-heading:focus-visible,\s*body\.dashboard-v4 #panel-history-heading:focus-visible,\s*body\.dashboard-v4 #panel-resumes-heading:focus-visible \{ outline: 3px solid var\(--v4-blue\); outline-offset: 2px; \}/);
});

// ---- focus and announcements -----------------------------------------------------------------------------------------------
test("Add a Job: a keyboard press focuses the posting box, a mouse tap or script click does not; Cancel returns to Add a Job", async () => {
  const k = world();
  await k.els["job-target-add-btn"].fire("click", keyboard);
  assert.deepStrictEqual(focused(k), ["job-description-input"]);
  const other = world();
  await other.els["job-target-add-btn"].fire("click", notKeyboard);
  await other.els["job-target-add-btn"].fire("click", { detail: 0, currentTarget: { matches: () => false } });
  assert.deepStrictEqual(focused(other), []);
  await k.els["job-cancel-btn"].fire("click");
  assert.deepStrictEqual(focused(k).slice(-1), ["job-target-add-btn"]);
});

test("comparison: focus to the progress card, then to the card heading, announced once; failure returns focus to the button with an error", async () => {
  const ok = world();
  await ok.els["job-compare-form"].fire("submit", { preventDefault() {} });
  assert.deepStrictEqual(focused(ok), ["job-loading-state", "job-card-heading"]);
  assert.deepStrictEqual(ok.log.status, ["", "Job comparison ready."]);
  assert.deepStrictEqual(ok.visible(), ["job-match-state"]);
  assert.ok(ok.log.focus.every((f) => f.options && f.options.preventScroll === true));
  const bad = world({ failing: ["compare"] });
  await bad.els["job-compare-form"].fire("submit", { preventDefault() {} });
  assert.deepStrictEqual(focused(bad), ["job-loading-state", "job-compare-btn"]);
  assert.strictEqual(bad.els["job-compare-error"].hidden, false);
  assert.match(bad.els["job-compare-error"].textContent, /compare step failed/);
  assert.strictEqual(bad.els["job-description-input"].value, "A fictional posting."); // what was pasted is still there
  assert.deepStrictEqual(bad.log.status, [""]);
});

test("the interview: Explore and Skip announce the next step; a failed Continue restores focus, shows the alert and no longer leaves the progress card on screen", async () => {
  const w = world();
  await w.els["job-compare-form"].fire("submit", { preventDefault() {} });
  w.log.focus.length = 0;
  w.log.status.length = 0;
  await w.els["job-start-interview-btn"].fire("click");
  assert.deepStrictEqual(focused(w), ["job-card-heading"]);
  assert.deepStrictEqual(w.log.status, ["Questions ready."]);
  assert.deepStrictEqual(w.visible(), ["job-questions-state"]);

  const bad = world({ failing: ["discover"] });
  await bad.els["job-compare-form"].fire("submit", { preventDefault() {} });
  await bad.els["job-start-interview-btn"].fire("click");
  bad.log.focus.length = 0;
  await bad.els["job-questions-submit-btn"].fire("click");
  assert.deepStrictEqual(focused(bad), ["job-loading-state", "job-questions-submit-btn"]);
  assert.strictEqual(bad.els["job-questions-error"].hidden, false);
  assert.deepStrictEqual(bad.visible(), ["job-questions-state"]); // the bug: job-loading-state used to stay visible here

  const good = world();
  await good.els["job-compare-form"].fire("submit", { preventDefault() {} });
  await good.els["job-start-interview-btn"].fire("click");
  good.log.focus.length = 0;
  good.log.status.length = 0;
  await good.els["job-questions-submit-btn"].fire("click");
  assert.deepStrictEqual(focused(good), ["job-loading-state", "job-card-heading"]);
  assert.deepStrictEqual(good.log.status, ["", "Add your name and contact line, then build your resume."]);
  assert.deepStrictEqual(good.visible(), ["job-build-form-state"]);
});

test("building: progress card, then heading and 'Your tailored resume is ready.'; failure keeps the typed details and focuses Build; later builds announce again", async () => {
  const w = world();
  await w.els["job-build-btn"].fire("click");
  assert.deepStrictEqual(focused(w), ["job-build-loading-state", "job-card-heading"]);
  assert.deepStrictEqual(w.log.status, ["", "Your tailored resume is ready."]);
  assert.deepStrictEqual(w.visible(), ["job-build-done-state"]);
  await w.els["job-start-over-btn"].fire("click"); // Compare another job
  assert.deepStrictEqual(focused(w).slice(-1), ["job-target-add-btn"]);
  assert.deepStrictEqual(w.visible(), ["job-target-empty"]);
  w.els["job-build-name"].value = "María José Peña-Núñez";
  w.els["job-build-contact"].value = "Naperville, IL | mj@example.com";
  await w.els["job-build-btn"].fire("click");
  assert.deepStrictEqual(w.log.status.filter((t) => t), ["Your tailored resume is ready.", "Your tailored resume is ready."]);
  assert.ok(w.log.status.includes("")); // emptied between builds, so the second one is announced again

  const bad = world({ failing: ["build"] });
  await bad.els["job-build-btn"].fire("click");
  assert.deepStrictEqual(focused(bad), ["job-build-loading-state", "job-build-btn"]);
  assert.strictEqual(bad.els["job-build-error"].hidden, false);
  assert.strictEqual(bad.els["job-build-name"].value, "María José Peña-Núñez");
  assert.deepStrictEqual(bad.log.status, [""]);
});

test("a missing name or contact line leaves focus where it was", async () => {
  const w = world();
  w.els["job-build-name"].value = "";
  await w.els["job-build-btn"].fire("click");
  assert.deepStrictEqual(focused(w), []);
  assert.strictEqual(w.els["job-build-error"].hidden, false);
});

test("keyword check: success, nothing to add, failure, Back, and Save my choices all keep focus inside the card", async () => {
  const w = world();
  await w.els["job-keyword-check-btn"].fire("click");
  assert.deepStrictEqual(focused(w), ["job-loading-state", "job-card-heading"]);
  assert.deepStrictEqual(w.log.status, ["", "Keyword choices ready."]);
  w.log.focus.length = 0;
  w.log.status.length = 0;
  await w.els["job-keywords-back-btn"].fire("click");
  assert.deepStrictEqual(focused(w), ["job-card-heading"]);
  assert.match(w.log.status[0], /^Keyword choices not saved\./);

  const none = world({ keywordTerms: [] });
  await none.els["job-keyword-check-btn"].fire("click");
  assert.deepStrictEqual(focused(none), ["job-loading-state", "job-card-heading"]);
  assert.match(none.log.status.slice(-1)[0], /already backed by your profile/);

  const bad = world({ failing: ["keywords"] });
  await bad.els["job-keyword-check-btn"].fire("click");
  assert.deepStrictEqual(focused(bad), ["job-loading-state", "job-keyword-check-btn"]);
  assert.strictEqual(bad.els["job-build-error"].hidden, false);

  const apply = world();
  await apply.els["job-keywords-apply-btn"].fire("click");
  assert.deepStrictEqual(focused(apply), ["job-card-heading"]);
  assert.strictEqual(apply.els["job-keywords-apply-btn"].disabled, false);
});

test("I applied for this job: keyboard opens the form on its first field; Cancel and Save put focus somewhere logical", async () => {
  const w = world();
  w.sandbox.__jobState.jobTitle = "Analyst at Contoso";
  await w.els["job-applied-btn"].fire("click", keyboard);
  assert.deepStrictEqual(focused(w), ["job-applied-title"]);
  await w.els["job-applied-cancel-btn"].fire("click");
  assert.deepStrictEqual(focused(w).slice(-1), ["job-applied-btn"]);
  const mouse = world();
  await mouse.els["job-applied-btn"].fire("click", notKeyboard);
  assert.deepStrictEqual(focused(mouse), []);
  await w.els["job-applied-save-btn"].fire("click");
  assert.deepStrictEqual(focused(w).slice(-1), ["job-applied-msg"]);
  assert.strictEqual(w.els["job-applied-msg"].hidden, false);
});

test("Skip this job: success announces the note and focuses Add a Job; failure shows the alert and gives the button its focus back", async () => {
  const ok = world();
  ok.sandbox.__jobState.scanHistoryId = 77;
  ok.sandbox.__jobState.jobTitle = "Senior Operations Analyst";
  await ok.els["job-skip-job-btn"].fire("click");
  assert.deepStrictEqual(focused(ok).slice(-1), ["job-target-add-btn"]);
  assert.match(ok.log.status.slice(-1)[0], /Skipped .Senior Operations Analyst/);
  assert.strictEqual(ok.els["job-skipped-note"].hidden, false);
  const bad = world({ failing: ["skip"] });
  bad.sandbox.__jobState.scanHistoryId = 77;
  await bad.els["job-skip-job-btn"].fire("click");
  assert.deepStrictEqual(focused(bad), ["job-skip-job-btn"]);
  assert.strictEqual(bad.els["job-skip-error"].hidden, false);
  assert.strictEqual(bad.els["job-skip-job-btn"].disabled, false);
});

test("Continue: <job> reopens the comparison, focuses the heading and announces it", async () => {
  const w = world();
  w.sandbox.allScanHistory.push({ id: 9, scan_type: "job_comparison", job_title: "Analyst", result_data: { match_report: { match_level: "High", strengths: [], required_qualification_gaps: [] }, job_description: "x" } });
  w.sandbox.restoreCurrentJobTarget();
  await w.els["job-resume-last-btn"].onclick();
  assert.deepStrictEqual(focused(w), ["job-card-heading"]);
  assert.deepStrictEqual(w.log.status.slice(-1), ["Job comparison ready."]);
});

test("repeated downloads never move focus or touch the status region", async () => {
  const w = world();
  await w.els["job-build-btn"].fire("click");
  w.log.focus.length = 0;
  const before = w.log.status.length;
  await w.els["job-download-btn"].fire("click");
  await w.els["job-download-btn"].fire("click");
  assert.deepStrictEqual(focused(w), []);
  assert.strictEqual(w.log.status.length, before);
});

// ---- saved-résumé and scan history -----------------------------------------------------------------------------------------
test("history lists: Delete, Bring back and Make default return focus to a heading (or stay on the card's menu after a failed save); filter chips keep their own focus", () => {
  const src = read("js", "history.js");
  assert.match(src, /function focusHistoryHeading\(id\) \{[\s\S]*?heading\.focus\(\{ preventScroll: true \}\)/);
  const resumeDelete = src.slice(src.indexOf('"/api/career/resume-versions/" + entry.id, { method: "DELETE" }'));
  assert.match(resumeDelete.slice(0, 200), /await loadResumeVersions\(\);\s*focusHistoryHeading\("panel-resumes-heading"\);/);
  const scanDelete = src.slice(src.indexOf('"/api/career/scan-history/" + entry.id, { method: "DELETE" }'));
  assert.match(scanDelete.slice(0, 200), /await loadScanHistory\(\);\s*focusHistoryHeading\("panel-history-heading"\);/);
  assert.match(src, /restoreCurrentJobTarget\(\);\s*focusHistoryHeading\("panel-history-heading"\);/);
  assert.match(src, /if \(result\.ok\) \{\s*focusHistoryHeading\("panel-resumes-heading"\);[^\n]*\n\s*\} else \{\s*syncDefault\(\);\s*layout\.focus\(\{ preventScroll: true \}\);/);
  assert.match(src, /chip\.dataset\.filter = value;/);
  assert.match(src, /bar\.querySelector\('\[data-filter="' \+ value \+ '"\]'\)/);
});

test("focusHistoryHeading focuses the named heading without scrolling and ignores a missing one", () => {
  const calls = [];
  const sandbox = { document: { getElementById: (id) => (id === "h" ? { focus: (o) => calls.push(o) } : null) } };
  vm.createContext(sandbox);
  vm.runInContext(read("js", "history.js").slice(read("js", "history.js").indexOf("function focusHistoryHeading"), read("js", "history.js").indexOf("// ---- pure helpers")), sandbox);
  sandbox.focusHistoryHeading("h");
  sandbox.focusHistoryHeading("nothing");
  assert.deepStrictEqual(JSON.parse(JSON.stringify(calls)), [{ preventScroll: true }]); // (copied out of the VM so the comparison is not cross-realm)
});

// ---- the "Make this my default" buttons inside the builders ------------------------------------------------------------------
test("Make this my default gives the button its focus back after saving, and only when it had focus before", async () => {
  async function press() {
    const calls = { focus: 0 };
    let handler;
    const button = { dataset: { layoutDefault: "menu", layoutMsg: "msg" }, disabled: false, addEventListener: (type, fn) => { handler = fn; }, focus: () => { calls.focus += 1; } };
    const doc = { activeElement: button, getElementById: (id) => (id === "menu" ? { value: "modern" } : { hidden: true, textContent: "" }), querySelectorAll: () => [button] };
    const sandbox = {
      document: doc,
      authedFetch: async () => ({ ok: true, json: async () => ({ layout: "modern" }) }),
    };
    // a disabled button loses focus, as in the browser: mimic it
    Object.defineProperty(button, "disabled", { get: () => false, set: (v) => { if (v) doc.activeElement = {}; } });
    vm.createContext(sandbox);
    vm.runInContext(read("js", "resumeLayout.js"), sandbox);
    await handler();
    return calls.focus;
  }
  assert.strictEqual(await press(), 1);
  const src = read("js", "resumeLayout.js");
  assert.match(src, /const hadFocus = document\.activeElement === btn;/); // only when the button had focus before it was disabled
  assert.match(src, /if \(hadFocus && typeof btn\.focus === "function"\) btn\.focus\(\{ preventScroll: true \}\);/);
});

test("the Continue button says Continue comparison; the job is named for screen readers and on hover", () => {
  const w = world();
  w.sandbox.allScanHistory.push({ id: 9, scan_type: "job_comparison", job_title: "Instructional Designer at Brightpath", result_data: { match_report: { match_level: "High", strengths: [], required_qualification_gaps: [] } } });
  const attrs = {};
  const btn = w.sandbox.document.getElementById("job-resume-last-btn"); // the fake page creates an element on first use
  btn.setAttribute = (k, v) => { attrs[k] = v; };
  w.sandbox.restoreCurrentJobTarget();
  assert.strictEqual(btn.textContent, "Continue comparison");
  assert.strictEqual(attrs["aria-label"], "Continue comparison: Instructional Designer at Brightpath");
  assert.ok(attrs["aria-label"].startsWith(btn.textContent), "the accessible name starts with the visible words");
  assert.strictEqual(btn.title, "Instructional Designer at Brightpath");
  assert.strictEqual(btn.hidden, false);
});

test("keyword check: terms the profile already backs are listed with their evidence and are not asked about", async () => {
  const covered = {
    already_covered: 3,
    covered_exact: [{ term: "Agile", importance: "required" }],
    covered_related: [{ term: "Client implementation", importance: "required", evidence: "Managed client connectivity projects" }],
  };
  const w = world({ keywordTerms: [{ term: "Change management", importance: "required", support: "none" }], covered });
  await w.els["job-keyword-check-btn"].fire("click");
  assert.strictEqual(w.els["job-keywords-covered"].hidden, false);
  assert.strictEqual(w.els["job-keywords-covered-summary"].textContent, "Already backed by your profile (2): see what we found");
  assert.match(w.els["job-keywords-intro"].textContent, /^2 key terms are already backed by your profile .*Only 1 term needs your answer/);
  const none = world({ keywordTerms: [{ term: "Change management" }], covered: { already_covered: 0 } });
  await none.els["job-keyword-check-btn"].fire("click");
  assert.strictEqual(none.els["job-keywords-covered"].hidden, true);
});

test("keyword check: the request names the job comparison so the plan is kept with it and reused by the build", async () => {
  const w = world();
  await w.els["job-keyword-check-btn"].fire("click");
  const body = JSON.parse(w.log.bodies["/api/career/job-keyword-check"]);
  assert.ok("scan_history_id" in body, "the keyword check sends the job comparison id");
});

test("suggestions: after a build the page asks (read-only) for suggestions for that saved resume and shows the block only when there are some", async () => {
  const none = world();
  await none.els["job-build-btn"].fire("click");
  await new Promise((r) => setTimeout(r, 0)); // the suggestions load in the background after the resume is shown
  assert.ok(none.log.fetches.includes("/api/career/resume-versions/5/suggestions"), "asked for the saved version's suggestions");
  assert.strictEqual(none.els["job-suggestions-block"].hidden, true);
  const some = world({ suggestions: { suggestions: [{ term: "Complaint resolution", importance: "required", experience_index: 0, role: "Shift Lead", organization: "Hearthside", source_sentence: "Handled complaints.", suggested_text: "Handled complaints.", before_bullets: ["Scheduled associates."] }], applied: [] } });
  await some.els["job-build-btn"].fire("click");
  await new Promise((r) => setTimeout(r, 0)); // the suggestions load in the background after the resume is shown
  assert.strictEqual(some.els["job-suggestions-block"].hidden, false);
  assert.ok(!some.log.fetches.some((u) => /suggestions\/apply$/.test(u)), "nothing is added until the candidate chooses it");
  const applied = world({ suggestions: { suggestions: [], applied: [{ term: "x", experience_index: 0, text: "t" }] } });
  await applied.els["job-build-btn"].fire("click");
  await new Promise((r) => setTimeout(r, 0)); // the suggestions load in the background after the resume is shown
  assert.strictEqual(applied.els["job-suggestions-undo-btn"].hidden, false);
});

test("suggestions: a failure to load them leaves the finished resume and the page exactly as they were", async () => {
  const w = world({ failing: ["suggestions"] });
  await w.els["job-build-btn"].fire("click");
  await new Promise((r) => setTimeout(r, 0));
  assert.strictEqual(w.els["job-suggestions-block"].hidden, true);
  assert.deepStrictEqual(w.log.alerts, []);
  assert.deepStrictEqual(w.visible(), ["job-build-done-state"]);
});

test("keyword check: an alternatives group is one question card and a met group is listed, not asked", async () => {
  const group = { term: "PMP or PRINCE2", importance: "required", support: "none", alternatives: ["PMP", "PRINCE2"], accepts_equivalent_experience: true };
  const asked = world({ keywordTerms: [group], covered: { already_covered: 0 } });
  await asked.els["job-keyword-check-btn"].fire("click");
  assert.match(asked.els["job-keywords-intro"].textContent, /Only 1 term needs your answer/);
  const met = world({
    keywordTerms: [{ term: "Change management", importance: "required", support: "none" }],
    covered: { already_covered: 1, covered_exact: [{ term: "PRINCE2", importance: "required" }], alternatives_met: [{ terms: ["PMP", "PRINCE2"], importance: "required", met_by: "PRINCE2", evidence: "" }] },
  });
  await met.els["job-keyword-check-btn"].fire("click");
  assert.strictEqual(met.els["job-keywords-covered-summary"].textContent, "Already backed by your profile (1): see what we found");
});

