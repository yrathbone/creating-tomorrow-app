// The clean homepage (frontend/index.html + home-v5.css): guards the things that must keep working.
// Static checks only - no browser needed.  Run:  node --test backend/tests/frontend
const test = require("node:test");
const assert = require("node:assert");
const fs = require("node:fs");
const path = require("node:path");

const FRONTEND = path.join(__dirname, "..", "..", "..", "frontend");
const read = (...p) => fs.readFileSync(path.join(FRONTEND, ...p), "utf8");
const html = read("index.html");
const css = read("home-v5.css");
const guide = read("guide.js");

function luminance(hex) {
  const [r, g, b] = [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16) / 255)
    .map((c) => (c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4));
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}
const contrast = (a, b) => { const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x); return (hi + 0.05) / (lo + 0.05); };
const token = (name) => css.match(new RegExp(`--${name}:\\s*(#[0-9a-fA-F]{6})`))[1];

test("the page loads the shared stylesheet, then home-v5.css, and marks the body", () => {
  const shared = html.indexOf('href="style.css"');
  const home = html.indexOf('href="home-v5.css"');
  assert.ok(shared > -1 && home > shared, "home-v5.css must load after style.css");
  assert.match(html, /<body class="home-v5">/);
  assert.ok(!html.includes("home-v4"), "the old homepage styles are gone from this page");
});

