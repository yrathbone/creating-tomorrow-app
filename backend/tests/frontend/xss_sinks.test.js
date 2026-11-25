// N-01: hostile-string and sink-contract tests for the places the front end writes HTML. Local, static and VM checks only; fictional strings; no network,
// no server, no production. See the N-01 inventory (N01_HTML_Sink_Inventory_2026-11-07.csv in the planning notes) for the classification of every sink.
// These tests lock in today's safe behaviour (AI, user and uploaded text is escaped or set with textContent) and document one CONFIRMED weakness as a
// todo test (the markdown link renderer), which must be fixed in a separate, reviewed change.
const test = require("node:test");
const assert = require("node:assert");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const FRONTEND = path.join(__dirname, "..", "..", "..", "frontend");
const read = (...p) => fs.readFileSync(path.join(FRONTEND, ...p), "utf8");

// Hostile strings an AI response, a job posting, a résumé or a profile field could carry (all fictional).
const HOSTILE = [
  `<script>alert(1)</script>`,
  `"><img src=x onerror=alert(1)>`,
  `' onmouseover='alert(1)`,
  `" autofocus onfocus="alert(1)`,
  `</li></ul><iframe src="javascript:alert(1)"></iframe>`,
  `<svg/onload=alert(1)>`,
  `javascript:alert(1)`,
  `&lt;b&gt;already-escaped&lt;/b&gt;`,
  "`${alert(1)}`",
  "‮<b>bidi</b>",
  `<a href="https://evil.example">x</a>`,
];

function sources() {
  const out = [];
  const walk = (dir) => {
    for (const name of fs.readdirSync(dir, { withFileTypes: true })) {
      const full = path.join(dir, name.name);
      if (name.isDirectory()) { if (!["fonts", "img", "node_modules"].includes(name.name)) walk(full); }
      else if (/\.(js|html)$/.test(name.name)) out.push(full);
    }
  };
  walk(FRONTEND);
  return out;
}

// Pull every `function escapeHtml(...) { ... }` out of the source (there are five copies) and return them as callable functions.
function escapeCopies() {
  const copies = [];
  for (const file of sources()) {
    const text = fs.readFileSync(file, "utf8");
    const m = text.match(/function escapeHtml\(str\) \{[\s\S]*?\n\}/);
    if (m) {
      const sandbox = {};
      vm.createContext(sandbox);
      vm.runInContext(m[0] + "\nthis.fn = escapeHtml;", sandbox);
      copies.push({ file: path.relative(FRONTEND, file), fn: sandbox.fn });
    }
  }
  return copies;
}

