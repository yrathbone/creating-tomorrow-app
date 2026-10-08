// The saved resume layout: loading it, saving it, and every menu starting on it.
// Runs the real frontend/career/js/resumeLayout.js in a bare VM with a stub authedFetch.
// Run:  node --test backend/tests/frontend
const test = require("node:test");
const assert = require("node:assert");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const CAREER = path.join(__dirname, "..", "..", "..", "frontend", "career");
const read = (...p) => fs.readFileSync(path.join(CAREER, ...p), "utf8");
const reply = (status, body) => async () => ({ ok: status >= 200 && status < 300, status, json: async () => body });

function load(fetchImpl) {
  const calls = [];
  const sandbox = { authedFetch: async (url, opts) => { calls.push({ url, opts }); return fetchImpl(url, opts); } };
  vm.createContext(sandbox);
  vm.runInContext(read("js", "resumeLayout.js"), sandbox);
  return { sandbox, calls, get preferred() { return vm.runInContext("preferredResumeLayout", sandbox); } };
}

test("only the three known layouts are accepted; anything else means Classic", () => {
  const { sandbox } = load(reply(200, {}));
  for (const ok of ["classic", "modern", "traditional"]) assert.strictEqual(sandbox.normalizeResumeLayout(ok), ok);
  for (const bad of ["fancy", "", "MODERN", null, undefined, 7, "__proto__", "toString"]) assert.strictEqual(sandbox.normalizeResumeLayout(bad), "classic", String(bad));
});

test("the confirmation names the layout", () => {
  const { sandbox } = load(reply(200, {}));
  assert.strictEqual(sandbox.layoutSavedMessage("modern"), "Saved. Your resumes will start on Modern from now on.");
  assert.strictEqual(sandbox.layoutSavedMessage("???"), "Saved. Your resumes will start on Classic from now on.");
});

test("loading asks GET /api/career/resume-layout (no id of any kind) and remembers the answer", async () => {
  const world = load(reply(200, { layout: "traditional" }));
  await world.sandbox.loadResumeLayoutPreference();
  assert.strictEqual(world.calls.length, 1);
  assert.strictEqual(world.calls[0].url, "/api/career/resume-layout");
  assert.ok(!world.calls[0].opts || !world.calls[0].opts.method || world.calls[0].opts.method === "GET");
  assert.strictEqual(world.preferred, "traditional");
});

test("if the server says no (the upgrade is not applied yet) or is unreachable, it stays on Classic without breaking", async () => {
  const notReady = load(reply(503, { detail: "not available yet" }));
  await notReady.sandbox.loadResumeLayoutPreference();
  assert.strictEqual(notReady.preferred, "classic");
  const down = load(async () => { throw new Error("network down"); });
  await down.sandbox.loadResumeLayoutPreference();
  assert.strictEqual(down.preferred, "classic");
});

test("saving sends only the layout name, then every menu follows", async () => {
  const world = load(reply(200, { layout: "modern" }));
  const result = await world.sandbox.savePreferredLayout("modern");
  assert.deepStrictEqual(JSON.parse(JSON.stringify(result)), { ok: true, layout: "modern" });
  assert.strictEqual(world.calls[0].url, "/api/career/resume-layout");
  assert.strictEqual(world.calls[0].opts.method, "PUT");
  assert.deepStrictEqual(JSON.parse(world.calls[0].opts.body), { layout: "modern" });
  assert.strictEqual(world.preferred, "modern");
});

test("a wrong name is never sent as-is, and a failed save keeps the old choice and says why", async () => {
  const world = load(reply(200, { layout: "classic" }));
  await world.sandbox.savePreferredLayout("<script>");
  assert.deepStrictEqual(JSON.parse(world.calls[0].opts.body), { layout: "classic" });

  const failing = load(reply(503, { detail: "The preferred resume layout is not available yet: the database upgrade (migration 0009) has not been applied." }));
  const result = await failing.sandbox.savePreferredLayout("modern");
  assert.strictEqual(result.ok, false);
  assert.match(result.message, /migration 0009/);
  assert.strictEqual(failing.preferred, "classic");
});

