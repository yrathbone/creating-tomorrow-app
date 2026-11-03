// Inter on every public page (batch 2 of the site-wide review, 2026-11-03). Static checks only. Run:  node --test backend/tests/frontend
const test = require("node:test");
const assert = require("node:assert");
const fs = require("node:fs");
const path = require("node:path");

const FRONTEND = path.join(__dirname, "..", "..", "..", "frontend");
const read = (p) => fs.readFileSync(path.join(FRONTEND, p), "utf8");

test("Inter is the typeface on every public page (through the shared chrome), and the signed-in dashboard keeps its own type", () => {
  const chrome = read("chrome-v6.css");
  const tokens = chrome.match(/body\.chrome-v6:not\(\.dashboard-v4\) \{[\s\S]*?\n\}/)[0];
  assert.match(tokens, /--font-sans: "Inter",/);
  assert.match(tokens, /--font-serif: "Inter",/);
  assert.ok(!/Source Serif/.test(chrome), "no serif is named in the shared chrome");
  assert.ok(!/Inter/.test(read("career/dashboard-v4.css")), "the dashboard stylesheet is untouched");
  for (const w of [400, 500, 700]) {
    assert.match(chrome, new RegExp(`font-weight: ${w}; font-display: swap; src: url\\("fonts/inter-latin-${w}-normal\\.woff2"\\)`));
    assert.ok(fs.existsSync(path.join(FRONTEND, "fonts", `inter-latin-${w}-normal.woff2`)));
  }
  assert.ok(!/googleapis|gstatic/.test(chrome), "no outside fonts");
});
