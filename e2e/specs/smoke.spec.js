// J0 smoke: every public page loads, has a title and language, throws no script errors, and does not scroll sideways (J1 layout part). Runs in every
// project (three engines plus two phone-sized layouts). Local server, no AI, no sign-in.
const { test, expect } = require("../support/guard");

const PAGES = ["/", "/about.html", "/learn.html", "/privacy.html", "/accessibility.html", "/contact.html", "/tool.html", "/career/login.html"];

for (const url of PAGES) {
  test(`public page ${url} loads cleanly and fits the screen width`, async ({ page }) => {
    const errors = [];
    page.on("pageerror", (e) => errors.push(`pageerror: ${e.message}`));
    page.on("console", (m) => { if (m.type() === "error") errors.push(`console.error: ${m.text()}`); });
    const res = await page.goto(url);
    expect(res.status(), `${url} status`).toBe(200);
    await page.waitForLoadState("domcontentloaded");
    await expect(page).toHaveTitle(/.+/);
    expect(await page.locator("html").getAttribute("lang"), "html lang attribute").toBeTruthy();
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
    expect(overflow, "horizontal scroll (px)").toBeLessThanOrEqual(1);
    // the sign-in library comes from the allowed CDN; a blocked bot-check script is expected and not an error of ours
    const real = errors.filter((e) => !/challenges\.cloudflare|net::ERR_BLOCKED_BY_CLIENT|Failed to load resource/.test(e));
    expect(real, "script errors").toEqual([]);
  });
}

test("the page answers with the security headers the audit relies on", async ({ request }) => {
  const res = await request.get("/");
  const h = res.headers();
  expect(h["x-content-type-options"]).toBe("nosniff");
  expect(h["x-frame-options"]).toBeTruthy();
  expect(h["strict-transport-security"]).toBeTruthy();
  expect(h["content-security-policy"]).toContain("frame-ancestors 'none'");
});
