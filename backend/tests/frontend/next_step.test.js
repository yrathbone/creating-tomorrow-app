// "Your next step" card: the pure ladder in frontend/career/js/nextStep.js picks ONE action from data the
// dashboard already loaded. Runs the real file in a bare VM - no browser needed.
// Run:  node --test backend/tests/frontend
const test = require("node:test");
const assert = require("node:assert");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const source = fs.readFileSync(path.join(__dirname, "..", "..", "..", "frontend", "career", "js", "nextStep.js"), "utf8");

function load(extra = {}) {
  const sandbox = { ...extra };
  vm.createContext(sandbox);
  vm.runInContext(source, sandbox);
  return sandbox;
}

const NOW = new Date("2026-10-08T12:00:00").getTime();
const daysAgo = (n) => new Date(NOW - n * 86400000).toISOString().slice(0, 10);
// a fully set-up person with one tailored resume and one tracked application
const done = (over = {}) => ({
  ready: true, roles: 2, education: 1, skills: 5, hasHeader: true,
  scans: [{ id: 7, scan_type: "job_comparison", job_title: "Analyst" }],
  resumes: [{ scan_history_id: 7 }],
  applications: [{ status: "applied", applied_on: daysAgo(3) }],
  today: NOW, ...over,
});
const key = (f) => { const s = load().chooseNextStep(f); return s && s.key; };

test("says nothing until everything has loaded (never advice from half-loaded data)", () => {
  assert.strictEqual(key(done({ ready: false })), null);
  assert.strictEqual(load().chooseNextStep(null), null);
});

test("an empty profile is asked for a role first, and the button is the existing Upload My Resume", () => {
  const step = load().chooseNextStep(done({ roles: 0, skills: 0, education: 0, hasHeader: false, scans: [], resumes: [] }));
  assert.strictEqual(step.key, "add-role");
  assert.deepStrictEqual([...step.targets], ["#upload-resume-btn"]);
});

test("profile gaps come in order: role, skills, header, education", () => {
  assert.strictEqual(key(done({ roles: 0 })), "add-role");
  assert.strictEqual(key(done({ skills: 0 })), "add-skills");
  assert.strictEqual(key(done({ hasHeader: false })), "add-header");
  assert.strictEqual(key(done({ education: 0 })), "add-education");
  assert.strictEqual(key(done({ skills: 0, hasHeader: false, education: 0 })), "add-skills");
});

test("then: first resume, compare a job, finish the unfinished tailored resume", () => {
  assert.strictEqual(key(done({ resumes: [], scans: [] })), "first-resume");
  assert.strictEqual(key(done({ resumes: [{ scan_history_id: null }], scans: [] })), "compare-job");
  const s = load().chooseNextStep(done({ scans: [{ id: 9, scan_type: "job_comparison", job_title: "Data Analyst" }], resumes: [{ scan_history_id: null }] }));
  assert.strictEqual(s.key, "finish-resume");
  assert.match(s.title, /Data Analyst/);
});

test("skill scans do not count as a job comparison", () => {
  assert.strictEqual(key(done({ scans: [{ id: 1, scan_type: "skill_scan" }], resumes: [{ scan_history_id: null }] })), "compare-job");
});

test("a comparison that already has its tailored resume is not nagged", () => {
  assert.notStrictEqual(key(done()), "finish-resume");
});

test("applications: interview beats everything below it, then stale 'applied', then none tracked", () => {
  const apps = (...a) => done({ applications: a });
  assert.strictEqual(key(apps({ status: "interview", applied_on: daysAgo(2) }, { status: "applied", applied_on: daysAgo(30) })), "prepare-interview");
  assert.strictEqual(load().chooseNextStep(apps({ status: "interview", applied_on: daysAgo(2) })).href, "../prepare.html");
  assert.strictEqual(key(apps({ status: "applied", applied_on: daysAgo(14) })), "check-applications");
  assert.strictEqual(key(apps({ status: "applied", applied_on: daysAgo(13) })), "keep-going");
  assert.strictEqual(key(apps()), "track-application");
});

