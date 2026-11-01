// Download buttons in the resume workflow (Phase 02 batch 2.3): the file name, the inline messages that replace pop-ups,
// and that nothing the person typed is cleared when a download fails. Runs frontend/career/js files in a bare VM with
// stand-in page elements and a stand-in server.
// Run:  node --test backend/tests/frontend
const test = require("node:test");
const assert = require("node:assert");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const CAREER = path.join(__dirname, "..", "..", "..", "frontend", "career");
const read = (...p) => fs.readFileSync(path.join(CAREER, ...p), "utf8");

function element(extra = {}) {
  const handlers = {};
  return Object.assign({
    hidden: false, disabled: false, value: "", textContent: "", style: {}, attrs: {},
    addEventListener(type, fn) { (handlers[type] = handlers[type] || []).push(fn); },
    setAttribute(k, v) { this.attrs[k] = v; },
    scrollIntoView() {},
    click() { return this.fire("click"); },
    fire(type, event = {}) { return Promise.all((handlers[type] || []).map((fn) => fn(event))); },
  }, extra);
}

// ---- the file name ------------------------------------------------------------------------------------------------------
const helpers = vm.createContext({ URL: { createObjectURL: () => "blob:x", revokeObjectURL() {} }, document: {} });
vm.runInContext(read("js", "resumeDownload.js"), helpers);
const fileName = (name, role) => vm.runInContext(`resumeFileName(${JSON.stringify(name)}, ${JSON.stringify(role)})`, helpers);

test("the file is First_Last_Resume_Role.docx, and the role is left out when there is none", () => {
  assert.strictEqual(fileName("Casey Rowan", ""), "Casey_Rowan_Resume.docx");
  assert.strictEqual(fileName("Casey Rowan", undefined), "Casey_Rowan_Resume.docx");
  assert.strictEqual(fileName("Casey Rowan", "Senior Operations Analyst"), "Casey_Rowan_Resume_Senior_Operations_Analyst.docx");
  assert.strictEqual(fileName("Mary Jane  Smith", "  QA / Test Lead "), "Mary_Jane_Smith_Resume_QA_Test_Lead.docx");
});

test("a missing name or role never leaves an empty part or a doubled underscore", () => {
  assert.strictEqual(fileName("", ""), "Resume.docx");
  assert.strictEqual(fileName(null, null), "Resume.docx");
  assert.strictEqual(fileName("   ", "Analyst"), "Resume_Analyst.docx");
  assert.strictEqual(fileName("Casey Rowan", "///"), "Casey_Rowan_Resume.docx");
  assert.ok(!/__/.test(fileName("A  B", "C   D")));
});

