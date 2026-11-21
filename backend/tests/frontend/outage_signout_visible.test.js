// On the sign-in configuration outage screen, a tab that holds a saved session can still sign out. Signing out does not need
// the configuration, so the header Sign Out link must be shown there (only when a saved session hint exists).
const test = require("node:test");
const assert = require("node:assert");
const fs = require("node:fs");
const path = require("node:path");

const FRONTEND = path.join(__dirname, "..", "..", "..", "frontend");
const loginJs = fs.readFileSync(path.join(FRONTEND, "career", "login.js"), "utf8");

// The outage branch of restoreSession: from its catch of ensureAuthReady to the return that follows it.
function outageBranch() {
  const start = loginJs.indexOf("await ensureAuthReady();");
  assert.ok(start > 0, "restoreSession waits for ensureAuthReady");
  const catchAt = loginJs.indexOf("} catch (err) {", start);
  const end = loginJs.indexOf("return;", catchAt);
  assert.ok(catchAt > start && end > catchAt, "the outage branch is found");
  return loginJs.slice(catchAt, end);
}

test("outage screen: Sign Out is shown when this tab holds a saved session, and never hidden by the outage branch", () => {
  const branch = outageBranch();
  assert.match(branch, /showLoginForm\(AUTH_UNAVAILABLE_MESSAGE\)/);
  assert.match(branch, /if \(looksLikeStoredSession\(\)\) document\.getElementById\("nav-signout"\)\.hidden = false;/);
});

test("the outage Sign Out runs the same handler as the dashboard's (no second sign-out path)", () => {
  const handlers = loginJs.match(/getElementById\("nav-signout"\)\.addEventListener\("click"/g) || [];
  assert.strictEqual(handlers.length, 1, "one click handler for the header Sign Out link");
  assert.match(loginJs, /await signOutCurrentUser\(\);/);
});
