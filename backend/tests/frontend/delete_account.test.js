// "Delete my data and account": frontend/career/js/deleteAccount.js, run in a bare VM with stand-in page elements,
// a stand-in server and a stand-in sign-in service, so no real account is ever involved.
// Run:  node --test backend/tests/frontend
const test = require("node:test");
const assert = require("node:assert");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const CAREER = path.join(__dirname, "..", "..", "..", "frontend", "career");
const read = (...p) => fs.readFileSync(path.join(CAREER, ...p), "utf8");
const source = read("js", "deleteAccount.js");

function element(extra = {}) {
  const handlers = {};
  return Object.assign({
    hidden: false, disabled: false, value: "", textContent: "", attrs: {}, clicks: 0, focused: false,
    addEventListener(type, fn) { (handlers[type] = handlers[type] || []).push(fn); },
    setAttribute(k, v) { this.attrs[k] = v; },
    focus() { this.focused = true; },
    click() { this.clicks += 1; return this.fire("click"); },
    fire(type, event = {}) { return Promise.all((handlers[type] || []).map((fn) => fn(event))); },
  }, extra);
}

// opts: server -> async () => response, cognito -> "ok" | "fail"
function world(opts = {}) {
  const ids = ["delete-account-start-btn", "delete-account-panel", "delete-confirm-input", "delete-confirm-btn", "delete-cancel-btn", "delete-error",
    "delete-backup-btn", "delete-readable-btn", "export-profile-btn", "export-readable-btn", "step-profile", "nav-signout", "deleted-message", "step-deleted"];
  const els = Object.fromEntries(ids.map((id) => [id, element()]));
  els["delete-account-panel"].hidden = true;
  els["delete-confirm-btn"].disabled = true;
  els["delete-error"].hidden = true;
  els["step-deleted"].hidden = true;
  const log = [];
  const sandbox = {
    document: { getElementById: (id) => els[id] || null },
    window: { scrollTo: () => log.push("scrolled") },
    authedFetch: async (url, options) => {
      log.push({ fetch: url, method: options.method, body: JSON.parse(options.body) });
      return (opts.server || (async () => ({ ok: true, status: 200, json: async () => ({ deleted: true }) })))();
    },
    deleteCurrentCognitoUser: async () => {
      log.push("cognito-delete");
      if (opts.cognito === "fail") throw new Error("NotAuthorizedException");
    },
    clearCognitoSessionKeys: () => log.push("keys-cleared"),
  };
  vm.createContext(sandbox);
  vm.runInContext(source, sandbox);
  return { els, log, sandbox };
}

const typeWord = (w, word) => { w.els["delete-confirm-input"].value = word; return w.els["delete-confirm-input"].fire("input"); };

test("the typed word must be exactly DELETE (spaces around it are fine, other spellings are not)", () => {
  const { sandbox } = world();
  assert.strictEqual(sandbox.deleteConfirmationMatches("DELETE"), true);
  assert.strictEqual(sandbox.deleteConfirmationMatches("  DELETE \n"), true);
  for (const wrong of ["delete", "Delete", "DELET", "DELETE ME", "DELETE!", "", null, undefined, "D E L E T E"]) {
    assert.strictEqual(sandbox.deleteConfirmationMatches(wrong), false, String(wrong));
  }
});

test("opening the panel deletes nothing; the final button stays off until DELETE is typed", async () => {
  const w = world();
  await w.els["delete-account-start-btn"].click();
  assert.strictEqual(w.els["delete-account-panel"].hidden, false);
  assert.strictEqual(w.els["delete-account-start-btn"].attrs["aria-expanded"], "true");
  assert.strictEqual(w.els["delete-confirm-input"].focused, true);
  assert.strictEqual(w.els["delete-confirm-btn"].disabled, true);
  await typeWord(w, "delete");
  assert.strictEqual(w.els["delete-confirm-btn"].disabled, true, "lowercase must not enable it");
  await w.els["delete-confirm-btn"].click();
  assert.deepStrictEqual(w.log, [], "a disabled/unconfirmed click sends nothing");
  await typeWord(w, "DELETE");
  assert.strictEqual(w.els["delete-confirm-btn"].disabled, false);
  await typeWord(w, "DELETE ");
  assert.strictEqual(w.els["delete-confirm-btn"].disabled, false);
  await typeWord(w, "DELET");
  assert.strictEqual(w.els["delete-confirm-btn"].disabled, true);
});

