// The dashboard is one box (like the homepage): the hero, the profile strip and the four cards share
// one panel, and the hidden editor stays outside it. Static checks only.
// Run:  node --test backend/tests/frontend
const test = require("node:test");
const assert = require("node:assert");
const fs = require("node:fs");
const path = require("node:path");

const CAREER = path.join(__dirname, "..", "..", "..", "frontend", "career");
const html = fs.readFileSync(path.join(CAREER, "login.html"), "utf8");
const css = fs.readFileSync(path.join(CAREER, "dashboard-v4.css"), "utf8");

test("the hero, the profile strip and all four cards are inside one panel, and the editor is outside it", () => {
  const open = html.indexOf('<div class="dash-panel">');
  const close = html.indexOf('<section class="card" id="career-profile-editor"');
  assert.ok(open > -1 && close > open);
  const inside = html.slice(open, close);
  for (const marker of ['id="dashboard-top"', 'class="cp-status"', 'class="dashboard-grid"', "job-card", 'id="general-resume-card"', "profile-card", "activity-card"]) {
    assert.ok(inside.includes(marker), `${marker} should be inside the panel`);
  }
  assert.strictEqual((inside.match(/<div/g) || []).length - (inside.match(/<\/div>/g) || []).length, 0, "the panel is balanced");
  assert.ok(!inside.includes("career-profile-editor"));
});

test("inside the panel the cards are thin-line sections, not boxes (and every id the scripts use is still there)", () => {
  assert.match(css, /\.dash-panel > \.dashboard-grid > \.card \{[^}]*box-shadow: none/);
  assert.match(css, /\.dash-panel > \.dashboard-grid > #general-resume-card \{ border-top-color/);
  for (const id of ["job-download-btn", "general-resume-download-btn", "application-list", "scan-history-list", "resume-version-list", "skill-detail-list", "language-detail-list", "edit-profile-btn"]) {
    assert.ok(html.includes(`id="${id}"`), `missing #${id}`);
  }
});
