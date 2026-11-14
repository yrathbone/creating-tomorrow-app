const test = require("node:test");
const assert = require("node:assert");
const fs = require("node:fs");
const path = require("node:path");

// Integrated dashboard layout: Discover Your Fit and Showcase your experience sit side by side, My Opportunities
// is beneath them, and the job discovery card (feature-gated) comes after My Opportunities. Only the order changed.
const FRONTEND = path.join(__dirname, "..", "..", "..", "frontend");
const html = fs.readFileSync(path.join(FRONTEND, "career", "login.html"), "utf8");
const grid = html.slice(html.indexOf('<div class="dashboard-grid">'), html.indexOf('<section id="privacy-note"'));

function openTagAt(id) {
  const at = grid.indexOf('id="' + id + '"');
  assert.ok(at > 0, "missing element " + id);
  return grid.slice(grid.lastIndexOf("<div", at), grid.indexOf(">", at) + 1);
}

test("the dashboard order is Discover, Showcase, My Opportunities, then job discovery, then My Career", () => {
  const order = ['class="card span-2 job-card"', 'id="general-resume-card"', 'id="opportunities-card"', 'id="discovery-card"', 'class="card span-2 snapshot-card profile-card"']
    .map((needle) => {
      const at = grid.indexOf(needle);
      assert.ok(at > 0, "missing " + needle);
      return at;
    });
  assert.deepStrictEqual(order, [...order].sort((a, b) => a - b), "blocks are out of order: " + order.join(", "));
});

test("My Opportunities and job discovery stay hidden until the server confirms the feature for this member", () => {
  assert.match(openTagAt("opportunities-card"), /\shidden>/, "My Opportunities must start hidden");
  assert.match(openTagAt("discovery-card"), /\shidden>/, "job discovery must start hidden");
});

test("no sample-data, preview or demonstration copy is left in the dashboard", () => {
  for (const phrase of ["sample data", "Preview only", "Illustrative", "demonstration", "Placement concept", "Layout preview"]) {
    assert.ok(!grid.toLowerCase().includes(phrase.toLowerCase()), "found leftover copy: " + phrase);
  }
});
