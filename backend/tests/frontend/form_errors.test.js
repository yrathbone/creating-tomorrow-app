// Form errors (2026-11-04, from the Marcus Bell production run): an over-long field gets a plain sentence, not the server's validator text,
// and every error box on the dashboard is announced to screen readers when it appears.
const test = require("node:test");
const assert = require("node:assert");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const FRONTEND = path.join(__dirname, "..", "..", "..", "frontend");
const loginJs = fs.readFileSync(path.join(FRONTEND, "career", "login.js"), "utf8");
const html = fs.readFileSync(path.join(FRONTEND, "career", "login.html"), "utf8");

const start = loginJs.indexOf("// A validation entry becomes a plain sentence");
const end = loginJs.indexOf("const loginForm = ");
assert.ok(start > 0 && end > start, "the formatter is where the test expects it");
const sandbox = {};
vm.runInNewContext(loginJs.slice(start, end) + "\nthis.formatErrorDetail = formatErrorDetail;", sandbox);
const format = (detail) => sandbox.formatErrorDetail(detail, "fallback");

test("the over-long description from the live run reads as a plain sentence with the limit", () => {
  const detail = [{ type: "string_too_long", loc: ["body", "description"], msg: "String should have at most 20000 characters", ctx: { max_length: 20000 } }];
  assert.strictEqual(format(detail), "Description is too long. Please keep it under 20,000 characters.");
  assert.ok(!/body\.|String should|characters\b.*at most/.test(format(detail)));
});

test("too short, missing and unknown validation entries are plain too, and several are joined as sentences", () => {
  assert.strictEqual(format([{ type: "string_too_short", loc: ["body", "title"], msg: "x", ctx: { min_length: 2 } }]), "Title is too short. Please write at least 2 characters.");
  assert.strictEqual(format([{ type: "missing", loc: ["body", "graduation_year"], msg: "Field required" }]), "Graduation year is required.");
  assert.strictEqual(format([{ type: "value_error", loc: ["body", "end_date"], msg: "Value error, bad" }]), "End date: please check what you entered.");
  assert.strictEqual(format([
    { type: "missing", loc: ["body", "title"], msg: "Field required" },
    { type: "string_too_long", loc: ["body", "organization"], msg: "x", ctx: { max_length: 200 } },
  ]), "Title is required. Organization is too long. Please keep it under 200 characters.");
});

test("strings, empty details, objects and entries without a message still behave as before", () => {
  assert.strictEqual(format("Already a plain sentence."), "Already a plain sentence.");
  assert.strictEqual(format(null), "fallback");
  assert.strictEqual(format({ msg: "Object message" }), "Object message");
  assert.strictEqual(format([{ foo: 1 }]), '{"foo":1}');
});

test("every error box on the dashboard page is announced to screen readers", () => {
  const boxes = [...html.matchAll(/<(div|p)\b[^>]*\bclass="error"[^>]*>/g)].map((m) => m[0]);
  assert.ok(boxes.length >= 20, "found the error boxes");
  const silent = boxes.filter((tag) => !/role="alert"/.test(tag));
  assert.deepStrictEqual(silent, [], "every box has role=alert");
  for (const id of ["exp-error", "edu-error", "cert-error", "skill-error", "language-error", "consent-error", "application-form-error"]) {
    assert.match(html, new RegExp(`id="${id}" class="error" role="alert" hidden`), id);
  }
});
