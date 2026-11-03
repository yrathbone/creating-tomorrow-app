// No bold on the public pages (2026-11-03): one override block at the end of the shared chrome (chrome-v6.css). Static checks only.
const test = require("node:test");
const assert = require("node:assert");
const fs = require("node:fs");
const path = require("node:path");

const FRONTEND = path.join(__dirname, "..", "..", "..", "frontend");
const read = (p) => fs.readFileSync(path.join(FRONTEND, p), "utf8");

test("the shared chrome sets regular weight everywhere on the public pages, medium for clickable things, and keeps the logo lettering", () => {
  const css = read("chrome-v6.css");
  const block = css.slice(css.indexOf("no bold on the public pages"));
  const S = "body.chrome-v6:not(.dashboard-v4)";
  assert.ok(block.includes(`${S} * { font-weight: 400 !important; }`));
  assert.match(block, /button,[^{]*\.btn-crimson,[^{]*\.h5-btn,[^{]*\.h7-btn,[^{]*\.nav-links a,[^{]*\.h7-link,[^{]*\.hv-vfoot \{ font-weight: 500 !important; \}/);
  assert.match(block, /p strong,[^{]*li b,[^{]*li strong \{ font-weight: 500 !important; \}/);
  assert.match(block, /\.nav-wordmark \* \{ font-weight: 700 !important; \}/);
  // only the three medium and regular weights appear in the block
  const weights = [...block.matchAll(/font-weight:\s*(\d+)/g)].map((m) => m[1]);
  assert.deepStrictEqual([...new Set(weights)].sort(), ["400", "500", "700"]);
});

test("the override is scoped to the public pages: every selector in it names the chrome and excludes the dashboard, and the dashboard stylesheet is untouched", () => {
  const css = read("chrome-v6.css");
  const block = css.slice(css.indexOf("/* ---------- no bold on the public pages")).replace(/\/\*[\s\S]*?\*\//g, "");
  for (const rule of block.split("}").map((r) => r.split("{")[0].trim()).filter(Boolean)) {
    for (const sel of rule.split(",").map((s) => s.trim())) assert.ok(sel.startsWith("body.chrome-v6") && sel.includes(":not(.dashboard-v4)"), sel);
  }
  assert.ok(!read("career/dashboard-v4.css").includes("no bold"));
});
