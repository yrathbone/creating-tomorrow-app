// The notice shown when the truth checks leave statements out of a tailored resume, or hold lines back for the candidate's confirmation.
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
  const make = () => ({ textContent: "", hidden: true, children: [], appendChild(c) { this.children.push(c); } });
  const nodes = { "job-truth-notice": make(), "job-truth-message": make(), "job-truth-held-message": make(), "job-truth-held": make() };
  const sandbox = {
    document: {
      getElementById: (id) => nodes[id] || null,
      createElement: () => ({ textContent: "" }),
    },
  };
  // textContent = "" on the list clears its children, like the browser
  Object.defineProperty(nodes["job-truth-held"], "textContent", { get() { return ""; }, set() { nodes["job-truth-held"].children = []; } });
  vm.createContext(sandbox);
  vm.runInContext(source.slice(start, end), sandbox);
  return { nodes, render: (n) => sandbox.renderTruthNotice(n) };
}

test("the finished-resume state has a polite status region for the notice, hidden until needed", () => {
  const done = html.slice(html.indexOf('id="job-build-done-state"'));
  assert.match(done, /<div id="job-truth-notice" class="hint" role="status" hidden>/);
  for (const id of ["job-truth-message", "job-truth-held-message", "job-truth-held"]) assert.ok(done.includes(`id="${id}"`), id);
  assert.ok(done.indexOf('id="job-truth-notice"') < done.indexOf('id="job-resume-template"'), "it sits at the top of the finished state");
});

test("it shows the server's message, and nothing when nothing was left out or held", () => {
  const { nodes, render } = renderer();
  const message = "We left out 2 statements we couldn\u2019t verify. Review your experience to make sure nothing important is missing.";
  render({ count: 2, message, held: [], held_message: "" });
  assert.strictEqual(nodes["job-truth-message"].textContent, message);
  assert.strictEqual(nodes["job-truth-notice"].hidden, false);
  assert.strictEqual(nodes["job-truth-held"].hidden, true);
  render({ count: 0, message: "", held: [], held_message: "" });
  assert.strictEqual(nodes["job-truth-notice"].hidden, true);
  render(undefined);
  assert.strictEqual(nodes["job-truth-notice"].hidden, true);
  render({ count: 3 }); // no message: nothing invented
  assert.strictEqual(nodes["job-truth-notice"].hidden, true);
});

test("held lines are listed word for word, with what the candidate wrote, and are never shown as verified", () => {
  const { nodes, render } = renderer();
  render({
    count: 0, message: "",
    held: [{ text: "Led unit planning that cut prep time by 20%.", said: "helped" }, { text: "Oversaw the budget.", said: "" }],
    held_message: "We held 2 lines out of your r\u00e9sum\u00e9 until you confirm them. They use stronger wording than you gave us, so they are not in your Word file yet.",
  });
  assert.strictEqual(nodes["job-truth-notice"].hidden, false);
  assert.strictEqual(nodes["job-truth-message"].hidden, true);
  assert.match(nodes["job-truth-held-message"].textContent, /^We held 2 lines out of your r\u00e9sum\u00e9/);
  assert.deepStrictEqual(nodes["job-truth-held"].children.map((c) => c.textContent),
    ["Led unit planning that cut prep time by 20%. (you wrote: \u201chelped\u201d)", "Oversaw the budget."]);
  assert.strictEqual(nodes["job-truth-held"].hidden, false);
  render({ count: 0, message: "", held: [], held_message: "" });  // a later build clears it
  assert.strictEqual(nodes["job-truth-notice"].hidden, true);
  assert.deepStrictEqual(nodes["job-truth-held"].children, []);
});

test("a build shows the notice from the response", () => {
  assert.match(source, /renderTruthNotice\(data\.truth_notice \|\|/);
});