test("names in other languages keep their letters; unsafe characters are removed", () => {
  assert.strictEqual(fileName("María José Peña-Núñez", ""), "María_José_Peña-Núñez_Resume.docx");
  assert.strictEqual(fileName("李明", "工程师"), "李明_Resume_工程师.docx");
  assert.ok(!/[\\/:*?"<>|\r\n;]/.test(fileName('a/b\\c:d*e?f"g<h>i|j;k', "r/s")));
  assert.ok(!fileName('Evil"; name\r\n..\\x', "").includes(".."));
});

test("very long names and roles are cut to a sensible length and never end in a separator", () => {
  const name = fileName("A".repeat(200) + " " + "B".repeat(200), "R".repeat(300));
  assert.ok(name.length <= 40 + 1 + 6 + 1 + 40 + 5, String(name.length));
  assert.ok(name.endsWith(".docx"));
  assert.ok(!/[._-]\.docx$/.test(name));
});

// ---- the general resume button -------------------------------------------------------------------------------------------
function generalWorld({ server } = {}) {
  const ids = ["general-resume-empty", "general-resume-form", "general-resume-loading", "general-resume-done", "general-resume-card", "general-resume-hero-btn",
    "general-resume-hero-btn-2", "general-resume-start-btn", "general-resume-cancel-btn", "general-resume-build-btn", "general-resume-name", "general-resume-contact",
    "general-resume-error", "general-resume-download-btn", "general-resume-template", "general-resume-again-btn", "general-build-layout", "general-download-msg"];
  const els = Object.fromEntries(ids.map((id) => [id, element()]));
  els["general-download-msg"].hidden = true;
  els["general-resume-template"].value = "classic";
  const log = { alerts: [], saved: [], fetches: [] };
  const sandbox = {
    document: { getElementById: (id) => els[id] || null, createElement: () => ({ click() { log.saved.push(this.download); }, remove() {} }), body: { appendChild() {} } },
    URL: { createObjectURL: () => "blob:x", revokeObjectURL() {} },
    alert: (m) => log.alerts.push(m),
    prefillResumeHeader() {}, confirmHeaderDetails: () => true, startProcessingState() {}, stopProcessingState() {}, carryLayoutChoice() {},
    formatErrorDetail: (detail, fallback) => (typeof detail === "string" && detail ? detail : fallback),
    authedFetch: async (url, options) => { log.fetches.push(url); return server(url, options); },
  };
  vm.createContext(sandbox);
  vm.runInContext(read("js", "resumeDownload.js") + "\n" + read("js", "generalResume.js") + "\nthis.__state = generalResumeState;", sandbox);
  return { els, log, state: sandbox.__state };
}
const okServer = async () => ({ ok: true, blob: async () => ({}) });

test("Download with no resume built shows a plain inline message, no pop-up and no request", async () => {
  const w = generalWorld({ server: okServer });
  await w.els["general-resume-download-btn"].fire("click");
  assert.strictEqual(w.els["general-download-msg"].hidden, false);
  assert.match(w.els["general-download-msg"].textContent, /no resume to download yet/i);
  assert.deepStrictEqual(w.log.alerts, []);
  assert.deepStrictEqual(w.log.fetches, []);
});

test("a download saves First_Last_Resume.docx and clears an earlier message", async () => {
  const w = generalWorld({ server: okServer });
  w.state.resumeData = { name: "Casey Rowan" };
  w.els["general-download-msg"].hidden = false;
  w.els["general-download-msg"].textContent = "old";
  await w.els["general-resume-download-btn"].fire("click");
  assert.deepStrictEqual(w.log.saved, ["Casey_Rowan_Resume.docx"]);
  assert.strictEqual(w.els["general-download-msg"].hidden, true);
  assert.strictEqual(w.els["general-resume-download-btn"].disabled, false);
});

test("a failed download shows the server's words inline, keeps everything, and can simply be tried again", async () => {
  let fail = true;
  const w = generalWorld({ server: async () => (fail ? { ok: false, status: 503, json: async () => ({ detail: "The document service is busy. Please try again." }) } : { ok: true, blob: async () => ({}) }) });
  w.state.resumeData = { name: "Casey Rowan", summary: "kept" };
  w.els["general-resume-name"].value = "Casey Rowan";
  w.els["general-resume-contact"].value = "Naperville, IL";
  await w.els["general-resume-download-btn"].fire("click");
  assert.strictEqual(w.els["general-download-msg"].textContent, "The document service is busy. Please try again.");
  assert.strictEqual(w.els["general-download-msg"].hidden, false);
  assert.deepStrictEqual(w.log.alerts, []);
  assert.strictEqual(w.els["general-resume-download-btn"].disabled, false);
  assert.strictEqual(w.state.resumeData.summary, "kept");
  assert.strictEqual(w.els["general-resume-name"].value, "Casey Rowan");
  assert.strictEqual(w.els["general-resume-contact"].value, "Naperville, IL");
  fail = false;
  await w.els["general-resume-download-btn"].fire("click");
  assert.deepStrictEqual(w.log.saved, ["Casey_Rowan_Resume.docx"]);
  assert.strictEqual(w.els["general-download-msg"].hidden, true);
});

test("an error with no readable detail gets one plain sentence, not a status code", async () => {
  const w = generalWorld({ server: async () => ({ ok: false, status: 500, json: async () => { throw new Error("not json"); } }) });
  w.state.resumeData = { name: "Casey Rowan" };
  await w.els["general-resume-download-btn"].fire("click");
  assert.match(w.els["general-download-msg"].textContent, /couldn't prepare your download/i);
  assert.doesNotMatch(w.els["general-download-msg"].textContent, /500/);
});

// ---- the page and its files -----------------------------------------------------------------------------------------------
test("the resume workflow no longer uses pop-up alerts", () => {
  for (const file of ["generalResume.js", "jobMatch.js", "history.js"]) {
    const code = read("js", file).split("\n").filter((l) => !l.trim().startsWith("//")).join("\n");
    assert.doesNotMatch(code, /\balert\(/, file);
  }
});

test("the page has an announced message slot for each download button and loads the helper first", () => {
  const html = read("login.html");
  for (const id of ["general-download-msg", "job-download-msg", "resume-download-status"]) {
    assert.match(html, new RegExp(`<p class="error resume-download-msg" id="${id}" role="alert" hidden></p>`), id);
  }
  const at = (name) => html.indexOf(`<script src="js/${name}"></script>`);
  assert.ok(at("resumeDownload.js") > 0);
  for (const later of ["generalResume.js", "jobMatch.js", "history.js"]) assert.ok(at("resumeDownload.js") < at(later), later);
});

test("tailored and saved resumes put the job title in the file name", () => {
  assert.match(read("js", "jobMatch.js"), /resumeFileName\(jobState\.tailoredResumeData\.name, jobState\.jobTitle\)/);
  const history = read("js", "history.js");
  assert.match(history, /role: jobTitle \|\| ""/);
  assert.match(history, /downloadResumeVersion\(entry, \(entry\.resume_data \|\| \{\}\)\.name, layout\.value, info\.role\)/);
});

test("the small-screen styles keep the layout menu inside its card and the resume buttons 44 px tall", () => {
  const css = read("dashboard-v4.css");
  assert.match(css, /\.resume-layout-field select \{ width: 100%; max-width: 100%; min-width: 0; box-sizing: border-box; \}/);
  assert.match(css, /min-height: 44px !important;/);
});
