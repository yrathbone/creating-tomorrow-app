// "Skip This Job": after a comparison the person can skip the job (it is kept under Skipped jobs and can be brought back), which
// takes them back to the empty Current Job Target. Static checks plus the pure helpers, run in a bare VM.
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

const job = (id, skipped, extra = {}) => ({ id, scan_type: "job_comparison", job_title: "Role " + id, result_data: { match_report: {}, ...(skipped ? { skipped: true } : {}), ...extra } });
const skill = (id) => ({ id, scan_type: "skill_scan", result_data: {} });

test("skipped jobs have their own filter and never show in All, Job comparisons or Skill scans", () => {
  const { filterScans, isSkipped } = load("history.js");
  const all = [job(1, false), job(2, true), skill(3), job(4, true)];
  const ids = (list) => list.map((e) => e.id);
  assert.deepStrictEqual(ids(filterScans(all, "all")), [1, 3]);
  assert.deepStrictEqual(ids(filterScans(all, "job_comparison")), [1]);
  assert.deepStrictEqual(ids(filterScans(all, "skill_scan")), [3]);
  assert.deepStrictEqual(ids(filterScans(all, "skipped")), [2, 4]);
  assert.strictEqual(isSkipped(skill(5)), false);
  assert.strictEqual(isSkipped({ scan_type: "skill_scan", result_data: { skipped: true } }), false, "only job comparisons can be skipped");
  assert.strictEqual(isSkipped(null), false);
});

test("a skipped job's card says so, and an ordinary one is unchanged", () => {
  const { scanCardInfo } = load("history.js");
  assert.strictEqual(scanCardInfo(job(1, true)).typeLabel, "Skipped job");
  assert.strictEqual(scanCardInfo(job(1, false)).typeLabel, "Job comparison");
});

test("a skipped job is never offered as an unfinished resume or as the job to continue", () => {
  const source = fs.readFileSync(path.join(CAREER, "js", "nextStep.js"), "utf8");
  const sandbox = {};
  vm.createContext(sandbox);
  vm.runInContext(source, sandbox);
  const base = { ready: true, roles: 2, education: 1, skills: 5, hasHeader: true, resumes: [{ scan_history_id: null }], applications: [], today: Date.now() };
  const unfinished = sandbox.chooseNextStep({ ...base, scans: [job(7, false)] });
  assert.strictEqual(unfinished.key, "finish-resume");
  const skipped = sandbox.chooseNextStep({ ...base, scans: [job(7, true)] });
  assert.strictEqual(skipped.key, "compare-job", "with every job skipped, the nudge is to compare a new one");
  const js = read("js", "jobMatch.js");
  assert.match(js, /s\.scan_type === "job_comparison" && !\(s\.result_data && s\.result_data\.skipped\)/, "Continue ignores skipped jobs");
});

test("the match screen has a Skip This Job button that is separate from Compare a Different Job, and it skips then goes back", () => {
  const html = read("login.html");
  const match = html.slice(html.indexOf('id="job-match-state"'), html.indexOf('id="job-questions-state"'));
  assert.match(match, /id="job-match-new-btn"[^>]*>Compare a Different Job</);
  assert.match(match, /id="job-skip-job-btn"[^>]*>Skip This Job</);
  assert.match(html, /id="job-skipped-note"/);
  const js = read("js", "jobMatch.js");
  const handler = js.slice(js.indexOf('getElementById("job-skip-job-btn").addEventListener'));
  assert.match(handler, /"\/api\/career\/scan-history\/" \+ id \+ "\/skip", \{ method: "POST" \}/);
  assert.ok(handler.indexOf("resetJobTarget();") > handler.indexOf("/skip"), "goes back to the empty Current Job Target after skipping");
  assert.match(handler, /loadScanHistory\(\)/, "the Activity list is refreshed");
  assert.match(handler, /Skipped jobs in Your Activity/, "tells them where it went");
});

test("a skipped card can be brought back and deleted", () => {
  const js = read("js", "history.js");
  assert.match(js, /visualButton\("Bring back", "btn-secondary"/);
  assert.match(js, /"\/unskip", \{ method: "POST" \}/);
  assert.match(js, /\["skipped", "Skipped jobs", skipped\]/);
});