test("pressing Enter in the box never deletes", async () => {
  const w = world();
  await typeWord(w, "DELETE");
  let prevented = false;
  await w.els["delete-confirm-input"].fire("keydown", { key: "Enter", preventDefault: () => { prevented = true; } });
  assert.strictEqual(prevented, true);
  assert.deepStrictEqual(w.log, []);
});

test("cancel closes the panel, clears what was typed and the message", async () => {
  const w = world();
  await w.els["delete-account-start-btn"].click();
  await typeWord(w, "DELETE");
  await w.els["delete-cancel-btn"].click();
  assert.strictEqual(w.els["delete-account-panel"].hidden, true);
  assert.strictEqual(w.els["delete-confirm-input"].value, "");
  assert.strictEqual(w.els["delete-confirm-btn"].disabled, true);
  assert.strictEqual(w.els["delete-account-start-btn"].attrs["aria-expanded"], "false");
});

test("the backup button presses the existing backup download button", async () => {
  const w = world();
  await w.els["delete-backup-btn"].click();
  assert.strictEqual(w.els["export-profile-btn"].clicks, 1);
  assert.strictEqual(w.els["export-readable-btn"].clicks, 0);
});

test("the readable-copy button presses the dashboard's readable download button, not the data file one", async () => {
  const w = world();
  await w.els["delete-readable-btn"].click();
  assert.strictEqual(w.els["export-readable-btn"].clicks, 1);
  assert.strictEqual(w.els["export-profile-btn"].clicks, 0);
});

test("happy path: server first, then the sign-in account, then a plain confirmation (no dashboard)", async () => {
  const w = world();
  await typeWord(w, "DELETE");
  await w.els["delete-confirm-btn"].click();
  const steps = w.log.filter((x) => typeof x !== "string" || x !== "scrolled");
  assert.deepStrictEqual(steps[0], { fetch: "/api/career/account/delete", method: "POST", body: { confirm: "DELETE" } });
  assert.deepStrictEqual(steps.slice(1), ["cognito-delete", "keys-cleared"], "our data first, then the sign-in account, then the browser is cleaned");
  assert.strictEqual(w.els["step-profile"].hidden, true);
  assert.strictEqual(w.els["nav-signout"].hidden, true);
  assert.strictEqual(w.els["step-deleted"].hidden, false);
  assert.match(w.els["deleted-message"].textContent, /sign-in account have been permanently deleted/);
});

