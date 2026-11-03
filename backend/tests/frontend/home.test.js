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
const css7 = read("home-v7.css");
const learnPopup = read("learn-popup.js");

function luminance(hex) {
  const [r, g, b] = [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16) / 255)
    .map((c) => (c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4));
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}
const contrast = (a, b) => { const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x); return (hi + 0.05) / (lo + 0.05); };
const token = (name) => css.match(new RegExp(`--${name}:\\s*(#[0-9a-fA-F]{6})`))[1];

test("every element guide.js looks up by id still exists (the Guide modal is intact)", () => {
  const ids = [...guide.matchAll(/getElementById\("([^"]+)"\)/g)].map((m) => m[1]);
  const optional = new Set(["guide-open-btn", "guide-character-slot", "guide-headline-open"]);
  for (const id of new Set(ids)) {
    if (optional.has(id)) continue;
    assert.ok(html.includes(`id="${id}"`), `missing #${id}`);
  }
});

test("the shared header, the privacy notice and the legal links are all present", () => {
  assert.match(html, /<nav class="site-nav">/);
  assert.match(html, /class="nav-account"/); // auth-nav.js switches this to "My Career"
  assert.match(html, /<script src="auth-nav\.js"><\/script>/);
  for (const label of ["Home", "Learn", "Videos", "About", "Career Tools", "Sign In"]) assert.match(html, new RegExp(`>${label}</a>`), label);
  assert.match(html, /<span class="h5-nosave">We do not keep your resume<\/span> or job posting\. We send them securely to our AI provider, which normally deletes them within 30 days\./);
  assert.match(html, /class="footer-links"><a href="privacy\.html">Privacy<\/a> <span class="h5-amp">&amp;<\/span> <a href="terms\.html">Terms<\/a> · <a href="accessibility\.html">Accessibility<\/a> · <a href="contact\.html">Contact<\/a>/);
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

test("the page does not name a person, and nothing the design dropped is left behind", () => {
  assert.ok(!/yovana|rathbone/i.test(html), "the page does not name a person");
  for (const gone of ["mascot-icon", "hv-", "hero-man", "team-people"]) assert.ok(!html.includes(gone), `leftover: ${gone}`);
});

test("colours: the locked palette is used exactly, and every text pairing meets WCAG AA", () => {
  const exact = { navy: "#071c42", cobalt: "#0756ed", gold: "#ffbc00", pale: "#f2f5f8", body: "#596b85", line: "#e2e8f0", "tint-blue": "#eaf1ff", "tint-gold": "#fff5dd", "gold-text": "#a66b00" };
  for (const [name, hex] of Object.entries(exact)) assert.strictEqual(token(name).toLowerCase(), hex, `--${name}`);
  assert.strictEqual(token("green").toLowerCase(), "#079b70");
  const [navy, cobalt, gold, goldText, pale, body] = ["navy", "cobalt", "gold", "gold-text", "pale", "body"].map(token);
  assert.ok(contrast(goldText, pale) >= 3, "dark gold on the pale bands (large text and icons)");
  assert.ok(contrast(goldText, "#ffffff") >= 3);
  assert.ok(contrast(body, pale) >= 4.5, "body gray on the pale bands");
  assert.ok(contrast(body, "#ffffff") >= 4.5, "body gray on white");
  assert.ok(contrast(cobalt, "#ffffff") >= 4.5, "links on white");
  assert.ok(contrast(cobalt, pale) >= 4.5, "the eyebrow and headline on the pale band");
  assert.ok(contrast("#ffffff", cobalt) >= 4.5, "white text on the cobalt band");
  assert.ok(contrast("#ffffff", navy) >= 4.5, "white text on the navy header button");
  assert.ok(contrast(navy, gold) >= 4.5, "navy text on the gold buttons");
  assert.ok(contrast(goldText, token("tint-gold")) >= 3, "gold icons on their pale tint");
  assert.ok(!/gradient\(/.test(css), "no gradients");
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

test("the old headline gold is gone: the headline's second line is cobalt and the 404 numeral uses the dark gold", () => {
  assert.ok(!/gold-display|e49107/i.test(css), "the retired headline gold is not left behind");
  assert.match(css, /\.h5-notfound-code \{[^}]*color: var\(--gold-text\)/);
});


// ---------- the new look (home-v7.css, learn-popup.js): Inter type, royal blue and amber gold, two hero buttons, image boxes ----------
test("the page loads its stylesheets in order and marks the body; the new look is scoped to the homepage", () => {
  const order = ["style.css", "home-v5.css", "home-v7.css", "chrome-v6.css"].map((f) => html.indexOf(`href="${f}"`));
  assert.ok(order.every((n) => n > -1), "all four stylesheets are linked");
  assert.deepStrictEqual([...order].sort((a, b) => a - b), order, "style.css, home-v5.css, home-v7.css, chrome-v6.css (chrome last)");
  assert.match(html, /<body class="home-v5 chrome-v6 home-v7">/);
  assert.ok(!read("not-found.html").includes("home-v7"), "the not-found page keeps the old look");
  const stripped = css7.replace(/\/\*[\s\S]*?\*\//g, "");
  const rules = [...stripped.matchAll(/(^|\})\s*([^{}@]+)\{/g)].map((m) => m[2].trim());
  for (const sel of rules) for (const part of sel.split(",").map((s) => s.trim()).filter(Boolean)) {
    assert.ok(/^body\.home-v7/.test(part) || /^\.(h7|learn)-/.test(part), `unscoped selector in home-v7.css: ${part}`);
  }
});

test("Inter is hosted on our own site (no outside fonts) and is the homepage typeface", () => {
  for (const w of [400, 500, 700]) {
    assert.match(css7, new RegExp(`font-weight: ${w}; font-display: swap; src: url\\("fonts/inter-latin-${w}-normal\\.woff2"\\)`));
    assert.ok(fs.existsSync(path.join(FRONTEND, "fonts", `inter-latin-${w}-normal.woff2`)), `inter ${w} file`);
  }
  assert.ok(fs.existsSync(path.join(FRONTEND, "fonts", "Inter-OFL.txt")), "the Inter licence is kept beside the font files");
  assert.match(css7, /body\.home-v7 \{[^}]*font-family: "Inter"/);
  assert.ok(!/googleapis|gstatic/.test(css7 + html), "no outside fonts");
});

test("the hero: new headline, new line, Free Tools opens the Guide popup, Learning opens the article popup, and both are real links", () => {
  assert.match(html, /<h1 id="hero-h">Your future is yours to shape\.<\/h1>/);
  assert.match(html, /<p class="h7-lead">Career tools to build your tomorrow<\/p>/);
  assert.match(html, /<a href="tool\.html" aria-haspopup="dialog" class="h7-btn h7-btn-green" data-guide-open>Free Tools<\/a>/);
  assert.match(html, /<a href="learn\.html" aria-haspopup="dialog" class="h7-btn h7-btn-gold" data-learn-open>Learning<\/a>/);
  assert.match(html, /<span>No cost\. No barriers\.<\/span>/);
  assert.ok(html.indexOf("h7-cta") < html.indexOf("h7-free"), "the line sits after the buttons");
  assert.match(html, /<blockquote><p>“The best way to predict the future is to invent it\.”<\/p><\/blockquote>\s*<figcaption>— Alan Kay<\/figcaption>/);
  assert.ok(!html.includes("how we begin") && !html.includes('id="how"'), "the three-steps section is gone");
  assert.match(css7, /\.h7-hero-photo::before \{[^}]*background: var\(--royal\)/);
  assert.match(css7, /\.h7-hero-photo::after \{[^}]*background: var\(--amber\)/);
});

test("the sizes the founder chose: headline 36px, line 19px, buttons 14px, no-cost line 11px, quote 11px, section headings 19px regular, titles 14px, descriptions 11px", () => {
  assert.match(css7, /\.h7-hero h1 \{[^}]*font-size: clamp\(1\.9rem, 1\.3rem \+ 1\.6vw, 2\.25rem\)/); // 36px at desktop width
  assert.match(css7, /\.h7-lead \{[^}]*font-size: 1\.1875rem/);
  assert.match(css7, /\.h7-btn \{[^}]*font-size: 0\.875rem/);
  assert.match(css7, /\.h7-free \{[^}]*font-size: 0\.6875rem/);
  assert.match(css7, /\.h7-statement p \{[^}]*font-size: 0\.6875rem/);
  assert.match(css7, /\.h7-h2 \{[^}]*font-size: 1\.1875rem; font-weight: 400/);
  assert.match(css7, /\.h7-title \{[^}]*font-size: 0\.875rem/);
  assert.match(css7, /\.h7-text \{[^}]*font-size: 0\.6875rem/);
  assert.match(css7, /\.h7-sub \{[^}]*font-size: 0\.6875rem/);
});

test("both hero buttons are the same size, with the text centred (equal columns, one height)", () => {
  assert.match(css7, /\.h7-cta \{[^}]*grid-template-columns: repeat\(2, 9\.4rem\)/);
  assert.match(css7, /\.h7-btn \{[^}]*align-items: center; justify-content: center;[^}]*min-height: 46px/);
});

test("four guide cards (ATS, Resume, LinkedIn, Interview) open the real articles, each with an image box and a short Read link", () => {
  const slugs = [...html.matchAll(/class="h7-guide" href="article\.html\?slug=([^"]+)"/g)].map((m) => m[1]);
  assert.deepStrictEqual(slugs, ["what-is-ats", "resume-calling-card", "honest-self-marketing", "how-we-grade"]);
  const data = read("learn-data.js");
  for (const slug of slugs) assert.ok(data.includes(slug), `article ${slug} is not in learn-data.js`);
  const titles = [...html.matchAll(/class="h7-guide"[\s\S]*?<b class="h7-title">([^<]+)<\/b>\s*<span class="h7-text">([^<]+)<\/span>/g)].map((m) => [m[1], m[2]]);
  assert.deepStrictEqual(titles, [["ATS Basics", "How resume screening works"], ["Resume Basics", "Create a resume that works"], ["LinkedIn Basics", "Build your professional profile"], ["Interview Basics", "Prepare stories, not scripts"]]);
  assert.strictEqual((html.match(/<span class="h7-link">Read <span aria-hidden="true">→<\/span><\/span>/g) || []).length, 4);
  assert.match(html, /aria-label="ATS Basics: What Is an ATS, Really\? Read the guide\."/); // the full title stays for screen readers
  assert.match(css7, /\.h7-link \{[^}]*text-decoration: none/, "no underline on the links");
});

test("six tool cards link to the same places the Guide recommends, with the short phrases, an image box and a plain Start link", () => {
  const guideHrefs = [...guide.matchAll(/toolHref: "([^"]+)"/g)].map((m) => m[1]).sort();
  const tileHrefs = [...html.matchAll(/<a class="h7-tool" href="([^"]+)"/g)].map((m) => m[1]).sort();
  assert.strictEqual(tileHrefs.length, 6);
  assert.deepStrictEqual(tileHrefs, guideHrefs);
  const cards = [...html.matchAll(/<b class="h7-title">([^<]+)<\/b><span class="h7-text">([^<]+)<\/span><\/span>\s*<span class="h7-link">Start<\/span>/g)].map((m) => [m[1], m[2]]);
  assert.deepStrictEqual(cards, [["Create", "Create your first resume"], ["Improve", "Optimize for screening"], ["Match", "Check your fit"], ["Discover", "Find hidden experiences"], ["LinkedIn", "Showcase your strengths"], ["Interview", "Master interview stories"]]);
  assert.strictEqual((html.match(/class="h7-img h7-img-(blue|gold|green)" aria-hidden="true"/g) || []).length, 10, "an image box on every guide and tool card");
});

test("the section headings, ids and closing line", () => {
  assert.match(html, /<h2 id="basics-h" class="h7-h2">Start with the basics\.<\/h2>\s*<p class="h7-sub">Learn how careers, resumes, and interviews work\.<\/p>/);
  assert.match(html, /<h2 id="tools-h" class="h7-h2">Career tools<\/h2>\s*<p class="h7-sub">Build your tomorrow!<\/p>/);
  for (const id of ["basics", "tools"]) assert.ok(html.includes(`id="${id}"`), `missing #${id}`);
  assert.match(html, /<h2 id="close-h">We don’t invent your value\. We help you see it\.<\/h2>/);
  assert.match(html, /href="tool\.html" class="h7-btn h7-btn-gold">Get Started Today/);
});

test("the Learning popup lists every article from learn-data.js, is a real dialog, and keeps keyboard focus inside", () => {
  assert.match(html, /<div id="learn-modal" class="guide-modal-overlay" hidden>/);
  assert.match(html, /role="dialog" aria-modal="true" aria-labelledby="learn-modal-heading"/);
  assert.match(html, /id="learn-close-btn"[^>]*aria-label="Close"/);
  assert.match(html, /<a href="learn\.html">See all learning resources/);
  const scripts = [...html.matchAll(/<script src="([^"]+)"/g)].map((m) => m[1]);
  assert.ok(scripts.indexOf("learn-data.js") > -1 && scripts.indexOf("learn-data.js") < scripts.indexOf("learn-popup.js"), "learn-data.js loads before learn-popup.js");
  for (const id of new Set([...learnPopup.matchAll(/getElementById\("([^"]+)"\)/g)].map((m) => m[1]))) assert.ok(html.includes(`id="${id}"`), `missing #${id}`);
  assert.match(learnPopup, /ARTICLES\.forEach/);
  assert.match(learnPopup, /article\.html\?slug=\$\{encodeURIComponent\(article\.slug\)\}/);
  assert.match(learnPopup, /querySelectorAll\("\[data-learn-open\]"\)/);
  assert.match(learnPopup, /e\.key === "Escape"/);
  assert.match(learnPopup, /learnOpener\.focus\(\)/, "focus goes back to the Learning button on close");
  assert.match(learnPopup, /e\.key === "Tab"/, "Tab stays inside the popup");
  assert.ok(!/\.innerHTML\s*=\s*[^"\s]/.test(learnPopup), "article titles are set as text, never as markup");
});

test("the Guide popup also moves focus in, keeps Tab inside and returns focus on close", () => {
  assert.match(guide, /guideOpener = document\.activeElement/);
  assert.match(guide, /guideOpener\.focus\(\)/);
  assert.match(guide, /e\.key === "Tab"/);
});

test("the new look's colours: royal blue and amber gold, and every text pairing meets WCAG AA", () => {
  const t7 = (name) => css7.match(new RegExp(`--${name}:\\s*(#[0-9a-fA-F]{6})`))[1].toLowerCase();
  assert.strictEqual(t7("royal"), "#003395");
  assert.strictEqual(t7("amber"), "#ffb000");
  assert.match(css7, /--c6-blue: #003395;/);
  assert.match(css7, /--c6-gold: #ffb000;/);
  assert.ok(contrast("#ffffff", t7("royal")) >= 4.5, "white on royal (header, closing band)");
  assert.ok(contrast(t7("royal"), "#ffffff") >= 4.5, "royal text on white");
  assert.ok(contrast(t7("ink"), t7("amber")) >= 4.5, "navy on the amber buttons");
  assert.ok(contrast("#ffffff", t7("green")) >= 4.5, "white on the green button");
  assert.ok(contrast(t7("muted"), "#ffffff") >= 4.5, "description text on white");
  assert.ok(contrast(t7("royal"), t7("tint-blue")) >= 4.5, "royal on the pale blue tint");
  assert.ok(!/gradient\(/.test(css7), "no gradients");
});

test("responsive: the hero stacks, the cards go 2-up then 1-up, and the new look adds no motion", () => {
  assert.match(css7, /@media \(max-width: 1000px\)[\s\S]*\.h7-hero \{ grid-template-columns: 1fr/);
  assert.match(css7, /@media \(max-width: 1000px\)[\s\S]*\.h7-guides \{ grid-template-columns: repeat\(2, 1fr\)/);
  assert.match(css7, /@media \(max-width: 1000px\)[\s\S]*\.h7-tools \{ grid-template-columns: repeat\(2, 1fr\)/);
  assert.match(css7, /@media \(max-width: 620px\)[\s\S]*\.h7-guides, \.h7-tools \{ grid-template-columns: 1fr/);
  assert.ok(!/animation|transition/.test(css7), "no animation");
});

test("accessibility: every tool card has a full spoken name, and the two popup buttons announce that they open a dialog", () => {
  const labels = [...html.matchAll(/<a class="h7-tool" href="[^"]+" aria-label="([^"]+)"/g)].map((m) => m[1]);
  assert.deepStrictEqual(labels, [
    "Create: Create your first resume. Start this tool.", "Improve: Optimize for screening. Start this tool.", "Match: Check your fit. Start this tool.",
    "Discover: Find hidden experiences. Start this tool.", "LinkedIn: Showcase your strengths. Start this tool.", "Interview: Master interview stories. Start this tool.",
  ]);
  assert.strictEqual((html.match(/aria-haspopup="dialog"/g) || []).length, 2);
});

test("the four guide cards carry their own drawings (code, resume with red pen, LinkedIn, interview): real files, decorative, and safe SVG", () => {
  const files = ["guide-ats", "guide-resume", "guide-linkedin", "guide-interview"];
  const used = [...html.matchAll(/<img src="img\/home\/(guide-[a-z]+)\.svg" alt="" width="360" height="160" \/>/g)].map((m) => m[1]);
  assert.deepStrictEqual(used, files, "each guide card shows its own drawing, in order, with empty alt text (decorative)");
  for (const f of files) {
    const svg = read("img", "home", `${f}.svg`);
    assert.match(svg, /^<svg xmlns="http:\/\/www\.w3\.org\/2000\/svg" viewBox="0 0 360 160"/);
    assert.ok(!/<script|onload=|onclick=|href=|<image|<foreignObject|<style/i.test(svg), `${f}.svg is plain shapes only`);
  }
  assert.match(css7, /\.h7-img img \{[^}]*object-fit: cover/);
});

test("the six tool cards carry their own drawings (page being started, before and after, match meter, magnifier, profile card, interview), decorative and safe SVG", () => {
  const files = ["tool-create", "tool-improve", "tool-match", "tool-discover", "tool-linkedin", "tool-interview"];
  const used = [...html.matchAll(/<img src="img\/home\/(tool-[a-z]+)\.svg" alt="" width="400" height="150" \/>/g)].map((m) => m[1]);
  assert.deepStrictEqual(used, files, "each tool card shows its own drawing, in order, with empty alt text (decorative)");
  for (const f of files) {
    const svg = read("img", "home", `${f}.svg`);
    assert.match(svg, /^<svg xmlns="http:\/\/www\.w3\.org\/2000\/svg" viewBox="0 0 400 150"/);
    assert.ok(!/<script|onload=|onclick=|href=|<image|<foreignObject|<style/i.test(svg), `${f}.svg is plain shapes only`);
  }
  assert.ok(!/class="h7-img[^"]*" aria-hidden="true"><\/span>/.test(html), "no empty placeholder box is left on the homepage");
});

test("copy and layout polish: card images keep the drawing's shape at every width, and the page copy is punctuated the same way throughout", () => {
  assert.match(css7, /\.h7-img \{[^}]*aspect-ratio: 360 \/ 160/);
  assert.match(css7, /\.h7-tool \.h7-img \{[^}]*aspect-ratio: 400 \/ 150/);
  assert.ok(!/\.h7-img \{[^}]*height:/.test(css7), "no fixed height that would crop the drawings at tablet width");
  assert.ok(!/Really\?\./.test(html), "no double punctuation in the spoken names");
  assert.ok(!html.includes("No Barriers"), "barriers is lower case");
  assert.match(html, /<p class="guide-modal-descriptor">Pick a guide to begin\.<\/p>/);
  const texts = [...html.matchAll(/<span class="h7-text">([^<]+)<\/span>/g)].map((m) => m[1]);
  assert.strictEqual(texts.length, 10);
  for (const x of texts) assert.ok(!/[.!?]$/.test(x) && /^[A-Z][a-z]/.test(x), `"${x}": starts with a capital, no ending period`);
});
