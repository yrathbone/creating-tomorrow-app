// Interview-draft retention wording: the rule is stated on the privacy page and at the start of the interview flow.
// The rule itself is enforced by backend/career/draft_retention.py and tested in backend/tests/test_draft_retention.py.
const test = require("node:test");
const assert = require("node:assert");
const fs = require("node:fs");
const path = require("node:path");

const frontend = path.join(__dirname, "..", "..", "..", "frontend");
const RULE = "Interview drafts are automatically deleted after 30 days without an update.";

test("the privacy page states the 30-day interview-draft rule next to the draft sentence", () => {
  const text = fs.readFileSync(path.join(frontend, "privacy.html"), "utf8").replace(/<[^>]+>/g, " ").replace(/\s+/g, " ");
  assert.ok(text.includes("until you save or discard that draft. " + RULE), "privacy page states the rule");
});

test("the interview flow shows the same notice at its start (upload step and unfinished-draft prompt)", () => {
  const html = fs.readFileSync(path.join(frontend, "career", "login.html"), "utf8");
  const uploadState = html.slice(html.indexOf('id="resume-upload-state"'), html.indexOf('id="resume-upload-form"'));
  const draftPrompt = html.slice(html.indexOf('id="resume-draft-prompt"'), html.indexOf('id="resume-upload-state"'));
  assert.ok(uploadState.includes(RULE), "upload step notice");
  assert.ok(draftPrompt.includes(RULE), "unfinished-draft prompt notice");
});
