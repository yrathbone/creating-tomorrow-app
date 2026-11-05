// Visual consistency (2026-11-04 scan): 16px form fields, 44px dashboard tap targets, equal count tiles.
// Intentional differences stay: the smaller About/Spotlight page titles and the homepage's denser body text are not touched here.
const test = require("node:test");
const assert = require("node:assert");
const fs = require("node:fs");
const path = require("node:path");

const FRONTEND = path.join(__dirname, "..", "..", "..", "frontend");
const read = (...p) => fs.readFileSync(path.join(FRONTEND, ...p), "utf8");
const chrome = read("chrome-v6.css");
const v8 = read("career", "dashboard-v8.css");

test("public form fields are 16px (a phone browser zooms a page when a field under 16px is focused)", () => {
  assert.match(chrome, /body\.chrome-v6:not\(\.dashboard-v4\) input:not\(\[type="checkbox"\]\)[^{]*\{ font-size: 1rem; \}/);
  assert.match(chrome, /body\.chrome-v6:not\(\.dashboard-v4\) textarea \{ font-size: 1rem; \}/);
  assert.match(chrome, /body\.chrome-v6:not\(\.dashboard-v4\) select \{ font-size: 1rem; \}/);
});

test("the signed-in dashboard has 16px fields too, and file, checkbox and radio inputs are left alone", () => {
  assert.match(v8, /body\.chrome-v6\.dashboard-v4 input:not\(\[type="checkbox"\]\):not\(\[type="radio"\]\):not\(\[type="file"\]\)[^{]*\{ font-size: 1rem; \}/);
  assert.match(v8, /body\.chrome-v6\.dashboard-v4 textarea \{ font-size: 1rem; \}/);
  assert.match(v8, /body\.chrome-v6\.dashboard-v4 select \{ font-size: 1rem; \}/);
});

test("dashboard header links, brand link, main buttons and button-style links are at least 44px tall; count tiles and inline link buttons are excluded", () => {
  assert.match(v8, /body\.chrome-v6\.dashboard-v4 \.nav-links a \{[^}]*min-height: 44px; \}/);
  assert.match(v8, /body\.chrome-v6\.dashboard-v4 \.nav-logo \{[^}]*min-height: 44px; \}/);
  assert.match(v8, /body\.chrome-v6\.dashboard-v4 main button:not\(\.stat-card\):not\(\.link-button\) \{ min-height: 44px !important; \}/);
  assert.match(v8, /body\.chrome-v6\.dashboard-v4 main a\.btn-secondary \{[^}]*min-height: 44px !important; \}/);
});

test("the five count tiles share the row equally (no stray left margin on the tiles after the first)", () => {
  assert.match(v8, /body\.chrome-v6\.dashboard-v4 \.snapshot-card \.stat-row \.stat-card \{ margin: 0; \}/);
});

test("the intentional page-title sizes are untouched: About and Spotlight keep the section-heading size, the others the page-title size", () => {
  const pages = read("pages-v4.css");
  assert.match(pages, /body\.pages-v4\.spotlight-page \.page-header h1 \{ font-size: var\(--fs-h2\); \}/);
  assert.match(pages, /body\.pages-v4 \.about-hero h1 \{ font-size: var\(--fs-h2\)/);
  assert.match(pages, /\.page-header h1 \{[^}]*font-size: var\(--fs-h1\)/);
});

test("no new colours or font families were added by this change", () => {
  const added = (chrome.split("form fields: 16px")[1] || "") + (v8.split("signed-in dashboard: 16px fields")[1] || "");
  assert.ok(added.length > 200, "found the new blocks");
  assert.ok(!/#[0-9a-fA-F]{3,6}\b/.test(added), "no colour values");
  assert.ok(!/font-family/.test(added), "no font family");
});
