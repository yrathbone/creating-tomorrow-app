// Copy consistency across the public pages (the site-wide review of 2026-11-03): one apostrophe style, one name for signing in,
// one spelling of resume and color, sentence-case results headings, and the same names and short phrases the homepage uses.
// Static checks only. Run:  node --test backend/tests/frontend
const test = require("node:test");
const assert = require("node:assert");
const fs = require("node:fs");
const path = require("node:path");

const FRONTEND = path.join(__dirname, "..", "..", "..", "frontend");
const read = (p) => fs.readFileSync(path.join(FRONTEND, p), "utf8");
const PAGES = ["index", "learn", "videos", "about", "tool", "scratch", "elevate", "spotlight", "prepare", "article", "contact", "accessibility", "not-found", "privacy", "terms", "career/login", "career/register"];

// The text a visitor sees (plus placeholder, aria-label, alt and title values), read by walking the page one tag at a time.
// It never rewrites the HTML, it only collects text, and it skips script, style and comment contents.
function visibleText(html) {
  const lower = html.toLowerCase();
  const attrs = [];
  let text = "";
  let i = 0;
  while (i < html.length) {
    const lt = html.indexOf("<", i);
    if (lt === -1) { text += html.slice(i); break; }
    text += html.slice(i, lt) + " ";
    if (html.startsWith("<!--", lt)) {
      const end = html.indexOf("-->", lt + 4);
      i = end === -1 ? html.length : end + 3;
      continue;
    }
    const gt = html.indexOf(">", lt);
    if (gt === -1) break;
    const tag = html.slice(lt, gt + 1);
    for (const m of tag.matchAll(/(?:placeholder|aria-label|alt|title)="([^"]*)"/g)) attrs.push(m[1]);
    const name = (tag.match(/^<\s*([a-zA-Z0-9]+)/) || [])[1];
    i = gt + 1;
    if (name && (name.toLowerCase() === "script" || name.toLowerCase() === "style")) {
      const close = lower.indexOf("</" + name.toLowerCase(), i);
      const closeEnd = close === -1 ? -1 : html.indexOf(">", close);
      i = closeEnd === -1 ? html.length : closeEnd + 1;
    }
  }
  return text + " " + attrs.join(" ");
}

test("one apostrophe style: no straight apostrophe inside a word in any page's visible text", () => {
  for (const page of PAGES) {
    const bad = visibleText(read(page + ".html")).match(/[A-Za-z]'[a-z]+/g) || [];
    assert.deepStrictEqual(bad, [], `${page}: use the curly apostrophe (’): ${bad.slice(0, 3).join(", ")}`);
  }
});

test("one name for signing in: the page, its title, its button and the register page all say sign in", () => {
  const login = read("career/login.html");
  assert.match(login, /<title>Sign In — Creating Tomorrow<\/title>/);
  assert.match(login, /<h1>Sign in<\/h1>/);
  assert.match(login, /id="login-btn">Sign in<\/button>/);
  assert.match(login, /Back to sign in<\/button>/);
  assert.match(read("career/register.html"), /<a href="login\.html">sign in<\/a>/);
  assert.match(read("career/register.html"), /<title>Create an account — Creating Tomorrow<\/title>/);
  for (const page of PAGES) assert.ok(!/\bLog In\b|<h1>Log in<\/h1>/.test(read(page + ".html")), `${page}: "Log In" label`);
  for (const page of ["career/login", "career/register"]) assert.ok(!/\blog in\b/i.test(visibleText(read(page + ".html"))), `${page}: "log in" in the visible text`);
});

test("one spelling: resume (no accents) and American color, on every public page", () => {
  for (const page of PAGES) {
    const text = visibleText(read(page + ".html"));
    assert.ok(!/résumé/i.test(text), `${page}: résumé`);
    assert.ok(!/\bcolour/i.test(text), `${page}: colour`);
  }
});

test("results headings on the Prepare page are sentence case, like every other results page", () => {
  const html = read("prepare.html");
  for (const h of ["What this employer appears to care about", "Likely interview questions", "Questions you may want to ask them", "Preparation tip"]) assert.ok(html.includes(`>${h}</h`), h);
});

test("the Career Tools page uses the homepage's short phrases, the Learn page says Read, and the 404 page uses the header's names", () => {
  const tool = read("tool.html");
  const phrases = [...tool.matchAll(/<span class="hv-vdesc">([^<]+)<\/span>/g)].map((m) => m[1]);
  assert.deepStrictEqual(phrases, ["Create your first resume", "Optimize for screening", "Check your fit", "Find hidden experiences", "Showcase your strengths", "Master interview stories"]);
  const home = read("index.html");
  for (const p of phrases) assert.ok(home.includes(`<span class="h7-text">${p}</span>`), `the homepage says "${p}" too`);
  const learn = read("learn.html");
  assert.strictEqual((learn.match(/Read <span aria-hidden="true">→<\/span>/g) || []).length, 4);
  assert.ok(!learn.includes("Read the guide <span"));
  const nf = read("not-found.html");
  assert.match(nf, /h5-btn-green">Career Tools<\/a>/);
  assert.match(nf, /h5-btn-outline">Learn<\/a>/);
});
