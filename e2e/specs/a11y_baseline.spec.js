// Tightened accessibility baseline (E1). The first-run policy in a11y.spec.js only failed on CRITICAL violations. This spec records what axe finds today
// (support/axe_baseline.json) and fails on anything NEW: a rule that is not in the baseline for that page, or a baseline rule that now reports more elements.
// It never hides a problem: every baseline violation is still attached to the report. axe finds only part of the problems; this is not a substitute for a
// screen-reader and keyboard pass by a person.
const fs = require("fs");
const path = require("path");
const { AxeBuilder } = require("@axe-core/playwright");
const { test, expect, loadTokens } = require("../support/guard");

const BASELINE = JSON.parse(fs.readFileSync(path.join(__dirname, "..", "support", "axe_baseline.json"), "utf8"));
const TAGS = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"];
const PAGES = Object.keys(BASELINE).filter((k) => k.startsWith("/"));
const DASHBOARD = "dashboard (signed in as fictional person A)";

function judge(url, violations, testInfo) {
  const allowed = BASELINE[url] || {};
  const found = {};
  for (const v of violations) found[v.id] = v.nodes.length;
  const newRules = Object.keys(found).filter((id) => !(id in allowed));
  const grown = Object.keys(found).filter((id) => id in allowed && found[id] > allowed[id]);
  const improved = Object.keys(allowed).filter((id) => (found[id] || 0) < allowed[id]);
  for (const id of improved) testInfo.annotations.push({ type: "baseline-can-be-lowered", description: `${url}: ${id} now ${found[id] || 0}, baseline ${allowed[id]}` });
  expect({ newRules: newRules.map((id) => `${id} (${found[id]} elements)`), grown: grown.map((id) => `${id}: ${found[id]} > ${allowed[id]}`) }, `new or worse accessibility violations on ${url}`).toEqual({ newRules: [], grown: [] });
}

for (const url of PAGES) {
  test(`axe baseline: ${url} has no new or worse violations`, async ({ page }, testInfo) => {
    await page.goto(url);
    await page.waitForLoadState("domcontentloaded");
    const results = await new AxeBuilder({ page }).withTags(TAGS).analyze();
    await testInfo.attach(`axe-${url.replace(/\W+/g, "_")}.json`, { body: JSON.stringify(results.violations, null, 2), contentType: "application/json" });
    judge(url, results.violations, testInfo);
  });
}

test("axe baseline: the signed-in dashboard (fictional person A) has no new or worse violations", async ({ page, signIn, request }, testInfo) => {
  const res = await request.post("/api/career/consent", { headers: { Authorization: `Bearer ${loadTokens().A.access}` } });
  expect(res.status(), await res.text()).toBe(200);
  await signIn("A");
  await page.goto("/career/login.html");
  await expect(page.locator("#dashboard-top")).toBeVisible({ timeout: 15_000 });
  await page.waitForTimeout(1500); // let the dashboard finish rendering its status cards
  const results = await new AxeBuilder({ page }).withTags(TAGS).analyze();
  await testInfo.attach("axe-dashboard.json", { body: JSON.stringify(results.violations, null, 2), contentType: "application/json" });
  judge(DASHBOARD, results.violations, testInfo);
});

test("control: the baseline check really fails on a new violation (an unlabeled button injected into the page)", async ({ page }, testInfo) => {
  await page.goto("/about.html");
  await page.evaluate(() => { const b = document.createElement("button"); b.innerHTML = '<span aria-hidden="true">x</span>'; document.body.appendChild(b); });
  const results = await new AxeBuilder({ page }).withTags(TAGS).analyze();
  expect(results.violations.map((v) => v.id)).toContain("button-name");
  let failed = false;
  try { judge("/about.html", results.violations, testInfo); } catch (e) { failed = true; }
  expect(failed, "judge() must reject a rule that is not in the baseline").toBe(true);
});
