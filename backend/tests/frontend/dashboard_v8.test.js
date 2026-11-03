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

test("Sign Out is a gold button with navy text, never white on white", () => {
  assert.match(css, /\.nav-links a\.nav-signout \{ background: var\(--c6-gold\); border-color: var\(--c6-gold\); color: #071c42;/);
  assert.match(css, /\.nav-links a\.nav-signout:hover \{ background: var\(--c6-gold-hover\)/);
  assert.ok(!/nav-signout[^}]*background: #ffffff/.test(css), "no white background on Sign Out");
});

test("the signed-in dashboard uses the founder-approved copy, word for word", () => {
  const html = read("career", "login.html");
  const next = read("career", "js", "nextStep.js");
  for (const line of [
    "<p>See Your Value. Build Your Tomorrow.</p>",
    '<p class="hint">Showcase Your Experience</p>',
    '<p class="hint">Your Experience Matters.</p>',
    '<p class="hint">Discover Your Fit</p>',
    '<p class="hint export-hint">Readable Copy: Read, print, or share.</p>',
    '<p class="hint">See Your Progress.</p>',
    '<p class="hint">Help us grow. Share your experience, not your private information.</p>',
    '<p class="hint">Download your information or choose to delete your account anytime.</p>',
  ]) assert.ok(html.includes(line), line);
  // the application tracker step is one line: a title only (founder-approved "Track Your Applications"), no sentence under it
  assert.ok(next.includes('title: "Track Your Applications",'));
  assert.match(next, /key: "track-application", title: "Track Your Applications",\s+text: "",/);
  assert.ok(next.includes('textEl.hidden = !step.text'));
  // the headings and controls are unchanged
  for (const keep of ["Your Career,", "General Resume", "My Career", "Your Activity", "Tell us how it went", "Your Data",
    'id="export-readable-btn"', 'id="export-profile-btn"', 'id="delete-account-start-btn"', 'id="feedback-link"']) {
    assert.ok(html.includes(keep), keep);
  }
});

test("the dashboard makes no restore, transfer or completeness promise about the data backup", () => {
  const html = read("career", "login.html");
  // the founder removed the old explanation; the site has no import feature and the backup omits the resume header
  assert.ok(!html.includes("Data Backup:"), "no Data Backup explanation");
  assert.ok(!html.includes("Your Files. Your Choice."), "no download heading");
  assert.ok(!/restor|transfer your|import your/i.test(html.slice(html.indexOf('id="export-readable-btn"') - 200, html.indexOf('id="export-profile-btn"') + 600)));
});

test("the next-step band is plain white with a smaller sentence, no yellow wash or gold edge", () => {
  const rule = css.match(/body\.chrome-v6\.dashboard-v4 \.next-step \{[^}]*\}/)[0];
  assert.match(rule, /background: #ffffff/);
  assert.match(rule, /box-shadow: none/);
  assert.ok(!/gold|ffb000|fdf8ea/i.test(rule), "no yellow in the band rule");
  assert.match(css, /\.next-step p#next-step-text \{ font-size: 0\.84rem;/);
});

test("every next-step sentence is one short line (60 characters or fewer)", () => {
  const src = read("career", "js", "nextStep.js");
  const sentences = src.split("\n")
    .map((line) => line.match(/^\s*text: (.*?),\s*$/))
    .filter(Boolean)
    .map((m) => new Function("STALE_APPLICATION_DAYS", "return " + m[1])(14));
  assert.ok(sentences.length >= 10, "found the sentences: " + sentences.length);
  for (const text of sentences) assert.ok(text.length <= 60, text.length + " characters: " + text);
});