test("there are escapeHtml copies and every one neutralises & < > \" ' in every hostile string", () => {
  const copies = escapeCopies();
  assert.ok(copies.length >= 5, `expected the five known copies, found ${copies.length}`);
  for (const { file, fn } of copies) {
    for (const bad of HOSTILE) {
      const out = fn(bad);
      assert.ok(!/[<>"']/.test(out), `${file}: raw markup character left in ${JSON.stringify(out)} for ${JSON.stringify(bad)}`);
    }
    assert.strictEqual(fn(`a&b`), "a&amp;b", file);
    assert.strictEqual(fn(null), "null", file); // String(null): never throws on missing values
  }
});

test("the escapeHtml copies agree with each other on every hostile string (no drift between files)", () => {
  const copies = escapeCopies();
  for (const bad of HOSTILE) {
    const outputs = new Set(copies.map((c) => c.fn(bad)));
    assert.strictEqual(outputs.size, 1, `copies differ on ${JSON.stringify(bad)}: ${[...outputs].join(" | ")}`);
  }
});

// Find each assignment `x.innerHTML = \`...\`` (template literal, possibly multi-line) and return its ${...} expressions.
function templateSinks(text) {
  const found = [];
  const re = /innerHTML\s*=\s*`([\s\S]*?)`/g;
  let m;
  while ((m = re.exec(text))) {
    const body = m[1];
    const line = text.slice(0, m.index).split("\n").length;
    const exprs = [];
    const inner = /\$\{([^}]*)\}/g;
    let e;
    while ((e = inner.exec(body))) exprs.push(e[1].trim());
    found.push({ line, exprs });
  }
  return found;
}

// Interpolations that are safe by construction and reviewed in the N-01 inventory: a numeric loop index, a prebuilt string of escaped list items,
// a static label map entry, or the formatter result in the shared fillList helper (whose callers must escape; checked in the next test).
const SAFE_EXPR = [
  /^escapeHtml\(.+\)$/,
  /^idx$/,
  /^bulletItems$/, // built from escapeHtml(b) in scratch.js
  /^signalLabel$/, // static SIGNAL_LABELS map in prepare.js
];
// First-party static data written unescaped today (article catalog and video list in the repository). Not user, AI or uploaded text. Listed explicitly
// so that any NEW unescaped interpolation fails this test; remove an entry here when its sink is fixed (N-01 follow-up).
const FIRST_PARTY_ALLOWLIST = {
  "article.html": [/^meta\.video_youtube_id$/, /^meta\.title$/, /^err\.message$/],
  "videos.html": [/^v\.title$/, /^v\.summary$/, /^v\.youtube_id$/, /^v\.duration$/],
};

test("every interpolation inside an innerHTML template is escaped, a reviewed constant, or on the first-party allowlist", () => {
  const problems = [];
  for (const file of sources()) {
    const rel = path.relative(FRONTEND, file).replace(/\\/g, "/");
    const text = fs.readFileSync(file, "utf8");
    for (const sink of templateSinks(text)) {
      for (const expr of sink.exprs) {
        const ok = SAFE_EXPR.some((r) => r.test(expr)) || (FIRST_PARTY_ALLOWLIST[rel] || []).some((r) => r.test(expr));
        if (!ok) problems.push(`${rel}:${sink.line} unescaped \${${expr}}`);
      }
    }
  }
  assert.deepStrictEqual(problems, []);
});

test("fillList in app.js is the only shared HTML sink fed by a callback, and every caller escapes each field it returns", () => {
  const text = read("app.js");
  const calls = [...text.matchAll(/fillList\("([^"]+)",\s*[^,]+,\s*\(([a-z]+)\)\s*=>\s*(\{[\s\S]*?\n\s*\}\)|[^\n]+\))/g)];
  assert.ok(calls.length >= 5, "expected the five fillList callers with a formatter");
  for (const c of calls) {
    const bodyExprs = [...c[3].matchAll(/\$\{([^}]*)\}/g)].map((x) => x[1].trim());
    for (const expr of bodyExprs) assert.match(expr, /^escapeHtml\(/, `${c[1]}: formatter interpolates ${expr} without escapeHtml`);
    if (!bodyExprs.length) assert.match(c[3], /escapeHtml\(/, `${c[1]}: formatter does not escape its value`);
  }
  // the other fillList copies (elevate, prepare, spotlight) use textContent
  for (const f of ["elevate.js", "prepare.js", "spotlight.js"]) {
    assert.match(read(f), /function fillList[\s\S]*?li\.textContent = item;/, f);
  }
});

test("résumé, job-posting, AI-evidence and truthfulness-notice renderers on the career screens never use innerHTML with data", () => {
  for (const f of ["career/js/evidenceView.js", "career/js/suggestions.js"].filter((x) => fs.existsSync(path.join(FRONTEND, x)))) {
    assert.ok(!/innerHTML|outerHTML|insertAdjacentHTML/.test(read(f)), `${f} must build DOM with textContent`);
  }
  for (const f of ["career/js/jobMatch.js", "career/js/resumeReview.js", "career/js/skillScan.js"]) {
    const text = read(f);
    for (const sink of templateSinks(text)) assert.ok(sink.exprs.every((e) => /^escapeHtml\(/.test(e)), `${f}:${sink.line}`);
    // static string assignments only: any `innerHTML = "<...>"` literal must contain no interpolation or concatenation
    for (const m of text.matchAll(/innerHTML\s*=\s*("[^"\n]*"|'[^'\n]*')\s*([+;])/g)) assert.strictEqual(m[2], ";", `${f}: HTML string concatenated`);
  }
});

test("no front-end file evaluates strings as code (eval, new Function, string timers) or writes with document.write", () => {
  const problems = [];
  for (const file of sources()) {
    const rel = path.relative(FRONTEND, file);
    const text = fs.readFileSync(file, "utf8").split("\n").filter((l) => !l.trim().startsWith("//")).join("\n");
    if (/\beval\s*\(|new Function\s*\(/.test(text)) problems.push(`${rel}: eval/new Function`);
    if (/set(Timeout|Interval)\s*\(\s*["'`]/.test(text)) problems.push(`${rel}: string timer`);
    if (/document\.write\s*\(/.test(text)) problems.push(`${rel}: document.write`);
  }
  assert.deepStrictEqual(problems, []);
});

// ---- the one confirmed weakness: the first-party markdown renderer

function loadMarkdown() {
  const sandbox = {};
  vm.createContext(sandbox);
  vm.runInContext(read("markdown.js") + "\nthis.render = renderMarkdown;", sandbox);
  return sandbox.render;
}

test("markdown renderer: raw HTML in the source is escaped (current behaviour, kept)", () => {
  const render = loadMarkdown();
  for (const bad of [`<script>alert(1)</script>`, `<img src=x onerror=alert(1)>`, `# <b>x</b>`, `- <iframe src=x></iframe>`]) {
    const html = render(bad);
    assert.ok(!/<(script|img|iframe|b)\b/i.test(html), `raw tag survived for ${bad}: ${html}`);
  }
});

test("markdown renderer: a link cannot carry a javascript: URL or break out of its href attribute", { todo: "N-01 CONFIRMED WEAKNESS: link href is unvalidated and quotes are not escaped; only repo-controlled article files are rendered today, so it is not exploitable by a visitor; fix in a separate reviewed change" }, () => {
  const render = loadMarkdown();
  const html = render(`[click](javascript:alert(1))`);
  assert.ok(!/href="javascript:/i.test(html), html);
  const html2 = render(`[x](https://a.example" onmouseover="alert(1))`);
  assert.ok(!/ onmouseover=/i.test(html2), html2);
});
