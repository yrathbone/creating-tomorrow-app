// Stubbed sign-in and cross-user isolation against the LOCAL server (S-03 write/delete probe, locally; the live probe is a separate approval).
// Two fictional people, A and B, hold tokens signed with a throw-away key that only this local server trusts. Nothing touches Cognito or the real database.
const { test, expect, loadTokens } = require("../support/guard");

const auth = (who) => ({ Authorization: `Bearer ${loadTokens()[who].access}` });
const experience = { title: "Cashier", organization: "Fictional Store", start_date: "2019", end_date: "2024", description: "Handled cash payments." };

async function consent(request, who) {
  const res = await request.post("/api/career/consent", { headers: auth(who) });
  expect(res.status(), await res.text()).toBe(200);
}

test("no token, a garbage token and an ID token (instead of an access token) are all refused", async ({ request }) => {
  expect((await request.get("/api/career/experiences")).status()).toBe(401);
  expect((await request.get("/api/career/experiences", { headers: { Authorization: "Bearer not.a.token" } })).status()).toBe(401);
  expect((await request.get("/api/career/experiences", { headers: { Authorization: `Bearer ${loadTokens().A.id}` } })).status()).toBe(401);
});

test("A creates an experience; B cannot read, change or delete it, and A's copy is untouched", async ({ request }) => {
  await consent(request, "A");
  await consent(request, "B");
  const created = await request.post("/api/career/experiences", { headers: auth("A"), data: experience });
  expect(created.status(), await created.text()).toBeLessThan(300);
  const id = (await created.json()).id;

  const listB = await (await request.get("/api/career/experiences", { headers: auth("B") })).json();
  expect(JSON.stringify(listB)).not.toContain("Fictional Store");

  for (const res of [
    await request.put(`/api/career/experiences/${id}`, { headers: auth("B"), data: { ...experience, title: "Hacked by B" } }),
    await request.delete(`/api/career/experiences/${id}`, { headers: auth("B") }),
  ]) expect([403, 404], "another person's record must not be reachable").toContain(res.status());

  const listA = await (await request.get("/api/career/experiences", { headers: auth("A") })).json();
  const mine = listA.find((e) => e.id === id);
  expect(mine, "A's experience still exists").toBeTruthy();
  expect(mine.title).toBe("Cashier");
});

test("a signed-in fictional person reaches their dashboard without being sent back to sign in", async ({ page, signIn, request }) => {
  await consent(request, "A");
  await signIn("A");
  const res = await page.goto("/career/login.html");
  expect(res.status()).toBe(200);
  // the page shows the dashboard when a session exists; give it time to read the stored session and call the local API
  await expect(page.locator("#dashboard-top")).toBeVisible({ timeout: 15_000 });
});
