// Sign-in page accessibility and keyboard behaviour (E1). Uses only the local server; the sign-in form is never submitted (Cognito is blocked by the guard).
const { test, expect } = require("../support/guard");

const active = (page) => page.evaluate(() => { const e = document.activeElement; return e ? (e.id || e.tagName) : "none"; });

test("sign-in page: one visible h1, labelled fields, correct autocomplete tokens, alert and status regions", async ({ page }) => {
  await page.goto("/career/login.html");
  expect(await page.locator("h1:visible").count(), "exactly one visible h1").toBe(1);
  const fields = await page.evaluate(() => [...document.querySelectorAll("#login-form input")].map((e) => ({
    id: e.id, label: (e.labels && e.labels[0] ? e.labels[0].innerText : "").trim(), auto: e.getAttribute("autocomplete"), required: e.required, type: e.type })));
  expect(fields).toEqual([
    { id: "login-email", label: expect.stringMatching(/email/i), auto: "username", required: true, type: "email" },
    { id: "login-password", label: expect.stringMatching(/password/i), auto: "current-password", required: true, type: "password" },
  ]);
  for (const id of ["login-error", "forgot-error", "newpassword-error", "consent-error"]) {
    expect(await page.locator(`#${id}`).getAttribute("role"), `${id} announces itself to screen readers`).toBe("alert");
  }
  expect(await page.locator("#login-notice").getAttribute("role")).toBe("status");
  const dup = await page.evaluate(() => { const seen = {}; const d = []; document.querySelectorAll("[id]").forEach((e) => { if (seen[e.id]) d.push(e.id); seen[e.id] = 1; }); return d; });
  expect(dup, "duplicate ids break label and aria references").toEqual([]);
});

test("sign-in page: keyboard order is email, password, Sign in, Forgot your password", async ({ page }) => {
  await page.goto("/career/login.html");
  await page.focus("#login-email");
  const seen = [await active(page)];
  for (let i = 0; i < 3; i++) { await page.keyboard.press("Tab"); seen.push(await active(page)); }
  expect(seen).toEqual(["login-email", "login-password", "login-btn", "forgot-open-btn"]);
});

test("forgot-password panel: Enter on the link opens it and moves focus to the email field", async ({ page }) => {
  await page.goto("/career/login.html");
  await page.focus("#forgot-open-btn");
  await page.keyboard.press("Enter");
  await expect(page.locator("#forgot-email")).toBeVisible();
  expect(await active(page), "focus moves into the opened panel").toBe("forgot-email");
  await expect(page.locator("#login-form")).toBeHidden();
});

// FINDING E1-F1 (Medium-Low, WCAG 2.4.3 Focus Order), FIXED in the same branch: "Back to sign in" used to hide the panel the keyboard focus was in, so focus fell
// back to <body> and the person had to start again from the top of the page. login.js now focuses the email box. This test was first recorded as an
// expected failure (test.fail) and proved the defect; it now guards the fix.
test("forgot-password panel: Back to sign in returns focus to a control on the sign-in form", async ({ page }) => {
  await page.goto("/career/login.html");
  await page.click("#forgot-open-btn");
  await page.click("#forgot-back-btn");
  await expect(page.locator("#login-form")).toBeVisible();
  expect(["login-email", "forgot-open-btn", "login-password"], "focus returns to the sign-in form").toContain(await active(page));
});

test("every public page reflows at 320 CSS px without sideways scrolling (WCAG 1.4.10)", async ({ page }) => {
  await page.setViewportSize({ width: 320, height: 800 });
  const bad = [];
  for (const u of ["/", "/about.html", "/learn.html", "/privacy.html", "/accessibility.html", "/contact.html", "/tool.html", "/career/login.html"]) {
    await page.goto(u);
    const m = await page.evaluate(() => ({ sw: document.documentElement.scrollWidth, cw: document.documentElement.clientWidth }));
    if (m.sw > m.cw) bad.push(`${u}: ${m.sw} > ${m.cw}`);
  }
  expect(bad).toEqual([]);
});

test("sign-in inputs and the Sign in button meet the 24 px target size (WCAG 2.5.8); the inline text button is reported", async ({ page }, testInfo) => {
  await page.goto("/career/login.html");
  const boxes = await page.evaluate(() => ["login-email", "login-password", "login-btn", "forgot-open-btn"].map((id) => { const r = document.getElementById(id).getBoundingClientRect(); return { id, w: Math.round(r.width), h: Math.round(r.height) }; }));
  for (const b of boxes.filter((b) => b.id !== "forgot-open-btn")) expect(Math.min(b.w, b.h), `${b.id} is at least 24 px`).toBeGreaterThanOrEqual(24);
  const link = boxes.find((b) => b.id === "forgot-open-btn");
  if (Math.min(link.w, link.h) < 24) testInfo.annotations.push({ type: "note-E1-F2", description: `forgot-open-btn is ${link.w}x${link.h}px; allowed only through the spacing exception of WCAG 2.5.8; consider 24 px height` });
});
