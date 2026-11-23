// The Improve Your Resume entry page: one page with the two labelled choices, each going to its existing flow. Static checks only.
const test = require("node:test");
const assert = require("node:assert");
const fs = require("node:fs");
const path = require("node:path");

const FRONTEND = path.join(__dirname, "..", "..", "..", "frontend");
const read = (p) => fs.readFileSync(path.join(FRONTEND, p), "utf8");

test("improve.html offers the two labelled choices, each going to its existing flow, with the shared chrome and the bottom privacy note", () => {
  const html = read("improve.html");
  assert.match(html, /<body class="pages-v4 chrome-v6">/);
  assert.match(html, /<h1>Improve Your Resume<\/h1>/);
  assert.match(html, /<a class="mode-btn hv-tool hv-t-butter" href="tool\.html\?mode=refine">/, "Polish goes to the Refine flow");
  assert.match(html, /<a class="mode-btn hv-tool hv-t-mint" href="elevate\.html">/, "Find goes to the Elevate flow");
  assert.match(html, /<b>Polish what&rsquo;s already there<\/b>/);
  assert.match(html, /<b>Find experience I left out<\/b>/);
  assert.match(html, /<p class="h5-footer-privacy-link" id="privacy-note">/);
  assert.ok(!html.includes('class="privacy-mark"'), "no privacy line under the title");
});

test("Home and Career Tools link the Improve Your Resume card to the entry page; the Career Tools page has no privacy line at the top", () => {
  assert.match(read("index.html"), /<a class="h7-tool" href="improve\.html"/);
  const tool = read("tool.html");
  assert.match(tool, /<a class="mode-btn hv-tool hv-t-butter" href="improve\.html">/);
  assert.ok(!tool.includes('class="privacy-mark"'), "the top privacy line is gone; the note stays at the bottom");
  assert.match(tool, /<p class="h5-footer-privacy-link" id="privacy-note">/);
});