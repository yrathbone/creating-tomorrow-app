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
  assert.match(html, /<body class="home-v5 chrome-v6">/);
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

test("the inner pages never scroll sideways: the centred Career Tools panel (sized by 100vw, which counts the scrollbar) is clipped by the body", () => {
  const css = read("pages-v4.css");
  assert.match(css, /body\.pages-v4 \{ overflow-x: clip; \}/);
  assert.match(css, /#step-mode\.pv-panel \{ position: relative; left: 50%; transform: translateX\(-50%\); width: min\(var\(--wrap\), 100vw\);/);
});

const PUBLIC = ["index", "about", "accessibility", "article", "contact", "elevate", "learn", "prepare", "privacy", "scratch", "spotlight", "terms", "tool", "videos", "not-found", "career/login", "career/register"];
const LAST_CSS = { index: "home-v5.css", "not-found": "/home-v5.css", "career/login": "auth-v5.css", "career/register": "auth-v5.css" };

test("every public page wears the shared chrome: the body class, and chrome-v6.css loaded after the page's own stylesheet", () => {
  for (const name of PUBLIC) {
    const html = read(name + ".html");
    assert.match(html, /<body class="[^"]*\bchrome-v6\b/, name + " body class");
    assert.ok(!html.includes("tool-hub"), name + " has no leftover single-page class");
    const links = [...html.matchAll(/<link rel="stylesheet" href="([^"]+)"/g)].map((m) => m[1]);
    const prefix = name.startsWith("career/") ? "../" : name === "not-found" ? "/" : "";
    assert.strictEqual(links[links.length - 1], prefix + "chrome-v6.css", name + ": chrome-v6.css is the last stylesheet");
    const own = LAST_CSS[name] || "pages-v4.css";
    assert.strictEqual(links[links.length - 2], own, name + ": it follows " + own);
  }
});

test("chrome-v6.css is scoped to the public pages, never the signed-in dashboard, and holds nothing for other pages", () => {
  const css = read("chrome-v6.css").replace(/\/\*[\s\S]*?\*\//g, "");
  const selectors = css.split("}").map((r) => r.split("{")[0].trim()).filter(Boolean).flatMap((r) => (r.startsWith("@") ? [] : r.split(",").map((x) => x.trim())));
  assert.ok(selectors.length > 40, "the stylesheet has its rules");
  for (const sel of selectors) assert.ok(/^body\.chrome-v6/.test(sel), "scoped: " + sel);
  for (const sel of selectors) assert.ok(sel.includes(":not(.dashboard-v4)"), "dashboard excluded: " + sel);
  // the dashboard stylesheet is not touched by this change
  assert.ok(!read("career/dashboard-v4.css").includes("chrome-v6"));
});

test("every footer says Privacy & Terms (two links, one crimson unit), and the free-tools line uses the new wording", () => {
  for (const name of PUBLIC) {
    const html = read(name + ".html");
    const prefix = name.startsWith("career/") ? "../" : name === "not-found" ? "/" : "";
    assert.ok(html.includes(`<a href="${prefix}privacy.html">Privacy</a> <span class="h5-amp">&amp;</span> <a href="${prefix}terms.html">Terms</a>`), name + " footer pair");
    assert.ok(!/Privacy<\/a>\s*·\s*<a href="[^"]*terms\.html">/.test(html), name + " has no dotted Privacy · Terms left");
    const m = html.match(/<p class="h5-footer-privacy">([\s\S]*?)<\/p>/);
    if (!m) continue;
    if (name.startsWith("career/")) { assert.match(m[1], /Career Profile is an early, invite-only preview/); continue; }
    assert.match(m[1], /^<span class="h5-nosave">We do not keep your [a-z ]+<\/span>/, name + " opens with the underlined promise");
    assert.match(m[1], /normally deletes (them|it) within 30 days\.$/, name + " says 'normally', never 'always'");
    assert.ok(!/typically deleted|don't save/.test(m[1]), name + " no old wording");
  }
});

test("the chrome rules hold their contrast and layout: cobalt header, gold button, crimson links, one-line centred sentence, brand bottom right", () => {
  const css = read("chrome-v6.css");
  assert.match(css, /--c6-blue: #0052f5;/);
  assert.match(css, /\.site-nav \{ background: var\(--c6-blue\); border-bottom: 0; \}/);
  assert.match(css, /\.nav-links a\.nav-account \{ background: var\(--c6-gold\); border-color: var\(--c6-gold\); color: #071c42; \}/);
  assert.match(css, /grid-template-areas: "nav legal" "privacy privacy" "copy brand";/);
  assert.match(css, /\.h5-footer-privacy \{ grid-area: privacy; justify-self: center; max-width: none;/);
  assert.match(css, /\.h5-footer-brand \{ grid-area: brand; justify-self: end; \}/);
  assert.match(css, /\.h5-footer \.nav-wordmark-gold \{ color: var\(--c6-gold-footer\); \}/);
  assert.match(css, /footer\.h5-footer::after \{ content: ""; display: block; height: 3\.25rem;/);
  const hex = (n) => parseInt(n, 16) / 255;
  const lin = (c) => (c <= 0.03928 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4));
  const lum = (h) => 0.2126 * lin(hex(h.slice(0, 2))) + 0.7152 * lin(hex(h.slice(2, 4))) + 0.0722 * lin(hex(h.slice(4, 6)));
  const ratio = (a, b) => { const [x, y] = [lum(a), lum(b)].sort((m, n) => n - m); return (x + 0.05) / (y + 0.05); };
  assert.ok(ratio("FFFFFF", "0052F5") >= 4.5, "white links on the cobalt header");
  assert.ok(ratio("FFB300", "0052F5") >= 3, "the gold wordmark on cobalt");
  assert.ok(ratio("071C42", "FFB300") >= 4.5, "navy text on the gold Sign In button");
  assert.ok(ratio("C8102E", "FFFFFF") >= 4.5, "crimson Privacy & Terms on white");
  assert.ok(ratio("0052F5", "FFFFFF") >= 4.5, "the cobalt page titles on white");
});

test("only the inner pages are whitened: the homepage keeps its locked grey and white bands", () => {
  const css = read("chrome-v6.css");
  assert.match(css, /body\.chrome-v6\.pages-v4:not\(\.dashboard-v4\) \{ --pale: #ffffff; background: #ffffff; \}/);
  assert.ok(!/body\.chrome-v6:not\(\.dashboard-v4\) \{[^}]*--pale/.test(css), "--pale is not redefined for every page");
  assert.match(read("home-v5.css"), /--pale: #f2f5f8;/);
});

