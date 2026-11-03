// The inner pages match the homepage (batch 3 of the site-wide review, 2026-11-03): the same ten drawings on the Learn and Career Tools cards,
// and one type scale (bold blue headings, navy lead text and descriptions, gray only for small print). Static checks only.
const test = require("node:test");
const assert = require("node:assert");
const fs = require("node:fs");
const path = require("node:path");

const FRONTEND = path.join(__dirname, "..", "..", "..", "frontend");
const read = (p) => fs.readFileSync(path.join(FRONTEND, p), "utf8");

test("the Learn page shows the four guide drawings, in order, one on each card", () => {
  const html = read("learn.html");
  const used = [...html.matchAll(/<img src="img\/home\/(guide-[a-z]+)\.svg" alt="" width="360" height="160" \/>/g)].map((m) => m[1]);
  assert.deepStrictEqual(used, ["guide-ats", "guide-resume", "guide-linkedin", "guide-interview"]);
  assert.strictEqual((html.match(/class="pv-img pv-img-guide" aria-hidden="true"/g) || []).length, 4);
  assert.ok(!html.includes("hv-vicon"), "the small icon circles are gone");
  assert.strictEqual((html.match(/href="article\.html\?slug=/g) || []).length, 4, "every card is still a link to its article");
});

test("the Career Tools page shows the six tool drawings, in order, and every tool still works", () => {
  const html = read("tool.html");
  const used = [...html.matchAll(/<img src="img\/home\/(tool-[a-z]+)\.svg" alt="" width="400" height="150" \/>/g)].map((m) => m[1]);
  assert.deepStrictEqual(used, ["tool-create", "tool-improve", "tool-match", "tool-discover", "tool-linkedin", "tool-interview"]);
  assert.ok(!html.slice(0, html.indexOf('id="step-upload"')).includes("hv-vicon"), "the small icon circles are gone from the tool cards");
  for (const id of ['id="mode-refine"', 'id="mode-analyze"', 'data-mode="refine"', 'data-mode="analyze"', 'href="scratch.html"', 'href="elevate.html"', 'href="spotlight.html"', 'href="prepare.html"']) assert.ok(html.includes(id), id);
  for (const f of ["guide-ats", "guide-resume", "guide-linkedin", "guide-interview", "tool-create", "tool-improve", "tool-match", "tool-discover", "tool-linkedin", "tool-interview"]) assert.ok(fs.existsSync(path.join(FRONTEND, "img", "home", f + ".svg")), f);
});

test("one type scale on the public pages: bold blue titles, navy lead text and descriptions, drawings sized by aspect ratio", () => {
  const css = read("chrome-v6.css");
  const block = css.slice(css.indexOf("one type scale on the public pages"));
  assert.match(block, /\.pv-head p,[\s\S]*?\.page-header \.tagline,[\s\S]*?\.pv-sub,[\s\S]*?span\.hv-vdesc \{ color: #0b1f4d; \}/);
  assert.match(block, /\.pv-band \.hv-h2,[\s\S]*?\.hv-guide b,[\s\S]*?\.hv-tool b,[\s\S]*?span\.hv-vtype \{ color: var\(--c6-blue\); \}/);
  assert.match(block, /\.pv-img-guide \{ aspect-ratio: 360 \/ 160; \}/);
  assert.match(block, /\.pv-img-tool \{ aspect-ratio: 400 \/ 150; \}/);
  assert.match(block, /\.pv-img img \{[^}]*object-fit: cover/);
  assert.ok(!/body\.chrome-v6[^{]*\{[^}]*font-family/.test(block), "this block sets colors and sizes only");
});
