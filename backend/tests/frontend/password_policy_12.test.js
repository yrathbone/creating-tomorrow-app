// Password length policy (12 characters) on the pages that let someone CHOOSE a password. Signing in with an existing password is unchanged.
// The Cognito pool's own minimum is a separate console setting; until it is raised, this client-side rule is the stricter one.
const test = require("node:test");
const assert = require("node:assert");
const fs = require("node:fs");
const path = require("node:path");

const FRONTEND = path.join(__dirname, "..", "..", "..", "frontend");
const html = fs.readFileSync(path.join(FRONTEND, "career", "login.html"), "utf8");

test("every new-password field requires 12 characters and the hint says so", () => {
  const fields = [...html.matchAll(/<input[^>]*autocomplete="new-password"[^>]*>/g)].map((m) => m[0]);
  assert.strictEqual(fields.length, 4, "reset page (2) and invited-person page (2)");
  for (const f of fields) assert.match(f, /minlength="12"/, f);
  assert.ok(!/minlength="8"/.test(html), "no field still asks for 8");
  assert.ok(!/At least 8 characters/.test(html), "no hint still says 8");
  assert.strictEqual((html.match(/At least 12 characters\./g) || []).length, 2);
});

test("the sign-in password field has no minimum (existing passwords keep working)", () => {
  const login = html.match(/<input[^>]*id="login-password"[^>]*>/)[0];
  assert.ok(!/minlength=/.test(login), login);
});

test("the invite-only sign-up page (which creates no account) asks for the same 12 characters, so the site says one thing", () => {
  const reg = fs.readFileSync(path.join(FRONTEND, "career", "register.html"), "utf8");
  const field = reg.match(/<input[^>]*id="signup-password"[^>]*>/)[0];
  assert.match(field, /minlength="12"/);
  assert.ok(!/minlength="8"/.test(reg));
  assert.match(reg, /At least 12 characters\./);
});

test("the invite-only page says plainly that its form cannot create an account and saves nothing", () => {
  const reg = fs.readFileSync(path.join(FRONTEND, "career", "register.html"), "utf8");
  assert.match(reg, /This form cannot create an account during the beta, and nothing you type here is saved or sent/);
  assert.match(reg, /<h1>Career Profile is by invitation<\/h1>/);
});