test("every dashboard layout menu starts on the saved choice and has a way to change it", () => {
  const html = read("login.html");
  const selects = [...html.matchAll(/<select id="([^"]+)" data-resume-layout>/g)].map((m) => m[1]);
  assert.deepStrictEqual(selects.sort(), ["general-build-layout", "general-resume-template", "job-build-layout", "job-resume-template", "profile-resume-layout"]);
  for (const [select, msg] of [["job-resume-template", "job-layout-msg"], ["general-resume-template", "general-layout-msg"]]) {
    assert.ok(html.includes(`data-layout-default="${select}" data-layout-msg="${msg}"`), `${select}: Make this my default button`);
    assert.ok(html.includes(`id="${msg}"`));
  }
  assert.ok(html.indexOf("js/resumeLayout.js") > -1 && html.indexOf("js/resumeLayout.js") < html.indexOf('src="login.js"'));
  // the saved choice is loaded before the Resumes Built cards are drawn, and the cards use it
  const login = read("login.js");
  assert.ok(login.indexOf("loadResumeLayoutPreference()") > -1 && login.indexOf("loadResumeLayoutPreference()") < login.indexOf("await loadResumeVersions()"));
  assert.match(read("js", "history.js"), /layout\.value = preferredResumeLayout/);
  assert.match(read("js", "profileBasics.js"), /savePreferredLayout\(layoutSelect\.value\)/);
});

// ---- the choice is offered where people actually are (build screens and Resumes Built cards) ----

test("both build screens offer a layout menu and 'Make this my default' before the Build button", () => {
  const html = read("login.html");
  for (const [prefix, buildBtn] of [["job", "job-build-btn"], ["general", "general-resume-build-btn"]]) {
    const select = html.indexOf(`id="${prefix}-build-layout"`);
    const button = html.indexOf(`data-layout-default="${prefix}-build-layout"`);
    const build = html.indexOf(`id="${buildBtn}"`);
    assert.ok(select > 0 && button > 0 && build > 0, prefix);
    assert.ok(select < build && button < build, `${prefix}: the menu comes before Build My Resume`);
    assert.ok(html.includes(`data-layout-msg="${prefix}-build-layout-msg"`) && html.includes(`id="${prefix}-build-layout-msg"`), prefix);
    assert.match(html.slice(select - 60, select + 40), /data-resume-layout|resume-layout-field|select/);
  }
});

test("every data-layout-default button points at a real menu and a real message line", () => {
  const html = read("login.html");
  for (const m of html.matchAll(/data-layout-default="([^"]+)" data-layout-msg="([^"]+)"/g)) {
    assert.ok(html.includes(`id="${m[1]}"`), `no menu ${m[1]}`);
    assert.ok(html.includes(`id="${m[2]}"`), `no message ${m[2]}`);
  }
});

test("the layout chosen on a build screen is the one the download screen starts on", () => {
  const els = { from: { value: "modern" }, to: { value: "classic" } };
  const sandbox = { document: { getElementById: (id) => els[id] || null, querySelectorAll: () => [] }, authedFetch: async () => ({ ok: true, json: async () => ({}) }) };
  vm.createContext(sandbox);
  vm.runInContext(read("js", "resumeLayout.js"), sandbox);
  sandbox.carryLayoutChoice("from", "to");
  assert.strictEqual(els.to.value, "modern");
  sandbox.carryLayoutChoice("missing", "to"); // quietly does nothing
  assert.strictEqual(els.to.value, "modern");
  assert.match(read("js", "jobMatch.js"), /carryLayoutChoice\("job-build-layout", "job-resume-template"\)/);
  assert.match(read("js", "generalResume.js"), /carryLayoutChoice\("general-build-layout", "general-resume-template"\)/);
});

test("each Resumes Built card can set its menu's layout as the default, and shows when it already is", () => {
  const src = read("js", "history.js");
  assert.match(src, /visualButton\("Make default"/);
  assert.match(src, /savePreferredLayout\(layout\.value\)/);
  assert.match(src, /Your default/);
  assert.match(read("login.html"), /id="resume-layout-status"/);
});
