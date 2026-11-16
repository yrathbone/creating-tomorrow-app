// Node regression tests for the member résumé review rules (frontend/career/js/resumeTruthModel.js).
// Run from the backend folder:  node --test tests/frontend/resumeTruthModel.test.js
const test = require("node:test");
const assert = require("node:assert/strict");
const path = require("node:path");
const model = require(path.join(__dirname, "..", "..", "..", "frontend", "career", "js", "resumeTruthModel.js"));

test("sections group the server's review by what the member must do", () => {
  const review = {
    items: [
      { id: "a", classification: "UNCERTAIN", where: "summary[1]", text: "x" },
      { id: "b", classification: "UNSUPPORTED", where: "skills[0]", text: "y" },
    ],
    supported: [{ text: "Record keeping", source: "saved skill" }],
    derived: [{ text: "Process Improvement", source: "saved role" }],
    removed: [{ text: "Certified in customer service", explanation: "Not in your saved information." }],
  };
  const s = model.truthSections(review);
  assert.equal(s.uncertain.length, 1);
  assert.equal(s.unsupported.length, 1);
  assert.equal(s.supported.length, 1);
  assert.equal(s.derived[0].source, "saved role");
  assert.equal(s.removed.length, 1);
});

test("only uncertain wording offers Keep, Edit and Remove; unsupported wording offers nothing", () => {
  assert.deepEqual(model.allowedActions({ classification: "UNCERTAIN" }), ["keep", "edit", "remove"]);
  assert.deepEqual(model.allowedActions({ classification: "UNSUPPORTED" }), []);
  assert.deepEqual(model.allowedActions({ classification: "SUPPORTED" }), []);
  assert.deepEqual(model.allowedActions(null), []);
});

test("decision wording is plain for each state", () => {
  assert.equal(model.describeDecision({}), "Not decided yet");
  assert.equal(model.describeDecision({ decision: "keep" }), "You kept this wording");
  assert.equal(model.describeDecision({ decision: "remove" }), "Removed by you: excluded from the final document. It stays here as history.");
});

test("edit limits match the server: non-empty, at most 300 characters, changed, no pipe in a headline", () => {
  assert.match(model.editProblem("   ", "Old wording", "summary[1]"), /Write the statement/);
  assert.match(model.editProblem("x".repeat(301), "Old wording", "summary[1]"), /under 300/);
  assert.match(model.editProblem("Old   wording", "Old wording", "summary[1]"), /not changed/);
  assert.match(model.editProblem("Coordinator | Records", "Records", "headline[0]"), /without the/);
  assert.equal(model.editProblem("A new, checked wording.", "Old wording", "summary[1]"), "");
  assert.equal(model.EDIT_LIMIT, 300);
});

test("sign-off is offered only when every statement is decided, previewed, confirmed and no edit is open", () => {
  const ready = { status: "ready", previewed: true, checked: true, editing: false };
  assert.equal(model.canSignOff(ready), true);
  assert.equal(model.canSignOff({ ...ready, status: "needs_review" }), false);
  assert.equal(model.canSignOff({ ...ready, previewed: false }), false);
  assert.equal(model.canSignOff({ ...ready, checked: false }), false);
  assert.equal(model.canSignOff({ ...ready, editing: true }), false);
  assert.equal(model.canSignOff(null), false);
});

// C-52 stabilization (Data 2026-11-15): F2 dedupe keeps every source; F8 sign-off reason.
test("F2: a supported row that repeats the same wording is shown once, with every saved source", () => {
  const rows = model.dedupeSupported([
    { text: "Team leadership", source: 'saved skill "Team leadership"' },
    { text: "Team Leadership", source: 'saved skill "Team leadership"' },
    { text: "Team leadership", source: 'job term "Team leadership": led a team' },
    { text: "Excel", source: 'saved skill "Excel"' },
  ]);
  assert.equal(rows.length, 2);
  assert.equal(rows[0].text, "Team leadership");
  assert.match(rows[0].source, /saved skill "Team leadership"; job term "Team leadership"/);
  assert.equal(rows[1].text, "Excel");
});

test("F8: sign-off names the reason it is not available, and nothing when it is", () => {
  assert.match(model.signOffBlocker({ status: "pending", previewed: false, checked: false, editing: false }), /Decide every statement/);
  assert.match(model.signOffBlocker({ status: "ready", previewed: false, checked: false, editing: false }), /Preview the whole resume first/);
  assert.match(model.signOffBlocker({ status: "ready", previewed: true, checked: false, editing: false }), /Tick the box/);
  assert.match(model.signOffBlocker({ status: "ready", previewed: true, checked: true, editing: true }), /Save or cancel your wording/);
  assert.equal(model.signOffBlocker({ status: "ready", previewed: true, checked: true, editing: false }), "");
});
