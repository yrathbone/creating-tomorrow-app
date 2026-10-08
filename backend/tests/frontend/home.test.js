// The redesigned homepage (frontend/index.html + home-v4.css): guards the things that must keep working.
// Static checks only - no browser needed.  Run:  node --test backend/tests/frontend
const test = require("node:test");
const assert = require("node:assert");
const fs = require("node:fs");
const path = require("node:path");

const FRONTEND = path.join(__dirname, "..", "..", "..", "frontend");
const read = (...p) => fs.readFileSync(path.join(FRONTEND, ...p), "utf8");
const html = read("index.html");
const css = read("home-v4.css");
const guide = read("guide.js");

test("the page loads the shared stylesheet, then home-v4.css, and marks the body", () => {
  const shared = html.indexOf('href="style.css"');
  const home = html.indexOf('href="home-v4.css"');
  assert.ok(shared > -1 && home > shared, "home-v4.css must load after style.css");
  assert.match(html, /<body class="home-v4">/);
});

test("every element guide.js looks up by id still exists (the Guide modal is intact)", () => {
  const ids = [...guide.matchAll(/getElementById\("([^"]+)"\)/g)].map((m) => m[1]);
  // the old teaser's mascot / headline / button are optional now (guide.js tolerates their absence)
  const optional = new Set(["guide-open-btn", "guide-character-slot", "guide-headline-open"]);
  for (const id of new Set(ids)) {
    if (optional.has(id)) continue;
    assert.ok(html.includes(`id="${id}"`), `missing #${id}`);
  }
});

test("there are Guide Me buttons, and guide.js wires them up", () => {
  assert.ok((html.match(/data-guide-open/g) || []).length >= 2);
  assert.match(guide, /querySelectorAll\("\[data-guide-open\]"\)/);
  assert.match(guide, /if \(guideOpenBtn\)/);
  assert.match(guide, /if \(!el\) return/);
});

test("the six tool tiles link to the same places the Guide recommends", () => {
  const guideHrefs = [...guide.matchAll(/toolHref: "([^"]+)"/g)].map((m) => m[1]).sort();
  const tileHrefs = [...html.matchAll(/<a class="hv-tool [^"]*" href="([^"]+)"/g)].map((m) => m[1]).sort();
  assert.strictEqual(tileHrefs.length, 6);
  assert.deepStrictEqual(tileHrefs, guideHrefs);
});

test("the shared header, the privacy notice and the Alan Kay quote are all present", () => {
  assert.match(html, /<nav class="site-nav">/);
  assert.match(html, /class="nav-account"/); // auth-nav.js switches this to "My Career"
  assert.match(html, /<script src="auth-nav\.js"><\/script>/);
  assert.match(html, /We don't save your resume or job posting/);
  assert.match(html, /The best way to predict the future is to invent it\./);
  assert.match(html, /Alan Kay/);
});

test("no broken relative paths from the prototype, and every referenced image exists", () => {
  assert.ok(!html.includes('="../'), "leftover ../ path");
  const srcs = [...html.matchAll(/src="([^"]+\.(?:jpg|png))"/g)].map((m) => m[1]);
  const cssImgs = [...css.matchAll(/url\("([^"]+\.(?:jpg|png))"\)/g)].map((m) => m[1]);
  for (const f of [...srcs, ...cssImgs]) assert.ok(fs.existsSync(path.join(FRONTEND, f)), `missing ${f}`);
});

test("home-v4.css only touches the homepage: every rule is scoped to body.home-v4 or an hv- class", () => {
  const stripped = css.replace(/\/\*[\s\S]*?\*\//g, "");
  const rules = [...stripped.matchAll(/(^|\})\s*([^{}@]+)\{/g)].map((m) => m[2].trim());
  for (const sel of rules) {
    for (const part of sel.split(",").map((s) => s.trim()).filter(Boolean)) {
      if (/^\d+%$|^from$|^to$/.test(part)) continue; // keyframe steps
      const ok = part.startsWith("body.home-v4") || /^\.hv-|^#(how|tools|basics)-h\b/.test(part) || part === "html";
      assert.ok(ok, `unscoped selector: ${part}`);
    }
  }
});

test("Career Basics is back: four guide tiles that open real articles, plus the Learn link", () => {
  const slugs = [...html.matchAll(/class="hv-guide [^"]*" href="article\.html\?slug=([^"]+)"/g)].map((m) => m[1]);
  assert.deepStrictEqual(slugs, ["what-is-ats", "resume-calling-card", "honest-self-marketing", "how-we-grade"]);
  assert.match(html, /href="learn\.html" class="hv-seeall"/);
  const data = read("learn-data.js");
  for (const slug of slugs) assert.ok(data.includes(slug), `article ${slug} is not in learn-data.js`);
});

test("the homepage says it is free for everyone, right under the hero buttons", () => {
  const hero = html.slice(html.indexOf('class="hv-hero"'), html.indexOf('class="hv-hero-photo"'));
  assert.match(hero, /Free for everyone\./);
  assert.match(hero, /No paywall\./);
  assert.ok(hero.indexOf("hv-cta") < hero.indexOf("hv-free"), "the line sits after the buttons");
});

test("the founder's note closes the page (after the team band, before the footer) and links to the About page", () => {
  const band = html.indexOf('class="hv-bottom"');
  const note = html.indexOf('class="hv-note"');
  const footer = html.indexOf('<footer');
  assert.ok(band > -1 && note > band && footer > note, "order: band, note, footer");
  assert.match(html, /I really believe our futures are linked\./);
  assert.match(html, /When my neighbors succeed, I succeed too\./);
  assert.match(html, /This is how I honor our connection and show everyone they are important\./);
  assert.match(html, /<a class="hv-note-link" href="about\.html">/);
  assert.ok(!/yovana|rathbone/i.test(html), "the page does not name a person (the About page does not either)");
});

test("How It Works, Career Basics and the six tools share one panel, in that order, before the team band", () => {
  const panelStart = html.indexOf('<div class="hv-panel">');
  const how = html.indexOf('id="how"');
  const basics = html.indexOf('id="basics"');
  const tools = html.indexOf('id="tools"');
  const band = html.indexOf('class="hv-bottom"');
  assert.ok(panelStart > -1 && panelStart < how && how < basics && basics < tools && tools < band);
  // the panel closes before the band: three sections inside, none after
  const panelHtml = html.slice(panelStart, band);
  assert.strictEqual((panelHtml.match(/<section class="hv-section hv-card/g) || []).length, 3);
  assert.strictEqual((panelHtml.match(/<div/g) || []).length - (panelHtml.match(/<\/div>/g) || []).length, 0, "panel div is balanced");
});

test("the section headings are warm, and the ids that links and tests rely on are unchanged", () => {
  assert.match(html, /<h2 id="how-h" class="hv-h2">Here’s how we begin<\/h2>/);
  assert.match(html, /<h2 id="basics-h" class="hv-h2">Start with the basics<\/h2>/);
  assert.match(html, /<h2 id="tools-h" class="hv-h2">Six free tools for your next step<\/h2>/);
  for (const id of ["how", "basics", "tools"]) assert.ok(html.includes(`id="${id}"`), `missing #${id}`);
  assert.match(html, /href="#tools"/); // Explore Tools and step 2 still jump to the tools
});

test("the hero and the sections below it are one box, with her line in the space between", () => {
  const panel = html.indexOf('<div class="hv-panel">');
  const hero = html.indexOf('<section class="hv-hero">');
  const quote = html.indexOf('class="hv-quote hv-quote-top"');
  const how = html.indexOf('id="how"');
  const band = html.indexOf('class="hv-bottom"');
  assert.ok(panel > -1 && panel < hero && hero < quote && quote < how && how < band, "order: panel, hero, her line, How It Works, band");
  assert.match(html, /You can’t become what you can’t picture\. Let’s picture it together\./);
  assert.ok(html.slice(0, panel).indexOf('class="hv-hero"') === -1, "no hero outside the box");
  const css = read("home-v4.css");
  assert.match(css, /\.hv-panel > \.hv-hero \{ width: auto;/);
});