test("only 'applied' ages into a follow-up; rejected/offer/no_response are left alone", () => {
  for (const status of ["rejected", "offer", "no_response"]) {
    assert.strictEqual(key(done({ applications: [{ status, applied_on: daysAgo(60) }] })), "keep-going", status);
  }
});

test("when the tracker is unavailable the card skips application advice instead of guessing", () => {
  assert.strictEqual(key(done({ applications: null })), "keep-going");
});

test("everything done still gives one useful next move", () => {
  const s = load().chooseNextStep(done());
  assert.strictEqual(s.key, "keep-going");
  assert.deepStrictEqual([...s.targets], ["#job-target-add-btn"]);
});

test("every step has a title, text, a button and somewhere to go", () => {
  const cases = [done({ roles: 0 }), done({ skills: 0 }), done({ hasHeader: false }), done({ education: 0 }), done({ resumes: [], scans: [] }),
    done({ resumes: [{ scan_history_id: null }], scans: [] }), done({ scans: [{ id: 9, scan_type: "job_comparison" }], resumes: [] .concat([{ scan_history_id: null }]) }),
    done({ applications: [{ status: "interview", applied_on: daysAgo(1) }] }), done({ applications: [{ status: "applied", applied_on: daysAgo(40) }] }),
    done({ applications: [] }), done()];
  for (const f of cases) {
    const s = load().chooseNextStep(f);
    assert.ok(s.title && s.text && s.button, s.key);
    assert.ok(s.href || (s.targets && s.targets.length), s.key);
  }
});

test("button runs the existing control; an open tile is not toggled closed; hidden controls are skipped", () => {
  const clicked = [];
  const scrolled = [];
  const els = {
    "#job-resume-last-btn": { hidden: true, click: () => clicked.push("last"), scrollIntoView: () => scrolled.push("last"), dataset: {}, classList: { contains: () => false } },
    '.stat-card[data-panel="skills"]': { hidden: false, click: () => clicked.push("tile"), scrollIntoView: () => scrolled.push("tile"), dataset: { panel: "skills" }, classList: { contains: (c) => c === "active" } },
  };
  const sandbox = load({
    document: { querySelector: (s) => els[s] || null, getElementById: (id) => (id === "panel-skills" ? { hidden: false, scrollIntoView: () => scrolled.push("panel") } : null) },
    window: { location: {} },
  });
  sandbox.runNextStep({ targets: ["#job-resume-last-btn"] });
  assert.deepStrictEqual(clicked, [], "a hidden control is never clicked");
  sandbox.runNextStep({ targets: ['.stat-card[data-panel="skills"]'] });
  assert.deepStrictEqual(clicked, [], "an already-open tile is not closed");
  assert.deepStrictEqual(scrolled, ["panel"], "but its list is brought into view");
  const win = { location: {} };
  const s2 = load({ document: { getElementById: () => null }, window: win });
  s2.runNextStep({ href: "../prepare.html" });
  assert.strictEqual(win.location.href, "../prepare.html");
});

test("the dashboard only counts the resume header as set when both the name and the contact line are saved", () => {
  const facts = (basics) => load({
    profileBasics: basics, nextStepReady: true, scansLoaded: true, resumesLoaded: true,
    allExperiences: [{}], allEducation: [{}], allSkills: [{}],
  });
  const hasHeader = (basics) => { const w = facts(basics); return vm.runInContext("nextStepFacts().hasHeader", w); };
  assert.strictEqual(hasHeader({ display_name: "Ada", contact_line: "London" }), true);
  assert.strictEqual(hasHeader({ display_name: "Ada", contact_line: null }), false);
  assert.strictEqual(hasHeader({ display_name: null, contact_line: "London" }), false);
});
