// The About page story: the simpler text, the promise line, and the page's call to action.
// Static checks only.  Run:  node --test backend/tests/frontend
const test = require("node:test");
const assert = require("node:assert");
const fs = require("node:fs");
const path = require("node:path");

const FRONTEND = path.join(__dirname, "..", "..", "..", "frontend");
const html = fs.readFileSync(path.join(FRONTEND, "about.html"), "utf8");

test("the About story uses the simpler text, in order, ending with the promise and the closing line", () => {
  // the quote is the page headline (kept) and is not repeated in the body
  assert.match(html, /<h1>&ldquo;Sometimes one person can change the way you see yourself\.&rdquo;<\/h1>/);
  assert.strictEqual((html.match(/one person can change the way you see yourself/g) || []).length, 1);
  const lines = [
    "Someone once helped me see how important it is to value my own experience.",
    "A résumé is just a piece of paper.",
    "That lesson stayed with me.",
    "Since then, I’ve helped many people see their experience differently",
    "That’s why I started Creating Tomorrow: to use AI tools to help others.",
    "This isn’t about making up qualifications or changing who you are.",
    "Sometimes, getting an opportunity starts with realizing you were ready to ask for it all along.",
    "A brighter tomorrow only matters if more of us have the chance to reach it.",
  ];
  let at = -1;
  for (const line of lines) {
    const i = html.indexOf(line);
    assert.ok(i > at, `missing or out of order: ${line}`);
    at = i;
  }
});

test("the promise block and the call-to-action box are gone, and the story ends with the quote", () => {
  assert.ok(!html.includes("in partnership with AI tools"));
  assert.ok(!html.includes("dozens of people"));
  assert.ok(!html.includes("We help you see it."), "the bold promise block was removed");
  assert.ok(!html.includes("You Probably Know More Than You Think"), "the call-to-action box was removed");
  assert.ok(!html.includes('class="final-cta"'));
  assert.match(html, /<p class="about-editorial-line">&ldquo;A brighter tomorrow only matters if more of us have the chance to reach it\.&rdquo;<\/p>/);
  // the quote is the very last thing in the story
  assert.ok(html.indexOf("about-editorial-line") > html.indexOf("ready to ask for it all along"));
  assert.ok(html.indexOf("</main>") > html.indexOf("about-editorial-line"));
});

test("the story is honest about AI and does not name a person", () => {
  assert.match(html, /to use AI tools to help others/);
  assert.ok(!/yovana|rathbone/i.test(html));
});
