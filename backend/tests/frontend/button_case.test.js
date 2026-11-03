// Button labels are sentence case ("Build my resume"); only page and tool names and proper names keep their capitals
// (docs/BUTTON-SCHEME.md, decided 2026-11-03). Static checks only. Run:  node --test backend/tests/frontend
const test = require("node:test");
const assert = require("node:assert");
const fs = require("node:fs");
const path = require("node:path");

const FRONTEND = path.join(__dirname, "..", "..", "..", "frontend");
const read = (p) => fs.readFileSync(path.join(FRONTEND, p), "utf8");
const PAGES = fs.readdirSync(FRONTEND).filter((f) => f.endsWith(".html")).concat(fs.readdirSync(path.join(FRONTEND, "career")).filter((f) => f.endsWith(".html")).map((f) => "career/" + f));

// words that keep their capitals inside a button label: tool and page names, and proper names
const NAMES = new Set(["Career", "Profile", "Tools", "Learn", "LinkedIn", "ATS", "Word", "Right", "Fit", "Elevate", "Spotlight", "Prepare", "Beginning", "Refine", "Guide", "About", "PDF", "Cognito", "Privacy", "Terms", "Free", "Skills"]);

// the text of a tag's contents without its inner tags, read one character at a time
function plainText(inner) {
  let out = "", inTag = false;
  for (const ch of inner) {
    if (ch === "<") inTag = true;
    else if (ch === ">") inTag = false;
    else if (!inTag) out += ch;
  }
  return out.replace(/&rarr;|&mdash;|&amp;|&rsquo;|&larr;/g, " ").replace(/\s+/g, " ").trim();
}

test("every button label in the pages is sentence case, apart from page, tool and proper names", () => {
  const bad = [];
  for (const page of PAGES) {
    const html = read(page);
    for (const m of html.matchAll(/<button\b[^>]*>([\s\S]*?)<\/button>/g)) {
      if (/hv-tool/.test(m[0].slice(0, m[0].indexOf(">")))) continue; // the Career Tools cards hold a drawing, a name and a description
      const label = plainText(m[1]).replace(/^[^A-Za-z]+/, "");
      if (label.length < 3 || label.length > 60 || /^[\u00d7\u2715]/.test(label)) continue; // a close mark, or a card with a paragraph inside
      const words = label.split(" ").slice(1).filter((w) => /^[A-Z][a-z]/.test(w) && !NAMES.has(w.replace(/[^A-Za-z]/g, "")));
      if (words.length) bad.push(`${page}: "${label}"`);
    }
  }
  assert.deepStrictEqual(bad, []);
});

test("the button scheme document states the rule", () => {
  const doc = fs.readFileSync(path.join(FRONTEND, "..", "docs", "BUTTON-SCHEME.md"), "utf8");
  assert.match(doc, /Button labels are sentence case/);
  assert.ok(!/Download Resume\b/.test(doc), "the examples use the sentence-case labels");
});
