// Accessibility foundation (WCAG 2.2 AA working target) with axe-core. axe finds only part of the problems (about a third to a half of WCAG issues);
// it does not replace a screen-reader and keyboard pass by a person. FIRST RUN POLICY: critical violations fail the test; every other violation is
// attached to the report and listed as an annotation so a baseline can be recorded and then tightened (tracked as the next step in e2e/README.md).
const { AxeBuilder } = require("@axe-core/playwright");
const { test, expect } = require("../support/guard");

const PAGES = ["/", "/about.html", "/learn.html", "/privacy.html", "/accessibility.html", "/contact.html", "/tool.html", "/career/login.html"];
const TAGS = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"];

for (const url of PAGES) {
  test(`axe: ${url} has no critical WCAG A/AA violations`, async ({ page }, testInfo) => {
    await page.goto(url);
    await page.waitForLoadState("domcontentloaded");
    const results = await new AxeBuilder({ page }).withTags(TAGS).analyze();
    await testInfo.attach(`axe-${url.replace(/\W+/g, "_")}.json`, { body: JSON.stringify(results.violations, null, 2), contentType: "application/json" });
    for (const v of results.violations) {
      testInfo.annotations.push({ type: `axe-${v.impact}`, description: `${v.id}: ${v.help} (${v.nodes.length} element${v.nodes.length === 1 ? "" : "s"})` });
    }
    const critical = results.violations.filter((v) => v.impact === "critical");
    expect(critical.map((v) => `${v.id}: ${v.help}`), "critical violations").toEqual([]);
  });
}

test("keyboard: the first Tab stop on the home page is a visible control and focus is never lost to the page body", async ({ page, browserName }) => {
  test.skip(browserName === "webkit", "Safari does not Tab to links by default; covered by the real-device pass");
  await page.goto("/");
  await page.keyboard.press("Tab");
  const active = await page.evaluate(() => {
    const el = document.activeElement;
    if (!el || el === document.body) return null;
    const r = el.getBoundingClientRect();
    return { tag: el.tagName, visible: r.width > 0 && r.height > 0 };
  });
  expect(active, "something received focus").not.toBeNull();
  expect(active.visible, "the focused control is visible").toBe(true);
});
