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
