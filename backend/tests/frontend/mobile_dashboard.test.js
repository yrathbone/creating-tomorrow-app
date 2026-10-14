// The signed-in dashboard on a phone. A plain 1fr grid column cannot shrink below its widest content, so on a 375px phone the cards
// were 538px wide and ran off the right edge (the page looked off-centre). Every dashboard grid column must be allowed to shrink.
const test = require("node:test");
const assert = require("node:assert");
const fs = require("node:fs");
const path = require("node:path");

const FRONTEND = path.join(__dirname, "..", "..", "..", "frontend");
const read = (...p) => fs.readFileSync(path.join(FRONTEND, ...p), "utf8");

test("every dashboard grid column can shrink below its content (minmax(0, 1fr)), on phones and tablets", () => {
  const css = read("style.css");
  const block = css.slice(css.indexOf(".dashboard-grid {"), css.indexOf(".dashboard-grid {") + 900);
  assert.match(block, /grid-template-columns: minmax\(0, 1fr\);/, "phone: one shrinkable column");
  assert.match(css, /\.dashboard-grid \{ grid-template-columns: minmax\(0, 1fr\) minmax\(0, 1fr\); \}/, "tablet: two shrinkable columns");
  assert.ok(!/\.dashboard-grid \{[^}]*grid-template-columns: 1fr(?: 1fr)?;/.test(css), "no plain 1fr dashboard column is left");
  const dash = read("career", "dashboard-v4.css");
  assert.match(dash, /\.dashboard-grid \{ grid-template-columns: repeat\(12, minmax\(0, 1fr\)\); \}/, "desktop: twelve shrinkable columns");
});