test("every element guide.js looks up by id still exists (the Guide modal is intact)", () => {
  const ids = [...guide.matchAll(/getElementById\("([^"]+)"\)/g)].map((m) => m[1]);
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

test("the six tool cards link to the same places the Guide recommends, and keep their real names", () => {
  const guideHrefs = [...guide.matchAll(/toolHref: "([^"]+)"/g)].map((m) => m[1]).sort();
  const tileHrefs = [...html.matchAll(/<a class="h5-card h5-tool" href="([^"]+)"/g)].map((m) => m[1]).sort();
  assert.strictEqual(tileHrefs.length, 6);
  assert.deepStrictEqual(tileHrefs, guideHrefs);
  for (const name of ["Beginning", "Refine", "Right Fit", "Elevate", "Spotlight", "Prepare"]) {
    assert.match(html, new RegExp(`Start ${name} <span aria-hidden="true">`), `${name} link text`);
  }
  for (const verb of ["Create", "Improve", "Match", "Discover", "LinkedIn", "Interview"]) {
    assert.match(html, new RegExp(`<b class="h5-card-title">${verb}</b>`), `${verb} card title`);
  }
});

test("the shared header, the privacy notice and the legal links are all present", () => {
  assert.match(html, /<nav class="site-nav">/);
  assert.match(html, /class="nav-account"/); // auth-nav.js switches this to "My Career"
  assert.match(html, /<script src="auth-nav\.js"><\/script>/);
  for (const label of ["Home", "Learn", "Videos", "About", "Career Tools", "Sign In"]) assert.match(html, new RegExp(`>${label}</a>`), label);
  assert.match(html, /We don't save your resume or job posting/);
  assert.match(html, /class="footer-links"><a href="privacy\.html">Privacy<\/a> · <a href="terms\.html">Terms<\/a> · <a href="accessibility\.html">Accessibility<\/a> · <a href="contact\.html">Contact<\/a>/);
  assert.match(html, /© 2026 Creating Tomorrow\. All rights reserved\./);
});

test("every referenced image exists and there are no broken relative paths", () => {
  assert.ok(!html.includes('="../'), "leftover ../ path");
  const srcs = [...html.matchAll(/src="([^"]+\.(?:jpg|png|webp))"/g)].map((m) => m[1]);
  assert.ok(srcs.includes("img/home/hero-graduate-placeholder.jpg"));
  for (const f of srcs) assert.ok(fs.existsSync(path.join(FRONTEND, f)), `missing ${f}`);
});

test("home-v5.css only touches the homepage: every rule is scoped to body.home-v5 or an h5- class", () => {
  const stripped = css.replace(/\/\*[\s\S]*?\*\//g, "");
  const rules = [...stripped.matchAll(/(^|\})\s*([^{}@]+)\{/g)].map((m) => m[2].trim());
  for (const sel of rules) {
    for (const part of sel.split(",").map((s) => s.trim()).filter(Boolean)) {
      const ok = part.startsWith("body.home-v5") || /^\.h5-/.test(part) || part === "html";
      assert.ok(ok, `unscoped selector: ${part}`);
    }
  }
});

test("the page is seven bands in the reference order: header, pale hero, white steps, pale guides, white tools, cobalt close, footer", () => {
  const order = ['<nav class="site-nav">', 'h5-band h5-band-pale h5-hero-band', 'id="how"', 'id="basics"', 'id="tools"', 'class="h5-closing"', '<footer class="h5-footer">'].map((s) => html.indexOf(s));
  assert.ok(order.every((n) => n > -1), "every band exists");
  assert.deepStrictEqual([...order].sort((a, b) => a - b), order, "bands appear in order");
  assert.match(html, /<section class="h5-band h5-band-white" id="how"/);
  assert.match(html, /<section class="h5-band h5-band-pale" id="basics"/);
  assert.match(html, /<section class="h5-band h5-band-white" id="tools"/);
  assert.match(css, /\.h5-closing \{[^}]*background: var\(--cta\)/);
});

test("the hero says what the design says, with the gold second line and the free note right under the buttons", () => {
  assert.match(html, /<p class="h5-eyebrow">Tools today\. Brighter tomorrow\.<\/p>/);
  assert.match(html, /<h1 id="hero-h">See your value\.<br \/><span>Build your future\.<\/span><\/h1>/);
  assert.match(css, /\.h5-hero h1 span \{[^}]*color: var\(--gold-display\)/);
  assert.match(html, /<p class="h5-lead">Free career tools to help you build a better tomorrow\.<\/p>/);
  const hero = html.slice(html.indexOf('class="h5-hero"'), html.indexOf('class="h5-hero-photo"'));
  assert.match(hero, /Guide Me <span aria-hidden="true">→<\/span>/);
  assert.match(hero, /href="#tools" class="h5-btn h5-btn-outline">Explore Tools/);
  assert.match(hero, /Free for everyone\./);
  assert.match(hero, /No paywall\./);
  assert.ok(hero.indexOf("h5-cta") < hero.indexOf("h5-free"), "the line sits after the buttons");
  assert.match(html, /<blockquote><p>“The best way to predict the future is to invent it\.”<\/p><\/blockquote>\s*<figcaption>— Alan Kay<\/figcaption>/);
  assert.ok(!html.includes("You can’t become what you can’t picture"), "the old line was swapped out on purpose");
});

test("the section headings and the ids that links rely on are unchanged", () => {
  assert.match(html, /<h2 id="how-h" class="h5-h2">Here’s how we begin\.<\/h2>/);
  assert.match(html, /<h2 id="basics-h" class="h5-h2">Start with the basics\.<\/h2>/);
  assert.match(html, /<h2 id="tools-h" class="h5-h2">Six free tools for your next step\.<\/h2>/);
  for (const id of ["how", "basics", "tools"]) assert.ok(html.includes(`id="${id}"`), `missing #${id}`);
  assert.match(html, /href="#tools"/); // Explore Tools and step 2 still jump to the tools
  assert.match(html, /<h2 id="close-h">We don’t invent your value\. We help you see it\.<\/h2>/);
  assert.match(html, /href="tool\.html" class="h5-btn h5-btn-gold">Get Started Today/);
});

test("the three steps keep their real links (Guide, tools, Prepare)", () => {
  const steps = [...html.matchAll(/<a class="h5-step" href="([^"]+)"/g)].map((m) => m[1]);
  assert.deepStrictEqual(steps, ["#", "#tools", "prepare.html"]);
  assert.match(html, /<a class="h5-step" href="#" data-guide-open/);
});

test("four guide cards open the real articles, and the Learn link is still there", () => {
  const slugs = [...html.matchAll(/class="h5-card h5-guide" href="article\.html\?slug=([^"]+)"/g)].map((m) => m[1]);
  assert.deepStrictEqual(slugs, ["what-is-ats", "resume-calling-card", "honest-self-marketing", "how-we-grade"]);
  assert.match(html, /<p class="h5-more"><a href="learn\.html">See all learning resources/);
  const data = read("learn-data.js");
  for (const slug of slugs) assert.ok(data.includes(slug), `article ${slug} is not in learn-data.js`);
  for (const label of ["ATS Basics", "Resume Basics", "LinkedIn Basics", "Interview Basics"]) assert.match(html, new RegExp(`<b class="h5-card-title">${label}</b>`));
  assert.strictEqual((html.match(/Read the Guide <span aria-hidden="true">/g) || []).length, 4);
  // the full article title stays available to screen readers and search tools
  assert.match(html, /aria-label="ATS Basics: What Is an ATS, Really\?\. Read the guide\."/);
});

test("the page does not name a person, and nothing the design dropped is left behind", () => {
  assert.ok(!/yovana|rathbone/i.test(html), "the page does not name a person");
  for (const gone of ["mascot-icon", "hv-", "hero-man", "team-people"]) assert.ok(!html.includes(gone), `leftover: ${gone}`);
});

test("colours: the reference palette is used, and every text pairing meets WCAG AA", () => {
  assert.strictEqual(token("navy").toLowerCase(), "#0b2454");
  assert.strictEqual(token("cobalt").toLowerCase(), "#075fea");
  assert.strictEqual(token("cta").toLowerCase(), "#075be8");
  assert.strictEqual(token("gold").toLowerCase(), "#f4a900");
  assert.strictEqual(token("pale").toLowerCase(), "#f5f7fa");
  assert.strictEqual(token("green").toLowerCase(), "#079b70");
  const [navy, cobalt, cta, gold, goldText, pale, body] = ["navy", "cobalt", "cta", "gold", "gold-text", "pale", "body"].map(token);
  assert.ok(contrast(goldText, pale) >= 3, "the large gold headline text needs 3:1");
  assert.ok(contrast(goldText, "#ffffff") >= 3);
  assert.ok(contrast(body, pale) >= 4.5, "body gray on the pale bands");
  assert.ok(contrast(body, "#ffffff") >= 4.5, "body gray on white");
  assert.ok(contrast(cobalt, "#ffffff") >= 4.5, "links on white");
  assert.ok(contrast(cobalt, pale) >= 4.5, "the eyebrow on the pale band");
  assert.ok(contrast("#ffffff", cta) >= 4.5, "white text on the cobalt band");
  assert.ok(contrast(navy, gold) >= 4.5, "navy text on the gold buttons");
  assert.ok(contrast(goldText, "#fff3d6") >= 3, "gold icons on their pale tint");
});

test("type: serif headlines and the shared size scale, buttons tall enough to tap, focus ring present", () => {
  assert.match(css, /\.h5-hero h1 \{[^}]*font-family: var\(--font-serif\)[^}]*font-size: var\(--fs-display\)/);
  assert.match(css, /\.h5-h2 \{[^}]*font-family: var\(--font-serif\)[^}]*font-size: var\(--fs-h1\)/);
  assert.match(read("style.css"), /--fs-display:\s*clamp\(/);
  assert.match(css, /\.h5-btn \{[^}]*min-height: 48px/);
  assert.match(css, /a:focus-visible,\s*\n?body\.home-v5 button:focus-visible \{ outline: 3px solid/);
  assert.ok(!/googleapis|gstatic/.test(css), "no outside fonts");
  assert.ok(!/Source Serif|Segoe UI/.test(css), "uses the shared tokens, not a second font stack");
});

test("responsive: tablet and phone layouts exist (stacked hero, 2-up then 1-up cards, stacked steps)", () => {
  assert.match(css, /@media \(max-width: 1000px\)[\s\S]*\.h5-hero \{ grid-template-columns: 1fr/);
  assert.match(css, /@media \(max-width: 1000px\)[\s\S]*\.h5-grid-4, \.h5-grid-3 \{ grid-template-columns: repeat\(2, 1fr\)/);
  assert.match(css, /@media \(max-width: 1000px\)[\s\S]*\.h5-steps \{ grid-template-columns: 1fr/);
  assert.match(css, /@media \(max-width: 620px\)[\s\S]*\.h5-grid-4, \.h5-grid-3 \{ grid-template-columns: 1fr/);
  assert.match(css, /prefers-reduced-motion: no-preference/);
});

test("less wording, because phones lose long text: a short lead, a short intro, and one short line per step", () => {
  const words = (re) => html.match(re)[1].trim().split(/\s+/).length;
  assert.ok(words(/<p class="h5-lead">([^<]+)<\/p>/) <= 12, "the hero line stays short");
  assert.match(html, /<p class="h5-sub">Get started now\.<\/p>/);
  const lines = [...html.matchAll(/<span class="h5-step-text">([^<]+)<\/span>/g)].map((m) => m[1]);
  assert.deepStrictEqual(lines, ["Share your background and goals.", "Use our free tools.", "Apply and prepare for interviews."]);
  for (const l of lines) assert.ok(l.split(/\s+/).length <= 6, `"${l}" is short enough for a phone`);
  for (const gone of ["in minutes", "meaningful steps", "see your experience clearly", "kind of work you"]) assert.ok(!html.includes(gone), `old wording left: ${gone}`);
});

test("card descriptions are a few words each, so they stay readable on a phone", () => {
  const guides = [...html.matchAll(/class="h5-card h5-guide"[\s\S]*?<span class="h5-card-text">([^<]+)<\/span>/g)].map((m) => m[1]);
  const tools = [...html.matchAll(/class="h5-card h5-tool"[\s\S]*?<span class="h5-card-text">([^<]+)<\/span>/g)].map((m) => m[1]);
  assert.deepStrictEqual(guides, ["See how resumes get screened.", "Keep your story ready.", "Show your experience honestly.", "Prepare stories, not scripts."]);
  assert.deepStrictEqual(tools, ["Build your first resume.", "Polish the resume you have.", "Check your fit for a job.", "Find experience you left out.", "Strengthen your LinkedIn.", "Get ready for interviews."]);
  for (const g of guides) assert.ok(g.split(/\s+/).length <= 5, `"${g}" is too long`);
  for (const t of tools) assert.ok(t.split(/\s+/).length <= 6, `"${t}" is too long`);
});

test("the headline gold is the founder's chosen colour, used on that one phrase only, and its contrast is a recorded choice", () => {
  assert.strictEqual(token("gold-display").toLowerCase(), "#e49107");
  const uses = css.match(/var\(--gold-display\)/g) || [];
  assert.strictEqual(uses.length, 1, "only the headline's second line uses it");
  // Known and accepted: below the 3:1 AA minimum for large text. If this ever needs to be fully AA, set --gold-display to #b87700.
  const ratio = contrast(token("gold-display"), token("pale"));
  assert.ok(ratio > 2.2 && ratio < 3, `recorded contrast ${ratio.toFixed(2)}:1 on the pale band`);
  assert.ok(contrast(token("gold-text"), token("pale")) >= 3, "every other gold text keeps the accessible gold");
});
