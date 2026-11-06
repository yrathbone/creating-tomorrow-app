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

test("the older per-page title sizes are still in pages-v4.css, but one standard title size now overrides them on every inner page", () => {
  const pages = read("pages-v4.css");
  assert.match(pages, /body\.pages-v4\.spotlight-page \.page-header h1 \{ font-size: var\(--fs-h2\); \}/); // superseded, not removed
  const block = chrome.slice(chrome.indexOf("one standard size scale on every inner page"), chrome.indexOf("one type scale on the public pages"));
  assert.match(block, /--c6-title: clamp\(1\.75rem, 1\.3rem \+ 1\.6vw, 2\.5rem\)/);
  for (const sel of [".page-header h1", ".pv-head h1", ".doc-hero h1", ".about-hero h1", ".ats-header h1", ".h5-notfound h1"]) {
    assert.ok(block.includes("body.chrome-v6:not(.dashboard-v4):not(.home-v7) " + sel), sel + " uses the standard title");
  }
  assert.match(block, /font-size: var\(--c6-title\)/);
});

test("one section-heading size (24px) and one body size (16px) on the content pages, and the homepage hero is left alone", () => {
  const block = chrome.slice(chrome.indexOf("one standard size scale on every inner page"), chrome.indexOf("one type scale on the public pages"));
  assert.match(block, /--c6-section: 1\.5rem/);
  assert.match(block, /--c6-body: 1rem/);
  for (const sel of [".doc-main h2", ".pv-band h2", ".pv-band .hv-h2", ".ats-body h2"]) assert.ok(block.includes(sel), sel);
  assert.ok(!/home-v7[^{]*h1/.test(block.replace(/:not\(\.home-v7\)/g, "")), "no rule targets the homepage title");
  for (const line of block.split(/\r?\n/).filter((l) => /\{/.test(l) && !l.startsWith("@media") && !l.trim().startsWith("/*"))) {
    assert.ok(/^\s*body\.chrome-v6:not\(\.dashboard-v4\)/.test(line) || line.startsWith("body.chrome-v6:not(.dashboard-v4)"), line);
  }
});

test("a compact header at 768px and below on the public pages and on the dashboard, with the 44px tap height kept", () => {
  const pub = chrome.slice(chrome.indexOf("a compact header on a tablet and a phone"), chrome.indexOf("one type scale on the public pages"));
  assert.match(pub, /@media \(max-width: 768px\)/);
  assert.match(pub, /\.site-nav \{ padding: 0\.5rem 1rem;/);
  assert.ok(!/min-height/.test(pub), "the compact header never lowers a tap height");
  const dash = v8.slice(v8.indexOf("the same compact header as the public pages"));
  assert.match(dash, /@media \(max-width: 768px\)/);
  for (const line of dash.split(/\r?\n/).filter((l) => /\{/.test(l) && !l.startsWith("@media") && !l.startsWith("/*"))) {
    assert.ok(line.trim().startsWith("body.chrome-v6.dashboard-v4"), line);
  }
  assert.match(chrome, /\.nav-links a \{ display: inline-flex; align-items: center; min-height: 44px; \}/);
});

test("no new colours or font families were added by this change", () => {
  const added = (chrome.split("form fields: 16px")[1] || "") + (v8.split("signed-in dashboard: 16px fields")[1] || "") +
    chrome.slice(chrome.indexOf("one standard size scale on every inner page"), chrome.indexOf("one type scale on the public pages"));
  assert.ok(added.length > 200, "found the new blocks");
  assert.ok(!/#[0-9a-fA-F]{3,6}\b/.test(added), "no colour values");
  assert.ok(!/font-family/.test(added), "no font family");
});
