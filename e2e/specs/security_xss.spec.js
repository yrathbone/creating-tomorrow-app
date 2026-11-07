// N-01 in a real browser: hostile text (as an AI response, a job posting or a profile field could carry it) goes through the REAL render functions of
// tool.html / app.js and must show as inert text: no script runs, no dialog opens, no element is created from the text. Fictional strings, local server.
const { test, expect } = require("../support/guard");

const HOSTILE = [
  `<img src=x onerror="window.__xss=(window.__xss||0)+1">`,
  `<script>window.__xss=(window.__xss||0)+1</script>`,
  `"><svg/onload=window.__xss=1>`,
  `' autofocus onfocus='window.__xss=1`,
  `</li></ul><iframe src="javascript:window.__xss=1"></iframe>`,
];

test.beforeEach(async ({ page }) => {
  page.on("dialog", async (d) => { await d.dismiss(); throw new Error(`a dialog opened: ${d.message()}`); });
});

test("hostile AI text in the match report is shown as text, never run", async ({ page }) => {
  await page.goto("/tool.html");
  await page.evaluate((hostile) => {
    renderMatchReport({
      match_level: "average",
      match_rationale: hostile[0],
      strengths: hostile,
      required_qualification_gaps: hostile.map((h) => ({ status: h, requirement: h, explanation: h })),
      same_word_different_job_flags: hostile.map((h) => ({ term: h, resume_meaning: h, posting_meaning: h, why_it_matters: h })),
      growth_suggestions: hostile,
      note_on_better_fit_roles: hostile[1],
    });
  }, HOSTILE);
  await page.waitForTimeout(200);
  expect(await page.evaluate(() => window.__xss), "script executed").toBeUndefined();
  const injected = await page.evaluate(() => document.querySelectorAll("#strengths-list img, #gaps-list img, #flags-list img, #growth-list img, #strengths-list iframe, #gaps-list svg, #flags-list script, #growth-list script, #strengths-list [onerror], #gaps-list [onfocus]").length);
  expect(injected, "elements created from hostile text").toBe(0);
  // the hostile strings are still visible, as plain text
  await expect(page.locator("#strengths-list")).toContainText("<img src=x");
});

test("a hostile question id cannot break out of its attribute", async ({ page }) => {
  await page.goto("/tool.html");
  await page.evaluate((hostile) => {
    renderQuestions(hostile.map((h, i) => ({ id: h, question: `Question ${i}: ${h}` })));
  }, HOSTILE);
  await page.waitForTimeout(200); // injected handlers such as onerror/onload fire asynchronously
  expect(await page.evaluate(() => window.__xss), "script executed").toBeUndefined();
  const attrs = await page.evaluate(() => [...document.querySelectorAll("#questions-list *")].flatMap((i) => [...i.attributes].map((a) => a.name)));
  expect(attrs.filter((n) => /^on/i.test(n)), "event-handler attributes created from a question id").toEqual([]);
  const injected = await page.evaluate(() => document.querySelectorAll("#questions-list img, #questions-list svg, #questions-list iframe, #questions-list script").length);
  expect(injected, "elements created from a question id").toBe(0);
});

test("the markdown article renderer escapes raw HTML (a link-URL weakness is tracked separately as N-01, see the unit test marked todo)", async ({ page }) => {
  await page.goto("/");
  await page.addScriptTag({ url: "/markdown.js" }); // loaded the way the page loads it (the policy forbids eval)
  const html = await page.evaluate(() => renderMarkdown("# Title\n\n<img src=x onerror=window.__xss=1>\n\n- <script>window.__xss=1</script>"));
  expect(html).not.toMatch(/<img|<script/i);
});
