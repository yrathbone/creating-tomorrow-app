// The privacy page states the retention policy: guest resume content is not saved to an account or retained on our servers;
// Anthropic's own terms govern what it processes and keeps (standard API: 30 days, with the listed exceptions); signed-in resumes
// are saved to Resumes Built and stay after sign-out. The page must not claim immediate deletion by all providers, or zero retention.
const test = require("node:test");
const assert = require("node:assert");
const fs = require("node:fs");
const path = require("node:path");

const html = fs.readFileSync(path.join(__dirname, "..", "..", "..", "frontend", "privacy.html"), "utf8");
const text = html.replace(/<[^>]+>/g, " ").replace(/\s+/g, " ");

test("guest resumes are not saved to an account or retained on our servers", () => {
  assert.match(text, /Creating Tomorrow does not save guest resume content to an account or retain it on its own servers\./);
});

test("Anthropic's own terms govern what it processes and keeps, and the standard 30-day rule and its exceptions are stated", () => {
  assert.match(text, /What Anthropic processes and keeps is governed by Anthropic.s own terms\./);
  assert.match(text, /deletes inputs and outputs within 30 days of receipt or generation/);
  assert.match(text, /up to 2 years/);
  assert.match(text, /safety classification scores for up to 7 years/);
  assert.match(text, /keeps the data for that submission for 5 years/);
  assert.match(text, /or where the law requires it/);
  assert.match(text, /do not allow deletion on request/);
  assert.match(text, /privacy\.claude\.com/);
});

test("signed-in resumes are saved to Resumes Built and stay after sign-out", () => {
  assert.match(text, /Resumes you create while signed in are saved to your Resumes Built history and stay there after you sign out/);
});

test("no claim of immediate deletion by all providers, zero retention, or the old 'typically deletes' wording", () => {
  assert.doesNotMatch(text, /typically deletes/i);
  assert.doesNotMatch(text, /zero (data )?retention/i);
  assert.doesNotMatch(text, /(deletes|delete) (it|them|everything|your (data|content)) immediately/i);
  assert.doesNotMatch(text, /all (AI )?providers (delete|erase)/i);
});
