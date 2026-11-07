// Safety fixture for every browser test (N-06). Nothing may leave this machine except the pinned, read-only sign-in library on jsDelivr.
//   - every request to a host other than 127.0.0.1 / localhost is ABORTED and recorded; the test then FAILS with the list;
//   - requests to Cognito, Anthropic, Render, creatingtomorrow.net or AWS are named explicitly in the failure so the cause is obvious;
//   - the Cloudflare bot-check script is blocked (the local server has the bot check off);
//   - signed-in tests get tokens for two FICTIONAL people from e2e/.auth/tokens.json (written by the local server launcher; ignored by git).
const base = require("@playwright/test");
const fs = require("node:fs");
const path = require("node:path");

const ALLOWED_HOSTS = new Set(["127.0.0.1", "localhost"]);
// The sign-in library the pages load (pinned with an integrity hash in the page). Read-only static file; it receives no user data.
const ALLOWED_CDN = /^https:\/\/cdn\.jsdelivr\.net\/npm\/amazon-cognito-identity-js@[\d.]+\//;
const NAMED_FORBIDDEN = /(cognito-idp|amazonaws\.com|api\.anthropic\.com|onrender\.com|render\.com|creatingtomorrow\.net|challenges\.cloudflare\.com)/i;

function loadTokens() {
  const file = path.join(__dirname, "..", ".auth", "tokens.json");
  if (!fs.existsSync(file)) throw new Error("e2e/.auth/tokens.json is missing: the local test server writes it when it starts (CT_E2E=1).");
  return JSON.parse(fs.readFileSync(file, "utf8"));
}

// Signs a fictional person in the way the page's sign-in library expects: tokens filed in sessionStorage under the app client id.
async function signIn(page, who) {
  const tokens = loadTokens();
  const person = tokens[who];
  const prefix = `CognitoIdentityServiceProvider.${tokens.client_id}`;
  await page.addInitScript(([prefix, sub, access, id]) => {
    try {
      sessionStorage.setItem(`${prefix}.LastAuthUser`, sub);
      sessionStorage.setItem(`${prefix}.${sub}.accessToken`, access);
      sessionStorage.setItem(`${prefix}.${sub}.idToken`, id);
      sessionStorage.setItem(`${prefix}.${sub}.refreshToken`, "not-a-real-refresh-token");
      sessionStorage.setItem(`${prefix}.${sub}.clockDrift`, "0");
    } catch (e) { /* storage unavailable */ }
  }, [prefix, person.sub, person.access, person.id]);
  return person;
}

const test = base.test.extend({
  violations: async ({}, use) => { await use([]); },
  page: async ({ page, violations }, use) => {
    await page.route("**/*", (route) => {
      const url = new URL(route.request().url());
      if (url.protocol === "data:" || url.protocol === "blob:" || url.protocol === "about:") return route.continue();
      if (ALLOWED_HOSTS.has(url.hostname)) return route.continue();
      if (ALLOWED_CDN.test(route.request().url())) return route.continue();
      violations.push(`${NAMED_FORBIDDEN.test(url.hostname) ? "FORBIDDEN SERVICE" : "external"}: ${route.request().method()} ${url.origin}${url.pathname}`);
      return route.abort("blockedbyclient");
    });
    await use(page);
  },
  signIn: async ({ page }, use) => { await use((who) => signIn(page, who)); },
});

// After every test: fail if anything tried to leave the machine.
test.afterEach(async ({ violations }) => {
  base.expect(violations, "requests that tried to leave this machine were blocked").toEqual([]);
});

module.exports = { test, expect: base.expect, loadTokens };
