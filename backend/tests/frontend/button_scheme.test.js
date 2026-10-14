// The button colour scheme (docs/BUTTON-SCHEME.md): blue = the everyday main action, gold = start here, green = explore and compare,
// crimson = the one action that builds the document, outline = secondary, outline red = delete.
// Green and crimson are used by exactly the buttons listed here, so a new button cannot quietly take one of those colours:
// to add one, add it to this table (and to the scheme document) on purpose.
const test = require("node:test");
const assert = require("node:assert");
const fs = require("node:fs");
const path = require("node:path");

const FRONTEND = path.join(__dirname, "..", "..", "..", "frontend");
const read = (...p) => fs.readFileSync(path.join(FRONTEND, ...p), "utf8");

const GREEN = {
  "career/login.html": ["job-compare-btn", "job-start-interview-btn", "skill-scan-btn", "resume-upload-btn"],
  "elevate.html": ["upload-btn"],
  "tool.html": ["analyze-btn"],
  "prepare.html": ["prepare-btn"],
  "spotlight.html": ["review-btn", "compare-signin-btn"],
};
const CRIMSON = {
  "career/login.html": ["job-build-btn", "general-resume-build-btn"],
  "elevate.html": ["confirm-continue-btn"],
  "tool.html": ["generate-btn"],
  "scratch.html": ["generate-btn"],
};
const PAGES = ["career/login.html", "elevate.html", "tool.html", "scratch.html", "prepare.html", "spotlight.html", "article.html", "about.html", "index.html", "not-found.html"];

function buttonsWithClass(html, cls) {
  const out = [];
  for (const m of html.matchAll(/<button\b([^>]*)>/g)) {
    const klass = (m[1].match(/class="([^"]*)"/) || [, ""])[1].split(/\s+/);
    const id = (m[1].match(/\bid="([^"]*)"/) || [, ""])[1];
    if (klass.includes(cls)) out.push(id);
  }
  return out.sort();
}

test("green is used by exactly the explore and compare buttons, crimson by exactly the build buttons", () => {
  for (const page of PAGES) {
    const html = read(...page.split("/"));
    assert.deepStrictEqual(buttonsWithClass(html, "btn-green"), (GREEN[page] || []).slice().sort(), page + " green buttons");
    assert.deepStrictEqual(buttonsWithClass(html, "btn-crimson"), (CRIMSON[page] || []).slice().sort(), page + " crimson buttons");
  }
});

test("the homepage and 404 use the same green, and Guide Me / Get Started stay gold", () => {
  assert.match(read("index.html"), /class="h5-btn h5-btn-green">Explore Tools</);
  assert.match(read("not-found.html"), /class="h5-btn h5-btn-green">Free career tools</);
  const home = read("index.html");
  assert.match(home, /class="h5-btn h5-btn-gold" data-guide-open>Guide Me/);
  assert.match(home, /class="h5-btn h5-btn-gold">Get Started Today/);
  const css = read("home-v5.css");
  assert.match(css, /\.h5-btn-green \{ background: #1f7a3f; color: #ffffff; \}/);
  assert.match(css, /\.h5-btn-green:hover \{ background: #16602f; \}/);
});

test("the two roles are defined once for every page, again for the free tools and the dashboard, and no one-off id rules are left", () => {
  const base = read("style.css");
  assert.match(base, /\.btn-green \{ background: #1f7a3f; color: #ffffff;/);
  assert.match(base, /\.btn-crimson \{ background: #c8102e; color: #ffffff;/);
  const pages = read("pages-v4.css");
  assert.match(pages, /body\.pages-v4 \.btn-green \{ background: #1f7a3f;/);
  assert.match(pages, /body\.pages-v4 \.btn-crimson \{ background: #c8102e;/);
  assert.ok(!/spotlight-page #review-btn/.test(pages) && !/spotlight-page #review-btn/.test(base), "no one-off colour rule is left for Review My Profile");
  const dash = read("career", "dashboard-v4.css");
  assert.match(dash, /\.card \.btn-green,[\s\S]*?\{ background-image: none; background-color: #1f7a3f; color: #ffffff;/);
  assert.match(dash, /\.card \.btn-crimson,[\s\S]*?\{ background-image: none; background-color: #c8102e; color: #ffffff;/);
  assert.ok(!/button#job-build-btn|button#job-compare-btn/.test(dash), "no one-off id rules for these buttons");
  // the dashboard's generic blue-button rule steps aside for the two roles, everywhere it is written
  for (const rule of dash.match(/button:not\(\.stat-card\)[^{,]*/g)) assert.ok(rule.includes(":not(.btn-green):not(.btn-crimson)"), "generic rule excludes green and crimson: " + rule.slice(0, 80));
  for (const rule of dash.match(/#career-profile-editor button:not\([^{,]*/g)) assert.ok(rule.includes(":not(.btn-green):not(.btn-crimson)"), "editor rule excludes green and crimson");
});

test("delete is outlined with red text, so a solid red always means Build", () => {
  const dash = read("career", "dashboard-v4.css");
  const tail = dash.slice(dash.lastIndexOf("/* delete: outlined, red text"));
  assert.match(tail, /\.btn-danger,\s*body\.dashboard-v4 #delete-confirm-btn \{ background-image: none; background-color: #ffffff; color: #b93030; border: 2px solid #b93030;/);
});

test("every role colour holds its contrast with white text, and the hover is darker still", () => {
  const lum = (h) => { const c = [0, 2, 4].map((i) => parseInt(h.slice(i, i + 2), 16) / 255).map((v) => (v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4))); return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]; };
  const ratio = (a, b) => { const [x, y] = [lum(a), lum(b)].sort((m, n) => n - m); return (x + 0.05) / (y + 0.05); };
  for (const [name, base, hover] of [["green", "1F7A3F", "16602F"], ["crimson", "C8102E", "8F0B22"]]) {
    assert.ok(ratio("FFFFFF", base) >= 4.5, name + " base with white text");
    assert.ok(ratio("FFFFFF", hover) >= ratio("FFFFFF", base), name + " hover is at least as dark");
  }
  assert.ok(ratio("B93030", "FFFFFF") >= 4.5, "delete text on white");
});

test("the scheme is written down once, with every role", () => {
  const doc = fs.readFileSync(path.join(FRONTEND, "..", "docs", "BUTTON-SCHEME.md"), "utf8");
  for (const word of ["Blue", "Gold", "Green", "Crimson", "Outline", "Delete", "#1F7A3F", "#C8102E", "#FFB300"]) assert.ok(doc.includes(word), "scheme document mentions " + word);
});
