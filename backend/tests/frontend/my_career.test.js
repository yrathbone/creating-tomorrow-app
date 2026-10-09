// Phase 2C slice 1: the My Career card's new pieces (resume-header form, Languages).
// Runs the real frontend scripts in a bare VM with a stub authedFetch - no browser needed.
// Run:  node --test backend/tests/frontend
const test = require("node:test");
const assert = require("node:assert");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const FRONTEND = path.join(__dirname, "..", "..", "..", "frontend");
const read = (...p) => fs.readFileSync(path.join(FRONTEND, ...p), "utf8");

function load(file, fetchImpl) {
  const calls = [];
  const sandbox = { authedFetch: async (url, opts) => { calls.push({ url, opts }); return fetchImpl(url, opts); } };
  vm.createContext(sandbox);
  vm.runInContext(read("career", "js", file), sandbox);
  return { sandbox, calls };
}
const reply = (status, body) => async () => ({ ok: status >= 200 && status < 300, status, json: async () => body });

test("saving the resume header sends only the two fields (trimmed, blank = none) and no identity", async () => {
  const { sandbox, calls } = load("profileBasics.js", reply(200, { display_name: "Ada Lovelace", contact_line: null }));
  const result = await sandbox.saveProfileBasics("  Ada Lovelace  ", "   ");
  assert.deepStrictEqual(JSON.parse(JSON.stringify(result)), { ok: true });
  assert.strictEqual(calls[0].url, "/api/career/profile");
  assert.strictEqual(calls[0].opts.method, "PUT");
  assert.deepStrictEqual(JSON.parse(calls[0].opts.body), { display_name: "Ada Lovelace", contact_line: null });
});

test("a saved header becomes the prefill for the resume forms", async () => {
  const { sandbox } = load("profileBasics.js", reply(200, { display_name: "Grace Hopper", contact_line: "Arlington, VA" }));
  await sandbox.saveProfileBasics("Grace Hopper", "Arlington, VA");
  const name = { value: "" }, contact = { value: "" };
  sandbox.prefillResumeHeader(name, contact);
  assert.strictEqual(name.value, "Grace Hopper");
  assert.strictEqual(contact.value, "Arlington, VA");
});

test("a rejected or failed save reports a message and keeps the old values", async () => {
  const rejected = load("profileBasics.js", reply(400, { detail: "Name is too long (200 characters max)." }));
  assert.deepStrictEqual(JSON.parse(JSON.stringify(await rejected.sandbox.saveProfileBasics("x", "y"))), { ok: false, message: "Name is too long (200 characters max)." });
  const offline = load("profileBasics.js", async () => { throw new Error("offline"); });
  const res = await offline.sandbox.saveProfileBasics("x", "y");
  assert.strictEqual(res.ok, false);
  const name = { value: "" }, contact = { value: "" };
  offline.sandbox.prefillResumeHeader(name, contact);
  assert.strictEqual(name.value + contact.value, "");
});

test("language requests carry only a trimmed name and proficiency", () => {
  const { sandbox } = load("languages.js", reply(200, []));
  const clean = (v) => JSON.parse(JSON.stringify(v));
  assert.deepStrictEqual(clean(sandbox.languagePayload({ name: "  Spanish ", proficiency: "  Native  ", id: 7, career_profile_id: 9, user_id: 1 })), { name: "Spanish", proficiency: "Native" });
  assert.deepStrictEqual(clean(sandbox.languagePayload({ name: "French", proficiency: "   " })), { name: "French", proficiency: null });
  assert.strictEqual(sandbox.languageLabel({ name: "German", proficiency: "Limited working proficiency" }), "German \u2014 Limited working proficiency");
  assert.strictEqual(sandbox.languageLabel({ name: "Hindi", proficiency: null }), "Hindi");
});

test("the dashboard keeps every existing tile, id and card and adds Languages, the header form and the progress strip", () => {
  const html = read("career", "login.html");
  assert.match(html, /<h2>My Career<\/h2>/);
  assert.doesNotMatch(html, /<h2>Your Career Profile<\/h2>/);
  assert.match(html, /class="nav-active">My Career<\/a>/);
  for (const id of ["career-stat-row", "snapshot-panels", "panel-roles", "panel-education", "panel-certifications", "panel-skills", "panel-languages",
                    "experience-detail-list", "education-detail-list", "certification-detail-list", "skill-detail-list", "export-profile-btn",
                    "profile-basics-form", "profile-display-name", "profile-contact-line", "language-form", "language-detail-list",
                    "career-progress", "career-progress-bar", "career-progress-sub",
                    "career-profile-status", "cp-name", "cp-contact", "cp-evidence", "edit-profile-btn", "profile-basics-cancel-btn",
                    // hero actions, cards and flows the scripts rely on
                    "upload-resume-btn", "import-linkedin-btn", "general-resume-hero-btn", "update-profile-btn",
                    "job-target-add-btn", "job-resume-last-btn", "general-resume-start-btn", "general-resume-card", "activity-stat-row", "activity-panels",
                    "panel-history", "panel-resumes", "panel-applications", "career-profile-editor", "nav-signout"]) {
    assert.ok(html.includes('id="' + id + '"'), "missing id " + id);
  }
  // decorative mascots: welcome pose in the hero, small icon pose in the progress strip; both hidden from screen readers
  assert.match(html, /<img class="dh-mascot"[^>]*alt=""/);
  assert.match(html, /<img class="mc-progress-mascot"[^>]*alt=""/);
  for (const f of ["mascot-welcome.png", "mascot-icon.png"]) assert.ok(fs.existsSync(path.join(FRONTEND, f)), f);
  const login = read("career", "login.js");
  assert.match(login, /key: "languages"/);
  assert.match(login, /await loadLanguages\(\)/);
  assert.ok(html.indexOf("js/languages.js") > html.indexOf("login.js"));
  assert.ok(html.indexOf("js/dashboardVisuals.js") > html.indexOf("js/languages.js"));
  assert.ok(html.indexOf("dashboard-v4.css") > html.indexOf("../style.css"));
});

