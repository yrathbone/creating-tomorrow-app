// The visual dashboard panels: scan cards, resume cards and skill groups (pure helpers + wiring).
// Runs the real frontend/career/js files in a bare VM - no browser needed.
// Run:  node --test backend/tests/frontend
const test = require("node:test");
const assert = require("node:assert");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const CAREER = path.join(__dirname, "..", "..", "..", "frontend", "career");
const read = (...p) => fs.readFileSync(path.join(CAREER, ...p), "utf8");

function load(file) {
  const sandbox = { document: { getElementById: () => null } };
  vm.createContext(sandbox);
  vm.runInContext(read("js", file), sandbox);
  return sandbox;
}
const plain = (v) => JSON.parse(JSON.stringify(v));

test("scan cards take their colour from the fit letter, else the match level, and skill scans are their own kind", () => {
  const { scanCardInfo } = load("history.js");
  const job = (result_data) => ({ scan_type: "job_comparison", job_title: "Role at Co", result_data });
  assert.deepStrictEqual(plain(scanCardInfo(job({ job_fit: { letter: "A" } }))), { kind: "job_comparison", tone: "strong", badge: "Fit A", typeLabel: "Job comparison", title: "Role at Co" });
  assert.strictEqual(scanCardInfo(job({ job_fit: { letter: "B" } })).tone, "good");
  assert.strictEqual(scanCardInfo(job({ job_fit: { letter: "C" } })).tone, "fair");
  assert.strictEqual(scanCardInfo(job({ job_fit: { letter: "D" } })).tone, "low");
  // no fit letter: use the match level the backend really returns (Low / Average / High) and common synonyms
  assert.strictEqual(scanCardInfo(job({ match_report: { match_level: "High" } })).tone, "strong");
  assert.strictEqual(scanCardInfo(job({ match_report: { match_level: "Average" } })).tone, "fair");
  assert.strictEqual(scanCardInfo(job({ match_report: { match_level: "Low" } })).tone, "low");
  assert.strictEqual(scanCardInfo(job({ match_report: { match_level: "Strong" } })).tone, "strong");
  assert.strictEqual(scanCardInfo(job({})).tone, "neutral");
  const skill = scanCardInfo({ scan_type: "skill_scan" });
  assert.strictEqual(skill.kind, "skill_scan");
  assert.strictEqual(skill.tone, "skill");
  assert.strictEqual(skill.title, "Skill Scan");
  assert.strictEqual(scanCardInfo({ scan_type: "job_comparison", result_data: {} }).title, "Job Comparison");
});

test("the scan filter splits job comparisons from skill scans", () => {
  const { filterScans } = load("history.js");
  const all = [{ id: 1, scan_type: "job_comparison" }, { id: 2, scan_type: "skill_scan" }, { id: 3, scan_type: "job_comparison" }];
  assert.deepStrictEqual(Array.from(filterScans(all, "all"), (e) => e.id), [1, 2, 3]);
  assert.deepStrictEqual(Array.from(filterScans(all, "job_comparison"), (e) => e.id), [1, 3]);
  assert.deepStrictEqual(Array.from(filterScans(all, "skill_scan"), (e) => e.id), [2]);
  assert.deepStrictEqual(Array.from(filterScans(null, "all")), []);
});

test("resume cards say what they were tailored to, or that they are general", () => {
  const { resumeCardInfo } = load("history.js");
  const scans = [{ id: 5, job_title: "Customer Success Manager at Stripe" }, { id: 6, job_title: null }];
  const tailored = resumeCardInfo({ scan_history_id: 5, resume_data: { name: "Ada Lovelace", headline: "CSM" } }, scans);
  assert.deepStrictEqual(plain(tailored), { title: "Ada Lovelace", headline: "CSM", kind: "tailored", subtitle: "Tailored to Customer Success Manager at Stripe" });
  assert.strictEqual(resumeCardInfo({ scan_history_id: 6, resume_data: {} }, scans).subtitle, "Tailored to a job");
  assert.strictEqual(resumeCardInfo({ scan_history_id: 99, resume_data: {} }, scans).subtitle, "Tailored to a job");
  const general = resumeCardInfo({ scan_history_id: null, resume_data: { name: "Sam" } }, scans);
  assert.strictEqual(general.kind, "general");
  assert.strictEqual(general.subtitle, "General resume");
  assert.strictEqual(resumeCardInfo({ resume_data: null }, []).title, "Resume");
});

