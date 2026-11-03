const test = require("node:test");
const assert = require("node:assert");
const fs = require("node:fs");
const path = require("node:path");

const css = fs.readFileSync(path.join(__dirname, "..", "..", "..", "frontend", "chrome-v6.css"), "utf8");

test("footer links are at least 44px tall and wide", () => {
  const i = css.indexOf("footer links: tap targets");
  assert.ok(i > 0, "tap-target block is present");
  const block = css.slice(i);
  assert.match(block, /\.footer-links a[^{]*\{[^}]*min-height: 44px/);
  assert.match(block, /\.footer-links a[^{]*\{[^}]*min-width: 44px/);
  assert.match(block, /\.h5-footer-nav a[^{]*\{[^}]*min-height: 44px/);
});

test("the tap-target rules leave the dashboard alone", () => {
  const block = css.slice(css.indexOf("footer links: tap targets"));
  for (const line of block.split("\n").filter((l) => l.includes("{"))) {
    assert.ok(line.startsWith("body.chrome-v6:not(.dashboard-v4)"), line);
  }
});