test("the Version 4 look lives in its own stylesheet and every rule is scoped to the signed-in dashboard", () => {
  const css = read("career", "dashboard-v4.css").replace(/\/\*[\s\S]*?\*\//g, "");
  const selectors = [...css.matchAll(/([^{}@;]+)\{/g)].map((m) => m[1]).flatMap((s) => s.split(",")).map((s) => s.trim())
    .filter((s) => s && !/^\d+%?$/.test(s) && !/^media /.test(s));
  const unscoped = selectors.filter((s) => !/^body\.dashboard-v4( |$)/.test(s));
  assert.deepStrictEqual(unscoped, []);
  // the class is switched on only by the dashboard code
  const login = read("career", "login.js");
  assert.match(login, /classList\.add\("dashboard-v4"\)/);
  assert.match(login, /classList\.remove\("dashboard-v4"\)/);
});

test("career foundation progress is derived from loaded data and explains what is next", () => {
  const { sandbox } = load("dashboardVisuals.js", reply(200, []));
  const clean = (v) => JSON.parse(JSON.stringify(v));
  const steps = (flags) => ["a resume header", "a role", "education", "a certification", "skills", "languages"].map((label, i) => ({ label, done: flags[i] }));
  assert.deepStrictEqual(clean(sandbox.careerProgressSummary(steps([false, false, false, false, false, false]))),
    { doneCount: 0, total: 6, complete: false, text: "0 of 6 started · next, add a resume header" });
  assert.strictEqual(sandbox.careerProgressSummary(steps([true, true, false, true, true, false])).text, "4 of 6 started · next, add education");
  const all = sandbox.careerProgressSummary(steps([true, true, true, true, true, true]));
  assert.strictEqual(all.complete, true);
  assert.strictEqual(all.text, "Complete");
});

test("the resume-header step is only done when BOTH the name and the contact line are saved", () => {
  const { sandbox } = load("dashboardVisuals.js", reply(200, []));
  const headerDone = (basics) => { sandbox.profileBasics = basics; return vm.runInContext("CAREER_STEPS.find((s) => s.key === 'header').done()", sandbox); };
  assert.strictEqual(headerDone({ display_name: "Ada Lovelace", contact_line: "London | ada@example.com" }), true);
  assert.strictEqual(headerDone({ display_name: "Ada Lovelace", contact_line: null }), false, "clearing the contact line un-completes the step");
  assert.strictEqual(headerDone({ display_name: "", contact_line: "London" }), false);
  assert.strictEqual(headerDone({ display_name: null, contact_line: null }), false);
});

test("the progress bar fills from the left like a meter, not wherever the finished steps happen to sit", () => {
  const { sandbox } = load("dashboardVisuals.js", reply(200, []));
  const clean = (v) => JSON.parse(JSON.stringify(v));
  assert.deepStrictEqual(clean(sandbox.careerProgressFill(0, 6)), [false, false, false, false, false, false]);
  assert.deepStrictEqual(clean(sandbox.careerProgressFill(4, 6)), [true, true, true, true, false, false]);
  assert.deepStrictEqual(clean(sandbox.careerProgressFill(6, 6)), [true, true, true, true, true, true]);
});

test("the status strip summarizes evidence and the avatar initial from loaded data", () => {
  const { sandbox } = load("dashboardVisuals.js", reply(200, []));
  assert.strictEqual(sandbox.careerEvidenceSummary({ roles: 3, education: 2, certifications: 1, skills: 8, languages: 2 }),
    "3 roles · 2 education · 1 certification · 8 skills · 2 languages");
  assert.strictEqual(sandbox.careerEvidenceSummary({ roles: 1, education: 0, certifications: 0, skills: 0, languages: 1 }), "1 role · 1 language");
  assert.strictEqual(sandbox.careerEvidenceSummary({ roles: 0, education: 0, certifications: 0, skills: 0, languages: 0 }), "No career evidence added yet");
  assert.strictEqual(sandbox.profileInitial("  ada lovelace"), "A");
  assert.strictEqual(sandbox.profileInitial(""), "");
  assert.strictEqual(sandbox.profileInitial(null), "");
});

test("the resume-header form is no longer permanently shown: it is hidden until Edit Profile, and the Job Target keeps both of its actions", () => {
  const html = read("career", "login.html");
  assert.match(html, /<form id="profile-basics-form"[^>]*\bhidden\b/);
  const form = html.indexOf('id="profile-basics-form"'), grid = html.indexOf('class="dashboard-grid"'), card = html.indexOf('<h2>My Career</h2>');
  assert.ok(html.indexOf('id="career-profile-status"') < grid, "status strip sits above the card grid");
  assert.ok(form < grid && form < card, "the form is no longer inside the My Career card");
  assert.match(html, /id="job-target-add-btn"/);
  assert.match(html, /id="job-resume-last-btn"/);
  assert.match(read("career", "js", "jobMatch.js"), /"Continue: " \+ latest\.job_title/);
});
