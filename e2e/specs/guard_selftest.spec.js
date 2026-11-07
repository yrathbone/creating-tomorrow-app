// The guard must catch every attempt to leave the machine. These tests are marked test.fail(): they PASS only when the guard fails them, which proves
// that a request to a real service (Anthropic, Cognito) or a redirect to one is detected and blocked. If the guard ever stops working, they go red.
const { test, expect } = require("../support/guard");

test("guard self-test: navigating to the Anthropic API is blocked and fails the test", async ({ page }) => {
  test.fail(true, "the guard is expected to fail this test");
  try { await page.goto("https://api.anthropic.com/v1/messages", { timeout: 8000 }); } catch (e) { /* the navigation is blocked */ }
});

test("guard self-test: navigating to the Cognito tenant is blocked and fails the test", async ({ page }) => {
  test.fail(true, "the guard is expected to fail this test");
  try { await page.goto("https://cognito-idp.us-east-2.amazonaws.com/", { timeout: 8000 }); } catch (e) { /* blocked */ }
});

test("browser-level guard: a redirect from a local page to a real service never connects (the name does not resolve)", async ({ page, browserName }) => {
  test.skip(browserName !== "chromium", "the host-name block is configured for the Chromium projects; Firefox and WebKit rely on the per-request guard only");
  // A redirect hop is followed inside the browser's network stack, below the per-request guard, so the DNS block is what protects here.
  await page.route("**/__redirect_probe__", (route) => route.fulfill({ status: 302, headers: { location: "https://creatingtomorrow.net/" } }));
  let message = "";
  try { await page.goto("/__redirect_probe__", { timeout: 8000 }); } catch (e) { message = String(e.message); }
  expect(message, "the redirect must fail to connect").toMatch(/ERR_NAME_NOT_RESOLVED|ERR_BLOCKED_BY_CLIENT|ERR_CONNECTION/);
  expect(page.url()).not.toContain("creatingtomorrow.net");
});
