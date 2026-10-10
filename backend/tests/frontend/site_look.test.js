// The v5 look (homepage language) carried to every other page: shared footer, no nav arrow, scoped sign-in styling.
const test = require("node:test");
const assert = require("node:assert");
const fs = require("fs");
const path = require("path");

const FE = path.join(__dirname, "..", "..", "..", "frontend");
const read = (p) => fs.readFileSync(path.join(FE, p), "utf8");
const PAGES = ["about", "accessibility", "article", "contact", "elevate", "learn", "prepare", "privacy", "scratch", "spotlight", "terms", "tool", "videos", "career/login", "career/register", "not-found"].map((p) => p + ".html");

test("every inner page uses the homepage footer and the plain Career Tools link", () => {
  for (const p of PAGES) {
    const html = read(p);
    assert.match(html, /<footer class="h5-footer">/, `${p} has the new footer`);
    assert.match(html, /© 2026 Creating Tomorrow\. All rights reserved\./, `${p} has the copyright line`);
    for (const l of ["privacy.html", "terms.html", "accessibility.html", "contact.html"]) assert.ok(html.includes(l), `${p} links ${l}`);
    assert.ok(!html.includes("Career Tools →"), `${p} has no nav arrow`);
  }
});

test("sign-in and sign-up styling is scoped so the dashboard keeps its own look", () => {
  const css = read("career/auth-v5.css");
  for (const html of [read("career/login.html"), read("career/register.html")]) {
    assert.match(html, /<body[^>]*class="[^"]*auth-v5/);
    assert.match(html, /auth-v5\.css/);
  }
  const rules = css.replace(/\/\*[\s\S]*?\*\//g, "").split("}").map((r) => r.split("{")[0].trim()).filter(Boolean);
  for (const sel of rules) {
    if (sel.startsWith("@") || sel.startsWith("body.auth-v5") || sel.startsWith(".h5-footer")) continue;
    assert.fail(`unscoped selector in auth-v5.css: ${sel}`);
  }
});

test("the 404 page uses the homepage stylesheet", () => {
  const html = read("not-found.html");
  assert.match(html, /<body class="home-v5">/);
  assert.match(html, /home-v5\.css/);
});

test("the signed-in dashboard uses the locked palette: flat, two-tone icons, no leftover purple, pink or green tile colours", () => {
  const css = read("career/dashboard-v4.css");
  assert.match(css, /v6 LOCKED PALETTE/);
  for (const [name, hex] of Object.entries({ "v4-ink": "#071c42", "v4-blue": "#0756ed", "v4-gold": "#ffbc00", "v4-gold-text": "#a66b00", "v4-line": "#e2e8f0", "v4-cream": "#f2f5f8", "v4-muted": "#596b85" })) {
    const all = [...css.matchAll(new RegExp(`--${name}:\\s*(#[0-9a-fA-F]{6})`, "g"))].map((m) => m[1].toLowerCase());
    assert.strictEqual(all[all.length - 1], hex, `--${name} ends as ${hex}`);
  }
  for (const gone of ["6d28d9", "be185d", "%236d28d9", "%23be185d", "%23047857", "%23b45309"]) assert.ok(!css.includes(gone), `leftover colour ${gone}`);
  assert.match(css, /--v4-shadow: none/);
  assert.match(css, /\.next-step \{ background: var\(--v4-gold-wash\); background-image: none; \}/);
});

test("the Career Tools page is all white with a cobalt header and a cobalt strip at the foot, and no other page is touched", () => {
  const html = read("tool.html");
  assert.match(html, /<body class="pages-v4 tool-hub">/);
  for (const other of ["learn.html", "videos.html", "about.html", "elevate.html", "prepare.html", "scratch.html", "spotlight.html"]) assert.ok(!read(other).includes("tool-hub"), other);
  const css = read("pages-v4.css");
  const rules = css.split("\n").filter((l) => l.includes("tool-hub"));
  assert.ok(rules.length >= 10, "the page has its own rules");
  for (const l of rules) assert.ok(/^\s*(body\.pages-v4\.tool-hub|\/\*)/.test(l), "every rule is scoped to the page: " + l.slice(0, 70));
  assert.match(css, /body\.pages-v4\.tool-hub \{ --pale: #ffffff; --blue: #0052f5; --blue-deep: #0043c9; --gold: #ffb300; --gold-hover: #f2a400; background: #ffffff; \}/);
  assert.match(css, /body\.pages-v4\.tool-hub \.h5-footer-privacy \{ color: #000000; \}/);
  assert.match(css, /\.h5-footer-privacy \.h5-nosave \{ text-decoration: underline;/);
  assert.match(css, /\.footer-links a:nth-of-type\(-n\+2\) \{ color: #c8102e; \}/);
  assert.match(html, /<p class="h5-footer-privacy"><span class="h5-nosave">We don't save your resume<\/span> or job posting/);
  assert.match(css, /tool-hub \.h5-footer-brand \{ order: 2; \}/);
  assert.match(css, /tool-hub \.h5-footer-nav \{ order: 1; margin-right: auto; \}/);
  assert.match(css, /body\.pages-v4\.tool-hub \.page-header h1 \{ color: var\(--blue\); \}/);
  assert.match(css, /body\.pages-v4\.tool-hub \.site-nav \{ background: var\(--blue\); border-bottom: 0; \}/);
  assert.match(css, /footer\.h5-footer::after \{ content: ""; display: block; height: 3\.25rem; margin-top: 2\.25rem; background: var\(--blue\); \}/);
  // the header recolouring must not leak into the footer's wordmark (white on white once happened)
  for (const l of rules.filter((x) => x.includes("nav-wordmark") || x.includes("nav-logo img"))) assert.ok(l.includes(".site-nav"), "header-only: " + l.slice(0, 80));
});

test("on the cobalt header the text keeps its contrast: white 5.9:1, navy-on-gold button, gold wordmark and the crimson Privacy and Terms links", () => {
  const hex = (n) => parseInt(n, 16) / 255;
  const lin = (c) => (c <= 0.03928 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4));
  const lum = (h) => 0.2126 * lin(hex(h.slice(0, 2))) + 0.7152 * lin(hex(h.slice(2, 4))) + 0.0722 * lin(hex(h.slice(4, 6)));
  const ratio = (a, b) => { const [x, y] = [lum(a), lum(b)].sort((m, n) => n - m); return (x + 0.05) / (y + 0.05); };
  assert.ok(ratio("FFFFFF", "0052F5") >= 4.5, "white links on the sharper cobalt");
  assert.ok(ratio("FFB300", "0052F5") >= 3, "the large bold gold wordmark on cobalt");
  assert.ok(ratio("071C42", "FFB300") >= 4.5, "navy text on the gold Sign In button");
  assert.ok(ratio("C8102E", "FFFFFF") >= 4.5, "the crimson privacy sentence on white");
  assert.ok(ratio("0052F5", "FFFFFF") >= 4.5, "the cobalt Career Tools headline on white");
});

test("the inner pages never scroll sideways: the centred Career Tools panel (sized by 100vw, which counts the scrollbar) is clipped by the body", () => {
  const css = read("pages-v4.css");
  assert.match(css, /body\.pages-v4 \{ overflow-x: clip; \}/);
  assert.match(css, /#step-mode\.pv-panel \{ position: relative; left: 50%; transform: translateX\(-50%\); width: min\(var\(--wrap\), 100vw\);/);
});
