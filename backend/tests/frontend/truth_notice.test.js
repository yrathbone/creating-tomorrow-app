// The one-line notice shown when the truth checks leave statements out of a tailored resume.
const test = require("node:test");
const assert = require("node:assert");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const FRONTEND = path.join(__dirname, "..", "..", "..", "frontend", "career");
const html = fs.readFileSync(path.join(FRONTEND, "login.html"), "utf8");
const source = fs.readFileSync(path.join(FRONTEND, "js", "jobMatch.js"), "utf8");

function renderer() {
  const start = source.indexOf("function renderTruthNotice(notice)");
  const end = source.indexOf("function resetAppliedBlock()");
  assert.ok(start > 0 && end > start, "renderTruthNotice is defined");
  const el = { textContent: "", hidden: true };
  const sandbox = { document: { getElementById: (id) => (id === "job-truth-notice" ? el : null) } };
  vm.createContext(sandbox);
  vm.runInContext(source.slice(start, end), sandbox);
  return { el, render: (n) => sandbox.renderTruthNotice(n) };
}

test("the finished-resume state has a polite status line for the notice, hidden until needed", () => {
  const done = html.slice(html.indexOf('id="job-build-done-state"'));
  assert.match(done, /<p id="job-truth-notice" class="hint" role="status" hidden><\/p>/);
  assert.ok(done.indexOf('id="job-truth-notice"') < done.indexOf('id="job-resume-template"'), "it sits at the top of the finished state");
});

test("it shows the server's message and count, and nothing when nothing was left out", () => {
  const { el, render } = renderer();
  const message = "We left out 2 statements we couldn’t verify. Review your experience to make sure nothing important is missing.";
  render({ count: 2, message });
  assert.strictEqual(el.textContent, message);
  assert.strictEqual(el.hidden, false);
  render({ count: 0, message: "" });
  assert.strictEqual(el.hidden, true);
  assert.strictEqual(el.textContent, "");
  render(undefined);
  assert.strictEqual(el.hidden, true);
  render({ count: 3 }); // no message: nothing invented
  assert.strictEqual(el.hidden, true);
});

test("a build shows the notice from the response", () => {
  assert.match(source, /renderTruthNotice\(data\.truth_notice \|\|/);
});
