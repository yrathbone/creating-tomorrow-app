// The dashboard's top links: Upload my resume also covers a LinkedIn export, so there is no separate Import from LinkedIn control.
const test = require("node:test");
const assert = require("node:assert");
const fs = require("node:fs");
const path = require("node:path");

const FRONTEND = path.join(__dirname, "..", "..", "..", "frontend");
const read = (...p) => fs.readFileSync(path.join(FRONTEND, ...p), "utf8");
const html = read("career", "login.html");
const loginJs = read("career", "login.js");

test("there is no separate Import from LinkedIn control, and no dangling handler for it", () => {
  assert.ok(!html.includes("import-linkedin-btn"));
  assert.ok(!loginJs.includes("import-linkedin-btn"));
  assert.ok(!/>Import from LinkedIn</.test(html));
});

test("the hero is just Upload my resume and Build a general resume", () => {
  const hero = html.slice(html.indexOf('class="dashboard-hero"'), html.indexOf('class="dh-mascot"'));
  for (const id of ["upload-resume-btn", "general-resume-hero-btn"]) assert.ok(hero.includes('id="' + id + '"'), id);
  assert.strictEqual((hero.match(/<button/g) || []).length, 2, "two controls in the hero");
  assert.ok(!hero.includes("update-profile-btn") && !loginJs.includes("update-profile-btn"), "the Update my Career Profile link and its handler are gone");
  assert.ok(!hero.includes("&middot;"), "no separator left over for a missing link");
});

test("Upload my resume opens the one upload flow, with no per-source wording switch", () => {
  assert.match(loginJs, /function openImportFlow\(\) \{\s*revealCareerProfileSections\("career-profile-editor"\);\s*document\.getElementById\("mode-resume-btn"\)\.click\(\);\s*\}/);
  assert.match(loginJs, /getElementById\("upload-resume-btn"\)\.addEventListener\("click", openImportFlow\)/);
  assert.ok(!loginJs.includes('"Import from LinkedIn"'));
});

test("the LinkedIn tip is always visible inside the upload form and says how to export a LinkedIn profile", () => {
  const tip = html.match(/<p class="hint" id="resume-linkedin-tip"[^>]*>[\s\S]*?<\/p>/)[0];
  assert.ok(!/\bhidden\b/.test(tip.slice(0, tip.indexOf(">"))), "not hidden");
  assert.match(tip, /<strong>Using LinkedIn\?<\/strong>/);
  assert.match(tip, /<strong>More<\/strong>, then <strong>Save to PDF<\/strong>/);
  assert.match(tip, /href="\.\.\/spotlight\.html"/);  // the LinkedIn review link is kept
  assert.ok(html.indexOf('id="resume-file"') < html.indexOf('id="resume-linkedin-tip"') + 2000, "the tip sits in the upload form");
});

test("other pages that pointed at Import from LinkedIn now point at Upload my resume", () => {
  const spotlight = read("spotlight.html");
  assert.ok(!spotlight.includes("Import from LinkedIn"));
  assert.match(spotlight, /<strong>Upload my resume<\/strong><\/a> on your dashboard and upload your LinkedIn PDF/);
});