test("skills group under their role in the profile's order, with the rest in one general group", () => {
  const { groupSkillsByRole } = load("skillsVisual.js");
  const roles = [{ id: 1, title: "CSM", organization: "Northwind" }, { id: 2, title: "Account Manager", organization: "Contoso" }, { id: 3, title: "Support", organization: "Fabrikam" }];
  const skills = [
    { id: 1, name: "Renewals", experience_id: 1 },
    { id: 2, name: "SQL", experience_id: null },
    { id: 3, name: "Onboarding", experience_id: 1 },
    { id: 4, name: "Salesforce", experience_id: 2 },
    { id: 5, name: "Orphan", experience_id: 404 }, // role was deleted: falls back to general
  ];
  const groups = plain(groupSkillsByRole(skills, roles));
  assert.deepStrictEqual(groups.map((g) => g.label), ["CSM", "Account Manager", "Not tied to one role"]); // Support has none: no empty card
  assert.deepStrictEqual(groups[0].skills.map((s) => s.name), ["Renewals", "Onboarding"]);
  assert.deepStrictEqual(groups[2].skills.map((s) => s.name), ["SQL", "Orphan"]);
  assert.strictEqual(groups[0].sublabel, "Northwind");
  assert.deepStrictEqual(plain(groupSkillsByRole([], roles)), []);
  assert.deepStrictEqual(plain(groupSkillsByRole(null, null)), []);
});

test("the dashboard page has the new hooks and loads the new script", () => {
  const html = read("login.html");
  for (const id of ["skill-view-toggle", "skill-view-groups", "skill-view-list", "scan-filter", "scan-history-list", "resume-version-list", "skill-detail-list"]) {
    assert.ok(html.includes(`id="${id}"`), `missing #${id}`);
  }
  assert.ok(html.includes('src="js/skillsVisual.js"'));
  const login = read("login.js");
  assert.match(login, /renderSkillGroups\(container\)/); // groups view
  assert.match(login, /renderDetailCard\(container, entry, SKILL_FIELD_DEFS/); // the editable list is still there
});

test("application cards are coloured by status and show how long ago, and stale 'Applied' ones are flagged", () => {
  const { applicationCardInfo } = load("applications.js");
  const day = 86400000;
  const now = new Date("2026-10-20T12:00:00").getTime();
  const at = (iso, status) => plain(applicationCardInfo({ applied_on: iso, status }, now));
  assert.deepStrictEqual(at("2026-10-20", "applied"), { tone: "good", typeLabel: "Applied, waiting", badge: "Today", days: 0, stale: false });
  assert.strictEqual(at("2026-10-19", "applied").badge, "1 day");
  assert.strictEqual(at("2026-10-06", "applied").badge, "14 days");
  assert.strictEqual(at("2026-10-06", "applied").stale, true); // two weeks with no word
  assert.strictEqual(at("2026-10-06", "interview").stale, false); // only "applied" is nudged
  assert.strictEqual(at("2026-10-01", "offer").tone, "strong");
  assert.strictEqual(at("2026-10-01", "interview").tone, "fair");
  assert.strictEqual(at("2026-10-01", "rejected").tone, "low");
  assert.strictEqual(at("2026-10-01", "no_response").tone, "neutral");
  assert.strictEqual(at("2026-10-01", "something-new").tone, "good"); // unknown status falls back to Applied
  assert.strictEqual(at("", "applied").badge, ""); // no date: no badge
  assert.ok(day > 0);
});

test("every card kind the dashboard builds has an icon and every tone has a colour in the stylesheet", () => {
  const css = read("dashboard-v4.css");
  const sources = ["login.js", "js/history.js", "js/applications.js", "js/languages.js"].map((f) => read(f)).join("\n");
  const kinds = new Set([...sources.matchAll(/kind: "([a-z_]+)"/g)].map((m) => m[1]));
  for (const k of ["role", "education", "certification", "skill", "language", "resume", "application", "job_comparison", "skill_scan"]) {
    assert.ok(kinds.has(k), `no card builds kind ${k}`);
  }
  for (const k of kinds) assert.match(css, new RegExp(`\\.vkind-${k} \\{ --scan-icon:`), `no icon for ${k}`);
  const tones = new Set([...sources.matchAll(/tone: "([a-z]+)"/g)].map((m) => m[1]));
  for (const t of ["strong", "good", "fair", "low", "skill", "pink", "neutral"]) assert.match(css, new RegExp(`\\.vtone-${t} \\{ --tone:`), `no colour for tone ${t}`);
  for (const t of tones) assert.match(css, new RegExp(`\\.vtone-${t} \\{ --tone:`), `unstyled tone ${t}`);
});

test("the editable lists all use the shared card: Roles, Education, Certifications, Skills, Languages", () => {
  const login = read("login.js");
  for (const defs of ["EXPERIENCE_FIELD_DEFS", "EDUCATION_FIELD_DEFS", "CERTIFICATION_FIELD_DEFS", "SKILL_FIELD_DEFS"]) {
    assert.match(login, new RegExp(String.raw`const ${defs} = \{\r?\n  card: \{`), `${defs} has no card`);
  }
  assert.match(read("js/languages.js"), /const LANGUAGE_FIELD_DEFS = \{\r?\n  card: \{/);
  assert.ok(read("login.html").indexOf("js/visualCards.js") < read("login.html").indexOf('src="login.js"'), "visualCards.js loads before login.js");
});
