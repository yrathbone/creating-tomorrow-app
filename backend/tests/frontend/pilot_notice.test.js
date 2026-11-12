// Pilot notice (content only): adults-only line, plain pilot notice on the consent screen, matching Privacy and Terms wording.
// Nothing here claims a backup window that has not been verified: the wording says "a short time" until the founder confirms the number.
const test = require("node:test");
const assert = require("node:assert");
const fs = require("node:fs");
const path = require("node:path");

const frontend = path.join(__dirname, "..", "..", "..", "frontend");
const read = (...p) => fs.readFileSync(path.join(frontend, ...p), "utf8");
const consent = () => {
  const html = read("career", "login.html");
  return html.slice(html.indexOf('id="step-consent"'), html.indexOf("</section>", html.indexOf('id="step-consent"')));
};

test("the consent screen has a pilot notice with the age line, the read-every-line rule, the AI-provider line and the backup line", () => {
  const section = consent();
  const notice = section.slice(section.indexOf('id="pilot-notice-heading"'));
  assert.match(notice, /Please read: this is a pilot/);
  assert.match(notice, /for adults\. By continuing you confirm that you are 18 or older/);
  assert.match(notice, /Read every line of any resume we build before you use it/);
  assert.match(notice, /Tell us how it went/);
  assert.match(notice, /sent to our AI provider \(Anthropic\)/);
  assert.match(notice, /ID numbers, bank details, or other people’s private information/);
  assert.match(notice, /Our hosting provider does not keep backup copies of your information\./);
});

test("the notice is above the consent button, so it is read before the person agrees", () => {
  const section = consent();
  assert.ok(section.indexOf('id="pilot-notice"') < section.indexOf('id="consent-btn"'));
});

test("the notice states no backup number that has not been verified", () => {
  const notice = consent().slice(consent().indexOf('id="pilot-notice"'));
  assert.ok(!/\b\d+\s*(days?|hours?|weeks?)\b/i.test(notice), "no unverified retention period on the consent screen");
});

test("Privacy and Terms carry the same adults-only rule and the deletion/backup wording, with a new date", () => {
  const privacy = read("privacy.html");
  const terms = read("terms.html");
  assert.match(privacy, /you must be 18 or older to create one/);
  assert.match(privacy, /<strong>If you delete your account\.<\/strong>/);
  assert.match(privacy, /Our hosting provider does not keep backup copies of your information\./);
  assert.match(terms, /optional and is for people 18 or older/);
  assert.match(privacy, /Last updated November 11, 2026/);
  assert.match(terms, /Last updated November 4, 2026/);
});

test("the existing feedback card and deletion sentence are still there", () => {
  const html = read("career", "login.html");
  assert.match(html, /id="feedback-card"/);
  assert.match(html, /You can delete your data and account yourself at any time, from Your Data on your dashboard/);
});