test("if only the sign-in account could not be removed, we say so plainly and give the way to finish", async () => {
  const w = world({ cognito: "fail" });
  await typeWord(w, "DELETE");
  await w.els["delete-confirm-btn"].click();
  assert.strictEqual(w.els["step-deleted"].hidden, false);
  assert.strictEqual(w.els["step-profile"].hidden, true);
  assert.match(w.els["deleted-message"].textContent, /saved data has been permanently deleted/);
  assert.match(w.els["deleted-message"].textContent, /couldn't remove your sign-in account/);
  assert.match(w.els["deleted-message"].textContent, /yovanarathbone@creatingtomorrow\.net/);
  assert.ok(w.log.includes("keys-cleared"), "signed out either way");
});

test("if the server refuses, nothing is deleted: the sign-in account is untouched and the person is told", async () => {
  const w = world({ server: async () => ({ ok: false, status: 500, json: async () => ({ detail: "The database is busy." }) }) });
  await typeWord(w, "DELETE");
  await w.els["delete-confirm-btn"].click();
  assert.ok(!w.log.includes("cognito-delete"), "never touch the sign-in account if the data was not erased");
  assert.ok(!w.log.includes("keys-cleared"));
  assert.strictEqual(w.els["step-profile"].hidden, false);
  assert.strictEqual(w.els["step-deleted"].hidden, true);
  assert.strictEqual(w.els["delete-error"].hidden, false);
  assert.match(w.els["delete-error"].textContent, /The database is busy\. Nothing was deleted/);
  assert.strictEqual(w.els["delete-confirm-btn"].disabled, false, "they can try again");
  assert.strictEqual(w.els["delete-cancel-btn"].disabled, false);
  assert.strictEqual(w.els["delete-confirm-btn"].textContent, "Permanently delete everything");
});

test("if the connection drops mid-request we do not claim either outcome", async () => {
  const w = world({ server: async () => { throw new Error("Failed to fetch"); } });
  await typeWord(w, "DELETE");
  await w.els["delete-confirm-btn"].click();
  assert.ok(!w.log.includes("cognito-delete"));
  const msg = w.els["delete-error"].textContent;
  assert.match(msg, /couldn't confirm that the deletion finished/);
  assert.doesNotMatch(msg, /Nothing was deleted/);
});

test("a double click sends one request", async () => {
  let resolveServer;
  const slow = () => new Promise((resolve) => { resolveServer = () => resolve({ ok: true, status: 200, json: async () => ({}) }); });
  const w = world({ server: slow });
  await typeWord(w, "DELETE");
  const first = w.els["delete-confirm-btn"].click();
  const second = w.els["delete-confirm-btn"].click();
  await new Promise((r) => setTimeout(r, 10));
  resolveServer();
  await Promise.all([first, second]);
  assert.strictEqual(w.log.filter((x) => x && x.fetch).length, 1);
  assert.strictEqual(w.els["delete-confirm-btn"].textContent, "Deleting...");
});

// ---- the page itself ----
test("the dashboard has the Your Data card, the confirmation panel, the final screen and loads the script last", () => {
  const html = read("login.html");
  for (const id of ["your-data-card", "delete-account-start-btn", "delete-account-panel", "delete-confirm-input", "delete-confirm-btn", "delete-cancel-btn", "delete-error", "delete-backup-btn", "delete-readable-btn", "step-deleted", "deleted-message"]) {
    assert.ok(html.includes(`id="${id}"`), id);
  }
  assert.match(html, /id="delete-confirm-btn" class="btn-danger" disabled>/, "the final button starts disabled");
  assert.match(html, /<section id="delete-account-panel" class="delete-panel" hidden/);
  assert.match(html, /<section class="card" id="step-deleted" hidden/);
  assert.ok(html.indexOf("js/deleteAccount.js") > html.indexOf('src="login.js"'), "needs authedFetch from login.js");
  assert.ok(html.indexOf("js/deleteAccount.js") > html.indexOf("js/auth.js"));
  assert.match(read("js", "auth.js"), /function deleteCurrentCognitoUser\(\)/);
});

test("the hero has two buttons and two quiet links, and every id the other scripts bind to is still there", () => {
  const html = read("login.html");
  const actions = html.slice(html.indexOf('class="dashboard-hero-actions"'), html.indexOf('class="dashboard-hero-links"'));
  assert.deepStrictEqual([...actions.matchAll(/<button[^>]*id="([^"]+)"/g)].map((m) => m[1]), ["upload-resume-btn", "general-resume-hero-btn"]);
  const links = html.slice(html.indexOf('class="dashboard-hero-links"'), html.indexOf("</p>", html.indexOf('class="dashboard-hero-links"')));
  assert.deepStrictEqual([...links.matchAll(/<button[^>]*id="([^"]+)"/g)].map((m) => m[1]), ["import-linkedin-btn", "update-profile-btn"]);
  const login = read("login.js") + read("js", "generalResume.js");
  for (const id of ["upload-resume-btn", "import-linkedin-btn", "general-resume-hero-btn", "update-profile-btn"]) assert.ok(login.includes(`"${id}"`), `${id} is still wired`);
});

test("the consent screen no longer says deletion is 'coming soon'", () => {
  const html = read("login.html");
  assert.ok(!html.includes("self-serve button is coming"));
  assert.match(html, /You can delete your data and account yourself at any time, from Your Data on your dashboard/);
});
