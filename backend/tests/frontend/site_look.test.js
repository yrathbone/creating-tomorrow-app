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
