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

test("Option B: the invitation page has no password field, so the 12-character hint and sentence of the earlier interim commits are gone with the form", () => {
  const reg = fs.readFileSync(path.join(FRONTEND, "career", "register.html"), "utf8");
  assert.ok(!/<input\b/i.test(reg), "no inputs");
  assert.ok(!/new-password|At least 12 characters|This form cannot create an account/.test(reg), "nothing left of the interim wording");
});

test("both corrections survive together: the reset and invited-person pages keep the 12-character rule while the invitation page keeps no form", () => {
  assert.strictEqual((html.match(/autocomplete="new-password"/g) || []).length, 4);
  assert.strictEqual((html.match(/minlength="12"/g) || []).length, 4);
  assert.strictEqual((html.match(/At least 12 characters\./g) || []).length, 2);
  const reg = fs.readFileSync(path.join(FRONTEND, "career", "register.html"), "utf8");
  assert.ok(!/<form\b/i.test(reg));
});

test("site-wide guard: any new-password field on any page must ask for 12 characters, so neither correction can be undone by accident", () => {
  const files = [];
  (function walk(dir) {
    for (const e of fs.readdirSync(dir, { withFileTypes: true })) {
      if (e.name === "node_modules") continue;
      const full = path.join(dir, e.name);
      if (e.isDirectory()) walk(full);
      else if (e.name.endsWith(".html")) files.push(full);
    }
  })(FRONTEND);
  let seen = 0;
  for (const f of files) {
    const page = fs.readFileSync(f, "utf8");
    for (const m of page.matchAll(/<input[^>]*autocomplete="new-password"[^>]*>/g)) {
      seen++;
      const min = Number((m[0].match(/minlength="(\d+)"/) || [])[1] || 0);
      assert.ok(min >= 12, `${path.relative(FRONTEND, f)}: ${m[0]}`);
    }
  }
  assert.strictEqual(seen, 4, "exactly the four fields on the sign-in page exist today");
});
