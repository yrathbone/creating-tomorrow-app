const test = require("node:test");
const assert = require("node:assert");
const fs = require("node:fs");
const path = require("node:path");

const FRONTEND = path.join(__dirname, "..", "..", "..", "frontend");
const read = (...p) => fs.readFileSync(path.join(FRONTEND, ...p), "utf8");
const css = read("career", "dashboard-v8.css");
const html = read("career", "login.html");

// the selectors of every rule, including those inside @media blocks, without the comments
function selectors(source) {
  const text = source.replace(/\/\*[\s\S]*?\*\//g, "");
  const out = [];
  const re = /([^{}]+)\{([^{}]*)\}/g;
  let m;
  while ((m = re.exec(text))) {
    const head = m[1].trim();
    if (head.startsWith("@media")) continue;
    for (const sel of head.split(",")) out.push(sel.trim().replace(/^@media[^{]*\{/, "").trim());
  }
  return out.filter(Boolean);
}

test("the dashboard loads the new stylesheet after the shared chrome and its own v4 file", () => {
  const order = ["../style.css", "dashboard-v4.css", "auth-v5.css", "../chrome-v6.css", "dashboard-v8.css"].map((n) => html.indexOf(`href="${n}"`));
  assert.ok(order.every((i) => i > 0), "all five stylesheets are linked");
  assert.deepStrictEqual([...order].sort((a, b) => a - b), order, "dashboard-v8.css comes last");
});

test("every rule is scoped to the signed-in dashboard, so the sign-in screens and public pages are untouched", () => {
  const sels = selectors(css);
  assert.ok(sels.length > 30, "the file has real rules");
  for (const sel of sels) assert.ok(sel.startsWith("body.chrome-v6.dashboard-v4"), sel);
});

test("the dashboard uses the site's royal blue, amber gold, ink and Inter", () => {
  const tokens = css.match(/body\.chrome-v6\.dashboard-v4 \{[\s\S]*?\n\}/)[0];
  for (const want of ["--v4-blue: #003395", "--v4-gold: #ffb000", "--c6-blue: #003395", "--c6-gold: #ffb000", "--v4-ink: #0b1f4d", '--font-serif: "Inter"', '--font-sans: "Inter"']) {
    assert.ok(tokens.includes(want), want);
  }
  assert.ok(!/#0a35a8|#efae09/i.test(css), "the old dashboard blue and gold are gone");
});

test("the header and footer are the public ones: royal-blue bar, gold account button, 44px footer links", () => {
  assert.match(css, /\.site-nav \{ background: var\(--c6-blue\)/);
  assert.match(css, /\.nav-links a\.nav-account \{ background: var\(--c6-gold\)/);
  assert.match(css, /\.footer-links a \{[^}]*min-height: 44px/);
  assert.match(css, /\.h5-footer-nav a,[\s\S]*?min-width: 44px/);
});

test("no bold: regular text, medium buttons and nav, bold logo lettering only", () => {
  assert.match(css, /body\.chrome-v6\.dashboard-v4 \* \{ font-weight: 400 !important; \}/);
  assert.match(css, /\.btn-danger[\s\S]*?\{ font-weight: 500 !important; \}/);
  assert.match(css, /\.nav-wordmark \* \{ font-weight: 700 !important; \}/);
});

test("the older dashboard and public-page stylesheets are not touched", () => {
  assert.ok(!/Inter/.test(read("career", "dashboard-v4.css")));
  assert.ok(read("chrome-v6.css").includes(":not(.dashboard-v4)"));
});
